"""Testes do streaming (serviço e endpoint SSE) e da interface web."""

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent import AgentExecutionError
from app.api.dependencies import get_agent_service
from app.main import app
from tests.fakes import tool_call


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """Converte o corpo text/event-stream em uma lista de (evento, dados)."""
    events = []
    for block in text.strip().split("\n\n"):
        event, data = "message", []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            events.append((event, json.loads("\n".join(data))))
    return events


async def test_service_stream_emits_tool_and_done_events(make_service) -> None:
    service, _ = make_service(
        [
            tool_call("calculator", {"expression": "6 * 7"}, "c1"),
            AIMessage(content="O resultado é 42."),
        ]
    )

    events = [e async for e in service.stream("6 * 7?", thread_id="t")]
    types = [e.type for e in events]

    assert types.index("tool_call") < types.index("tool_result") < types.index("done")
    assert types[-1] == "done"
    assert events[types.index("tool_call")].data == {
        "name": "calculator",
        "args": {"expression": "6 * 7"},
    }
    assert events[types.index("tool_result")].data == {"name": "calculator", "output": "42"}
    assert "".join(e.data["text"] for e in events if e.type == "token") == "O resultado é 42."
    done = events[-1].data
    assert done["answer"] == "O resultado é 42."
    assert done["thread_id"] == "t"
    assert done["tool_calls"] == [
        {"name": "calculator", "args": {"expression": "6 * 7"}, "output": "42"}
    ]


async def test_streamed_turns_are_remembered(make_service) -> None:
    service, model = make_service([AIMessage(content="Oi, Ana."), AIMessage(content="Ana.")])

    [e async for e in service.stream("Sou a Ana", thread_id="t")]
    result = await service.run("Quem sou eu?", thread_id="t")

    assert result.answer == "Ana."
    assert any(m.text == "Sou a Ana" for m in model.calls[1])


async def test_service_stream_wraps_llm_failure(make_service) -> None:
    service, _ = make_service([])

    with pytest.raises(AgentExecutionError):
        [e async for e in service.stream("oi")]


def test_stream_endpoint(client: TestClient, make_service) -> None:
    service, _ = make_service(
        [tool_call("calculator", {"expression": "2 ** 10"}, "c1"), AIMessage(content="1024")]
    )
    app.dependency_overrides[get_agent_service] = lambda: service

    response = client.post("/chat/stream", json={"message": "2 ** 10?", "thread_id": "abc"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [name for name, _ in events if name != "token"] == ["tool_call", "tool_result", "done"]
    assert events[-1][1]["answer"] == "1024"
    assert events[-1][1]["thread_id"] == "abc"


def test_stream_endpoint_reports_failures_as_error_event(client: TestClient, make_service) -> None:
    service, _ = make_service([])
    app.dependency_overrides[get_agent_service] = lambda: service

    response = client.post("/chat/stream", json={"message": "oi"})

    assert response.status_code == 200
    assert parse_sse(response.text) == [
        ("error", {"detail": "Falha ao consultar o modelo de linguagem."})
    ]


def test_stream_endpoint_validates_before_streaming(
    client: TestClient, make_service, monkeypatch
) -> None:
    monkeypatch.setenv("MAX_MESSAGE_LENGTH", "5")
    service, _ = make_service([AIMessage(content="x")])
    app.dependency_overrides[get_agent_service] = lambda: service

    assert client.post("/chat/stream", json={"message": "   "}).status_code == 422
    assert client.post("/chat/stream", json={"message": "123456"}).status_code == 422


def test_stream_endpoint_without_api_key_returns_503(client: TestClient) -> None:
    assert client.post("/chat/stream", json={"message": "oi"}).status_code == 503


def test_delete_thread_endpoint(client: TestClient, make_service) -> None:
    service, model = make_service([AIMessage(content="Ok."), AIMessage(content="Ok.")])
    app.dependency_overrides[get_agent_service] = lambda: service

    client.post("/chat", json={"message": "lembre: azul", "thread_id": "t1"})
    assert client.delete("/threads/t1").status_code == 204
    client.post("/chat", json={"message": "qual cor?", "thread_id": "t1"})

    assert not any(m.text == "lembre: azul" for m in model.calls[1])
    assert client.delete("/threads/inv%C3%A1lido!").status_code == 422


def test_web_ui_is_served(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Atlas AI" in response.text
    assert "/chat/stream" in response.text
