"""Injeção de dependências do FastAPI.

O serviço do agente é criado sob demanda (e cacheado). Nos testes,
``app.dependency_overrides[get_agent_service]`` troca o serviço real por um
que usa um modelo falso, sem precisar de chave de API.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.memory import InMemorySaver

from app.agent import AgentService, build_agent_graph
from app.config import get_settings
from app.llm import create_chat_model
from app.tools import build_tools


@lru_cache
def get_agent_service() -> AgentService:
    settings = get_settings()
    graph = build_agent_graph(
        model=create_chat_model(settings),
        tools=build_tools(settings.default_timezone, settings.reports_dir),
        max_iterations=settings.agent_max_iterations,
        max_history_messages=settings.max_history_messages,
        # Memória em RAM: simples e sem dependências, mas se perde ao reiniciar
        # e não é compartilhada entre processos. Em produção, troque por um
        # checkpointer persistente (ex.: PostgresSaver).
        checkpointer=InMemorySaver(),
    )
    return AgentService(graph, max_iterations=settings.agent_max_iterations)
