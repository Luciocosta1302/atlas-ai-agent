"""Grafo LangGraph do agente (ciclo ReAct: raciocinar -> agir -> observar).

    START -> agent --(tool_calls e iterações < limite)--> tools -> agent
                   --(resposta final)--------------------> END
                   --(limite atingido)--> iteration_limit -> END

O grafo foi escrito explicitamente com ``StateGraph`` (em vez de um agente
pronto) para deixar visível cada etapa do loop e onde fica o limite de iterações.

Memória: quando um ``checkpointer`` é informado, o LangGraph salva o estado ao
fim de cada passo, separado por ``thread_id``. Na próxima requisição com o mesmo
``thread_id``, o histórico anterior é carregado automaticamente.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, trim_messages
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from app.agent.prompts import SYSTEM_PROMPT

ITERATION_LIMIT_MESSAGE = (
    "Não consegui concluir a tarefa dentro do limite de etapas permitido. "
    "Tente dividir o pedido em partes menores."
)


class AgentState(MessagesState):
    """Estado do grafo: histórico de mensagens + contador de chamadas ao modelo."""

    iterations: int


def build_agent_graph(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    max_iterations: int,
    max_history_messages: int = 30,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Monta e compila o grafo do agente.

    Args:
        model: qualquer chat model do LangChain com suporte a tool calling.
            Receber o modelo por parâmetro permite usar um modelo falso nos testes.
        tools: ferramentas que o modelo pode chamar.
        max_iterations: número máximo de chamadas ao modelo por requisição.
        max_history_messages: quantas mensagens recentes são enviadas ao modelo.
        checkpointer: onde o estado das conversas é salvo (memória). ``None``
            torna cada execução independente.
    """
    model_with_tools = model.bind_tools(tools)
    system_message = SystemMessage(content=SYSTEM_PROMPT)

    async def call_model(state: AgentState) -> dict:
        # Envia só as mensagens mais recentes, para o custo e o tamanho do
        # contexto não crescerem sem limite. ``start_on="human"`` garante que o
        # corte nunca separe um pedido de ferramenta do seu resultado.
        history = trim_messages(
            state["messages"],
            max_tokens=max_history_messages,
            token_counter=len,  # conta mensagens, não tokens
            strategy="last",
            start_on="human",
        )
        response = await model_with_tools.ainvoke([system_message, *history])
        return {"messages": [response], "iterations": state.get("iterations", 0) + 1}

    def route_after_model(
        state: AgentState,
    ) -> Literal["tools", "iteration_limit", "__end__"]:
        last_message = state["messages"][-1]
        if not (isinstance(last_message, AIMessage) and last_message.tool_calls):
            return END
        if state["iterations"] >= max_iterations:
            return "iteration_limit"
        return "tools"

    def stop_at_iteration_limit(state: AgentState) -> dict:
        # Substitui (mesmo id) o último pedido de ferramenta, que não será
        # executado. Assim o histórico salvo não fica com uma chamada de
        # ferramenta sem resposta, o que a API do Gemini rejeitaria no turno seguinte.
        last_message = state["messages"][-1]
        return {"messages": [AIMessage(content=ITERATION_LIMIT_MESSAGE, id=last_message.id)]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    # handle_tool_errors=True: exceções inesperadas viram uma ToolMessage de erro
    # que o modelo consegue ler, em vez de derrubar a requisição.
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    graph.add_node("iteration_limit", stop_at_iteration_limit)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_model)
    graph.add_edge("tools", "agent")
    graph.add_edge("iteration_limit", END)
    return graph.compile(checkpointer=checkpointer)
