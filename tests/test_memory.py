"""Testes da memória de conversa (checkpointer + thread_id)."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import ITERATION_LIMIT_MESSAGE
from app.config import Settings
from tests.fakes import tool_call


def human_texts(messages) -> list[str]:
    return [m.text for m in messages if isinstance(m, HumanMessage)]


async def test_same_thread_remembers_previous_turns(make_service) -> None:
    service, model = make_service(
        [AIMessage(content="Prazer, Ana!"), AIMessage(content="Seu nome é Ana.")]
    )

    first = await service.run("Meu nome é Ana.", thread_id="conversa-1")
    second = await service.run("Qual é o meu nome?", thread_id="conversa-1")

    assert first.thread_id == second.thread_id == "conversa-1"
    assert second.answer == "Seu nome é Ana."
    # Na segunda chamada o modelo recebe o histórico completo da conversa.
    assert human_texts(model.calls[1]) == ["Meu nome é Ana.", "Qual é o meu nome?"]
    assert any(m.text == "Prazer, Ana!" for m in model.calls[1])


async def test_different_threads_are_isolated(make_service) -> None:
    service, model = make_service([AIMessage(content="Ok."), AIMessage(content="Ok.")])

    await service.run("Segredo da conversa A", thread_id="a")
    await service.run("Pergunta da conversa B", thread_id="b")

    assert human_texts(model.calls[1]) == ["Pergunta da conversa B"]


async def test_new_thread_id_is_generated_when_missing(make_service) -> None:
    service, _ = make_service([AIMessage(content="Oi."), AIMessage(content="Oi.")])

    first = await service.run("oi")
    second = await service.run("oi")

    assert first.thread_id != second.thread_id
    assert len(first.thread_id) == 32


async def test_result_only_reports_tool_calls_of_current_turn(make_service) -> None:
    service, _ = make_service(
        [
            tool_call("calculator", {"expression": "2 + 2"}, "c1"),
            AIMessage(content="4"),
            AIMessage(content="De nada!"),
        ]
    )

    first = await service.run("2 + 2?", thread_id="t")
    second = await service.run("Obrigado", thread_id="t")

    assert len(first.tool_calls) == 1
    assert second.tool_calls == []
    assert second.iterations == 1  # o contador recomeça a cada pedido


async def test_iteration_limit_leaves_a_valid_history(make_service) -> None:
    looping = [tool_call("calculator", {"expression": "1 + 1"}, f"c{i}") for i in range(2)]
    service, model = make_service([*looping, AIMessage(content="Tudo bem.")], max_iterations=2)

    limited = await service.run("loop", thread_id="t")
    await service.run("e agora?", thread_id="t")

    assert limited.answer == ITERATION_LIMIT_MESSAGE
    # Todo pedido de ferramenta no histórico enviado ao modelo tem um resultado.
    history = model.calls[-1]
    answered = {m.tool_call_id for m in history if isinstance(m, ToolMessage)}
    requested = {c["id"] for m in history if isinstance(m, AIMessage) for c in m.tool_calls}
    assert requested <= answered
    assert any(m.text == ITERATION_LIMIT_MESSAGE for m in history)


async def test_history_sent_to_model_is_trimmed(make_service) -> None:
    replies = [AIMessage(content=f"resposta {i}") for i in range(6)]
    service, model = make_service(replies, max_iterations=1, max_history_messages=4)

    for i in range(6):
        await service.run(f"pergunta {i}", thread_id="t")

    sent = model.calls[-1][1:]  # sem o system prompt
    assert len(sent) <= 4
    assert isinstance(sent[0], HumanMessage)  # o corte começa numa pergunta
    assert sent[-1].text == "pergunta 5"


async def test_delete_thread_forgets_history(make_service) -> None:
    service, model = make_service([AIMessage(content="Ok."), AIMessage(content="Ok.")])

    await service.run("lembre disso", thread_id="t")
    await service.delete_thread("t")
    await service.run("do que eu falei?", thread_id="t")

    assert human_texts(model.calls[1]) == ["do que eu falei?"]


def test_history_limit_must_fit_one_full_turn() -> None:
    with pytest.raises(ValueError, match="MAX_HISTORY_MESSAGES"):
        Settings(agent_max_iterations=10, max_history_messages=10)
    assert Settings(agent_max_iterations=5, max_history_messages=12).max_history_messages == 12
