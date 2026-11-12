"""Grafo LangGraph do agente (ciclo ReAct: raciocinar -> agir -> observar).

    START -> agent --(tool_calls e iterações < limite)--> tools -> agent
                   --(resposta final)--------------------> END
                   --(limite atingido)--> iteration_limit -> END

O grafo foi escrito explicitamente com ``StateGraph`` (em vez de um agente
pronto) para deixar visível cada etapa do loop e onde fica o limite de iterações.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
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
) -> CompiledStateGraph:
    """Monta e compila o grafo do agente.

    Args:
        model: qualquer chat model do LangChain com suporte a tool calling.
            Receber o modelo por parâmetro permite usar um modelo falso nos testes.
        tools: ferramentas que o modelo pode chamar.
        max_iterations: número máximo de chamadas ao modelo por requisição.
    """
    model_with_tools = model.bind_tools(tools)
    system_message = SystemMessage(content=SYSTEM_PROMPT)

    async def call_model(state: AgentState) -> dict:
        response = await model_with_tools.ainvoke([system_message, *state["messages"]])
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
        return {"messages": [AIMessage(content=ITERATION_LIMIT_MESSAGE)]}

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
    return graph.compile()
