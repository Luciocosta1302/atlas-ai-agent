"""Camada de serviço: executa o grafo e traduz o resultado para a API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
    iterations: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


class AgentService:
    """Executa uma tarefa em linguagem natural usando o grafo do agente."""

    def __init__(self, graph: CompiledStateGraph, max_iterations: int) -> None:
        self._graph = graph
        # Rede de segurança: cada iteração usa ~2 passos (agent + tools),
        # mais folga para o nó final. O limite "de negócio" fica no próprio grafo.
        self._recursion_limit = max_iterations * 2 + 3

    async def run(self, message: str) -> AgentResult:
        try:
            final_state = await self._graph.ainvoke(
                {"messages": [HumanMessage(content=message)], "iterations": 0},
                config={"recursion_limit": self._recursion_limit},
            )
        except GraphRecursionError as exc:
            raise AgentExecutionError("O agente excedeu o limite de passos.") from exc
        except Exception as exc:  # erros de rede/provedor do LLM
            logger.exception("Falha ao executar o agente")
            raise AgentExecutionError("Falha ao consultar o modelo de linguagem.") from exc

        messages = final_state["messages"]
        answer = _final_answer(messages)
        return AgentResult(
            answer=answer,
            iterations=final_state.get("iterations", 0),
            tool_calls=_collect_tool_calls(messages),
        )


def _final_answer(messages: list) -> str:
    last = messages[-1]
    if isinstance(last, AIMessage) and last.text.strip():
        return last.text.strip()
    raise AgentExecutionError("O modelo não retornou uma resposta em texto.")


def _collect_tool_calls(messages: list) -> list[ToolCallRecord]:
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
