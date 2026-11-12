from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import AgentService, build_agent_graph
from app.config import get_settings
from app.main import app
from app.memory import ConversationStore, InMemoryThreadRepository
from app.tools import build_tools
from tests.fakes import ScriptedChatModel


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Garante que nenhum teste use uma chave real nem grave fora de tmp_path."""
    for name in ("GEMINI_API_KEY", "ATLAS_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data" / "atlas.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.chdir(tmp_path)  # evita ler um .env do desenvolvedor
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    return tmp_path / "reports"


@pytest.fixture
def make_service(reports_dir: Path) -> Callable[..., tuple[AgentService, ScriptedChatModel]]:
    def _make(
        responses: list[AIMessage], max_iterations: int = 5, max_history_messages: int = 30
    ) -> tuple[AgentService, ScriptedChatModel]:
        model = ScriptedChatModel(responses=responses)
        store = ConversationStore(checkpointer=InMemorySaver(), threads=InMemoryThreadRepository())
        graph = build_agent_graph(
            model=model,
            tools=build_tools("America/Sao_Paulo", reports_dir),
            max_iterations=max_iterations,
            max_history_messages=max_history_messages,
            checkpointer=store.checkpointer,
        )
        return AgentService(graph, store, max_iterations=max_iterations), model

    return _make


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
