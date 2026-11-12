"""Injeção de dependências do FastAPI.

O banco da memória é aberto no ``lifespan`` da aplicação (``app/main.py``) e
fica em ``app.state.store``. O serviço do agente é criado na primeira
requisição e reaproveitado. Nos testes, ``app.dependency_overrides`` troca
``get_agent_service`` por um serviço com modelo falso, sem chave de API.
"""

from __future__ import annotations

from fastapi import Request

from app.agent import AgentService, build_agent_graph
from app.config import get_settings
from app.llm import create_chat_model
from app.tools import build_tools


def get_agent_service(request: Request) -> AgentService:
    state = request.app.state
    service: AgentService | None = getattr(state, "agent_service", None)
    if service is None:
        settings = get_settings()
        graph = build_agent_graph(
            model=create_chat_model(settings),  # lança MissingAPIKeyError -> 503
            tools=build_tools(settings.default_timezone, settings.reports_dir),
            max_iterations=settings.agent_max_iterations,
            max_history_messages=settings.max_history_messages,
            checkpointer=state.store.checkpointer,
        )
        service = AgentService(graph, state.store, settings.agent_max_iterations)
        state.agent_service = service
    return service
