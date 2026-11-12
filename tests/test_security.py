"""Testes dos controles de segurança: token, limite de requisições, cabeçalhos e ids."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.api.dependencies import get_agent_service
from app.config import Settings, get_settings
from app.main import app
from app.memory import new_thread_id
from app.security import RateLimiter

TOKEN = "token-de-teste-com-32-caracteres"


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch, make_service):
    """Define variáveis de ambiente e devolve um TestClient iniciado depois delas."""

    def _configure(**env: str) -> Iterator[TestClient]:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        service, _ = make_service([AIMessage(content="Ok.") for _ in range(20)])
        app.dependency_overrides[get_agent_service] = lambda: service
        return TestClient(app, raise_server_exceptions=False)

    return _configure


# ------------------------------------------------------------------ RateLimiter


def test_rate_limiter_blocks_after_limit_and_recovers() -> None:
    now = [0.0]
    limiter = RateLimiter(limit=2, window=60, clock=lambda: now[0])

    assert limiter.check("ip") is None
    assert limiter.check("ip") is None
    assert limiter.check("ip") == pytest.approx(60)  # espera até a 1ª sair da janela
    assert limiter.check("outro-ip") is None  # cada cliente tem sua cota

    now[0] = 61
    assert limiter.check("ip") is None


def test_rate_limiter_memory_is_bounded() -> None:
    now = [0.0]
    limiter = RateLimiter(limit=5, window=60, max_clients=3, clock=lambda: now[0])
    for i in range(3):
        limiter.check(f"ip-{i}")

    now[0] = 120  # todos ficaram inativos
    limiter.check("ip-novo")

    assert len(limiter._hits) == 1


def test_chat_returns_429_with_retry_after(configure) -> None:
    with configure(RATE_LIMIT_PER_MINUTE="2") as client:
        statuses = [client.post("/chat", json={"message": "oi"}).status_code for _ in range(3)]
        blocked = client.post("/chat", json={"message": "oi"})
        health = client.get("/health")

    assert statuses == [200, 200, 429]
    assert int(blocked.headers["retry-after"]) >= 1
    assert health.status_code == 200  # rotas públicas não entram no limite


# ------------------------------------------------------------------------ token


def test_token_is_required_when_configured(configure) -> None:
    with configure(ATLAS_API_TOKEN=TOKEN) as client:
        missing = client.post("/chat", json={"message": "oi"})
        wrong = client.post(
            "/chat", json={"message": "oi"}, headers={"Authorization": "Bearer errado"}
        )
        ok = client.post(
            "/chat", json={"message": "oi"}, headers={"Authorization": f"Bearer {TOKEN}"}
        )
        stream = client.post("/chat/stream", json={"message": "oi"})
        delete = client.delete(f"/threads/{new_thread_id()}")
        public = [client.get("/").status_code, client.get("/health").status_code]

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert stream.status_code == 401
    assert delete.status_code == 401
    assert public == [200, 200]


def test_api_is_open_without_token(configure) -> None:
    with configure() as client:
        assert client.post("/chat", json={"message": "oi"}).status_code == 200


def test_token_settings_validation() -> None:
    assert Settings(atlas_api_token="").atlas_api_token is None
    with pytest.raises(ValueError, match="16 caracteres"):
        Settings(atlas_api_token="curto")


# ------------------------------------------------------------ ids de conversa


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_unknown_thread_id_returns_404(configure, path: str) -> None:
    with configure() as client:
        response = client.post(path, json={"message": "oi", "thread_id": new_thread_id()})

    assert response.status_code == 404
    assert "não encontrada" in response.json()["detail"]


@pytest.mark.parametrize("thread_id", ["conversa-1", "ABCDEF" * 6, "a" * 31])
def test_client_chosen_thread_ids_are_rejected(configure, thread_id: str) -> None:
    with configure() as client:
        response = client.post("/chat", json={"message": "oi", "thread_id": thread_id})

    assert response.status_code == 422


# --------------------------------------------------- cabeçalhos e tamanho do corpo


def test_security_headers(configure) -> None:
    with configure() as client:
        response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_oversized_body_is_rejected_before_parsing(configure) -> None:
    with configure() as client:
        response = client.post(
            "/chat",
            content=b'{"message": "' + b"a" * 70_000 + b'"}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413


def test_web_ui_has_strict_csp(configure) -> None:
    with configure() as client:
        csp = client.get("/").headers["content-security-policy"]

    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "frame-ancestors 'none'" in csp


def test_global_limit_caps_all_clients_together(configure) -> None:
    # Simula clientes diferentes trocando o IP a cada requisição.
    with configure(RATE_LIMIT_PER_MINUTE="100", GLOBAL_RATE_LIMIT_PER_MINUTE="3") as client:
        limiter = client.app.state.rate_limiter
        statuses = []
        for i in range(4):
            limiter._hits.clear()  # "IP novo" a cada vez: o limite por cliente não ajuda
            statuses.append(client.post("/chat", json={"message": f"oi {i}"}).status_code)

    assert statuses == [200, 200, 200, 429]


def test_forged_forwarded_for_header_is_ignored(configure) -> None:
    with configure(RATE_LIMIT_PER_MINUTE="2") as client:
        statuses = [
            client.post(
                "/chat",
                json={"message": "oi"},
                headers={"X-Forwarded-For": f"203.0.113.{i}"},
            ).status_code
            for i in range(3)
        ]

    assert statuses == [200, 200, 429]
