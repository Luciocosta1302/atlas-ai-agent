"""Camada de serviço: executa o grafo e traduz o resultado para a API."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)


class AgentExecutionError(RuntimeError):
    """Falha ao executar o agente (ex.: erro do provedor de LLM)."""


@dataclass(frozen=True)
class ToolCallRecord:
    """Registro de uma chamada de ferramenta feita durante a execução."""

    name: str
    args: dict
    output: str


@dataclass(frozen=True)
class AgentResult:
    answer: str
    thread_id: str
    iterations: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass(frozen=True)
class AgentEvent:
    """Evento emitido durante o streaming.

    Tipos: ``token`` (trecho de texto do modelo), ``tool_call`` (o modelo pediu
    uma ferramenta), ``tool_result`` (resultado da ferramenta) e ``done``
    (execução concluída, com o mesmo conteúdo da resposta não-streaming).
    """

    type: str
    data: dict[str, Any]


def new_thread_id() -> str:
    return uuid.uuid4().hex


class AgentService:
    """Executa tarefas em linguagem natural usando o grafo do agente."""

    def __init__(self, graph: CompiledStateGraph, max_iterations: int) -> None:
        self._graph = graph
        # Rede de segurança: cada iteração usa ~2 passos (agent + tools),
        # mais folga para o nó final. O limite "de negócio" fica no próprio grafo.
        self._recursion_limit = max_iterations * 2 + 3

    async def run(self, message: str, thread_id: str | None = None) -> AgentResult:
        """Executa o agente e devolve a resposta completa."""
        thread_id = thread_id or new_thread_id()
        try:
            final_state = await self._graph.ainvoke(
                self._inputs(message), config=self._config(thread_id)
            )
        except GraphRecursionError as exc:
            raise AgentExecutionError("O agente excedeu o limite de passos.") from exc
        except Exception as exc:  # erros de rede/provedor do LLM
            logger.exception("Falha ao executar o agente")
            raise AgentExecutionError("Falha ao consultar o modelo de linguagem.") from exc
        return _build_result(final_state, thread_id)

    async def stream(self, message: str, thread_id: str | None = None) -> AsyncIterator[AgentEvent]:
        """Executa o agente emitindo eventos à medida que acontecem."""
        thread_id = thread_id or new_thread_id()
        config = self._config(thread_id)
        try:
            # "messages" entrega os tokens do modelo; "updates" entrega o
            # resultado de cada nó (pedidos e resultados de ferramentas).
            async for mode, payload in self._graph.astream(
                self._inputs(message), config=config, stream_mode=["messages", "updates"]
            ):
                for event in _to_events(mode, payload):
                    yield event
            final_state = (await self._graph.aget_state(config)).values
        except GraphRecursionError as exc:
            raise AgentExecutionError("O agente excedeu o limite de passos.") from exc
        except Exception as exc:
            logger.exception("Falha ao executar o agente (streaming)")
            raise AgentExecutionError("Falha ao consultar o modelo de linguagem.") from exc

        result = _build_result(final_state, thread_id)
        yield AgentEvent(
            "done",
            {
                "answer": result.answer,
                "thread_id": result.thread_id,
                "iterations": result.iterations,
                "tool_calls": [vars(c) for c in result.tool_calls],
            },
        )

    async def delete_thread(self, thread_id: str) -> None:
        """Apaga o histórico de uma conversa."""
        if self._graph.checkpointer is not None:
            await self._graph.checkpointer.adelete_thread(thread_id)

    def _config(self, thread_id: str) -> RunnableConfig:
        return {
            "recursion_limit": self._recursion_limit,
            "configurable": {"thread_id": thread_id},
        }

    @staticmethod
    def _inputs(message: str) -> dict:
        # "iterations" volta a zero a cada pedido: o limite vale por requisição.
        return {"messages": [HumanMessage(content=message)], "iterations": 0}


def _to_events(mode: str, payload: Any) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    if mode == "messages":
        chunk, metadata = payload
        is_model_text = (
            metadata.get("langgraph_node") == "agent"
            and isinstance(chunk, AIMessage)
            and chunk.text
        )
        if is_model_text:
            events.append(AgentEvent("token", {"text": chunk.text}))
    elif mode == "updates":
        for node, update in payload.items():
            for message in (update or {}).get("messages", []):
                if node == "agent" and isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        events.append(
                            AgentEvent("tool_call", {"name": call["name"], "args": call["args"]})
                        )
                elif node == "tools" and isinstance(message, ToolMessage):
                    events.append(
                        AgentEvent("tool_result", {"name": message.name, "output": message.text})
                    )
    return events


def _build_result(state: dict, thread_id: str) -> AgentResult:
    turn = _current_turn(state["messages"])
    return AgentResult(
        answer=_final_answer(turn),
        thread_id=thread_id,
        iterations=state.get("iterations", 0),
        tool_calls=_collect_tool_calls(turn),
    )


def _current_turn(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Mensagens a partir da última pergunta do usuário (o turno atual)."""
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _final_answer(messages: list[BaseMessage]) -> str:
    last = messages[-1]
    if isinstance(last, AIMessage) and last.text.strip():
        return last.text.strip()
    raise AgentExecutionError("O modelo não retornou uma resposta em texto.")


def _collect_tool_calls(messages: list[BaseMessage]) -> list[ToolCallRecord]:
    """Relaciona cada tool call do modelo com o resultado (ToolMessage) correspondente."""
    outputs = {m.tool_call_id: m.text for m in messages if isinstance(m, ToolMessage)}
    records: list[ToolCallRecord] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call["id"] in outputs:
                    records.append(
                        ToolCallRecord(
                            name=call["name"], args=call["args"], output=outputs[call["id"]]
                        )
                    )
    return records
