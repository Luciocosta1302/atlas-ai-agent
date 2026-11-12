"""Testes do endpoint HTTP com o agente substituído por um modelo falso."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.api.dependencies import get_agent_service
from app.main import app
from tests.fakes import tool_call


def override_agent(make_service, responses: list[AIMessage]) -> None:
    service, _ = make_service(responses)
    app.dependency_overrides[get_agent_service] = lambda: service


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_success_with_tool_call(client: TestClient, make_service) -> None:
    override_agent(
        make_service,
        [
            tool_call("calculator", {"expression": "6 * 7"}, "c1"),
            AIMessage(content="6 vezes 7 é 42."),
        ],
    )

    response = client.post("/chat", json={"message": "  Quanto é 6 * 7?  "})

    assert response.status_code == 200
    assert response.json() == {
        "answer": "6 vezes 7 é 42.",
        "iterations": 2,
        "tool_calls": [{"name": "calculator", "args": {"expression": "6 * 7"}, "output": "42"}],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": "    "},
        {"message": 123},
        {"message": "oi", "extra": "campo"},
    ],
)
def test_chat_rejects_invalid_input(client: TestClient, make_service, payload) -> None:
    override_agent(make_service, [AIMessage(content="não deveria ser chamado")])
    assert client.post("/chat", json=payload).status_code == 422


def test_chat_rejects_message_above_configured_limit(
    client: TestClient, make_service, monkeypatch
) -> None:
    monkeypatch.setenv("MAX_MESSAGE_LENGTH", "10")
    override_agent(make_service, [AIMessage(content="x")])

    response = client.post("/chat", json={"message": "x" * 11})

    assert response.status_code == 422
    assert "10 caracteres" in response.json()["detail"]


def test_chat_without_api_key_returns_503(client: TestClient) -> None:
    # Sem override: o serviço real tenta criar o Gemini e não encontra a chave.
    response = client.post("/chat", json={"message": "oi"})

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_chat_llm_failure_returns_502(client: TestClient, make_service) -> None:
    override_agent(make_service, [])  # modelo falso falha na primeira chamada

    response = client.post("/chat", json={"message": "oi"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Falha ao consultar o modelo de linguagem."}


def test_unexpected_error_returns_generic_500(client: TestClient) -> None:
    class BrokenService:
        async def run(self, message: str):
            raise KeyError("segredo interno")

    app.dependency_overrides[get_agent_service] = lambda: BrokenService()

    response = client.post("/chat", json={"message": "oi"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno do servidor."}
    assert "segredo" not in response.text
