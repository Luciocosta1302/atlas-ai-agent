"""Testes da memória de conversa (checkpointer + registro de conversas)."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import AgentService, ThreadNotFoundError, build_agent_graph
from app.agent.graph import ITERATION_LIMIT_MESSAGE
from app.config import Settings
from app.memory import InMemoryThreadRepository, new_thread_id, open_sqlite_store
from app.tools import build_tools
from tests.fakes import ScriptedChatModel, tool_call


def human_texts(messages) -> list[str]:
    return [m.text for m in messages if isinstance(m, HumanMessage)]


async def test_same_thread_remembers_previous_turns(make_service) -> None:
    service, model = make_service(
        [AIMessage(content="Prazer, Ana!"), AIMessage(content="Seu nome é Ana.")]
    )

    first = await service.run("Meu nome é Ana.")
    second = await service.run("Qual é o meu nome?", thread_id=first.thread_id)

    assert second.thread_id == first.thread_id
    assert second.answer == "Seu nome é Ana."
    # Na segunda chamada o modelo recebe o histórico completo da conversa.
    assert human_texts(model.calls[1]) == ["Meu nome é Ana.", "Qual é o meu nome?"]
    assert any(m.text == "Prazer, Ana!" for m in model.calls[1])


async def test_different_threads_are_isolated(make_service) -> None:
    service, model = make_service([AIMessage(content="Ok."), AIMessage(content="Ok.")])

    await service.run("Segredo da conversa A")
    await service.run("Pergunta da conversa B")

    assert human_texts(model.calls[1]) == ["Pergunta da conversa B"]


async def test_server_generates_unpredictable_thread_ids(make_service) -> None:
    service, _ = make_service([AIMessage(content="Oi."), AIMessage(content="Oi.")])

    first = await service.run("oi")
    second = await service.run("oi")

    assert first.thread_id != second.thread_id
    assert len(first.thread_id) == 32
    int(first.thread_id, 16)  # hexadecimal


async def test_unknown_thread_id_is_rejected(make_service) -> None:
    service, model = make_service([AIMessage(content="não deveria ser chamado")])

    with pytest.raises(ThreadNotFoundError):
        await service.run("oi", thread_id=new_thread_id())
    assert model.calls == []


async def test_result_only_reports_tool_calls_of_current_turn(make_service) -> None:
    service, _ = make_service(
        [
            tool_call("calculator", {"expression": "2 + 2"}, "c1"),
            AIMessage(content="4"),
            AIMessage(content="De nada!"),
        ]
    )

    first = await service.run("2 + 2?")
    second = await service.run("Obrigado", thread_id=first.thread_id)

    assert len(first.tool_calls) == 1
    assert second.tool_calls == []
    assert second.iterations == 1  # o contador recomeça a cada pedido


async def test_iteration_limit_leaves_a_valid_history(make_service) -> None:
    looping = [tool_call("calculator", {"expression": "1 + 1"}, f"c{i}") for i in range(2)]
    service, model = make_service([*looping, AIMessage(content="Tudo bem.")], max_iterations=2)

    limited = await service.run("loop")
    await service.run("e agora?", thread_id=limited.thread_id)

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

    thread_id = None
    for i in range(6):
        thread_id = (await service.run(f"pergunta {i}", thread_id=thread_id)).thread_id

    sent = model.calls[-1][1:]  # sem o system prompt
    assert len(sent) <= 4
    assert isinstance(sent[0], HumanMessage)  # o corte começa numa pergunta
    assert sent[-1].text == "pergunta 5"


async def test_deleted_thread_cannot_be_continued(make_service) -> None:
    service, _ = make_service([AIMessage(content="Ok.")])

    result = await service.run("lembre disso")
    await service.delete_thread(result.thread_id)

    with pytest.raises(ThreadNotFoundError):
        await service.run("do que eu falei?", thread_id=result.thread_id)


async def test_expired_threads_are_purged() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    from app.memory import ConversationStore

    now = [1_000.0]
    threads = InMemoryThreadRepository(clock=lambda: now[0])
    store = ConversationStore(checkpointer=InMemorySaver(), threads=threads)
    old = await threads.create()
    now[0] += 3_000
    recent = await threads.create()

    removed = await store.purge_expired(ttl_seconds=2_000)

    assert removed == 1
    assert not await threads.exists(old)
    assert await threads.exists(recent)


async def test_sqlite_memory_survives_restart(tmp_path: Path, reports_dir: Path) -> None:
    """Simula um reinício do servidor: fecha o banco e abre de novo."""
    database = tmp_path / "atlas.db"

    async def run_once(message: str, thread_id: str | None, reply: str):
        model = ScriptedChatModel(responses=[AIMessage(content=reply)])
        async with open_sqlite_store(database) as store:
            graph = build_agent_graph(
                model,
                build_tools("America/Sao_Paulo", reports_dir),
                max_iterations=5,
                checkpointer=store.checkpointer,
            )
            result = await AgentService(graph, store, max_iterations=5).run(message, thread_id)
        return result, model

    first, _ = await run_once("Meu nome é Ana.", None, "Prazer!")
    second, model = await run_once("Qual é o meu nome?", first.thread_id, "Ana.")

    assert second.thread_id == first.thread_id
    assert human_texts(model.calls[0]) == ["Meu nome é Ana.", "Qual é o meu nome?"]


async def test_sqlite_store_delete_and_purge(tmp_path: Path) -> None:
    async with open_sqlite_store(tmp_path / "atlas.db") as store:
        kept = await store.threads.create()
        removed = await store.threads.create()
        await store.delete(removed)

        assert await store.threads.exists(kept)
        assert not await store.threads.exists(removed)
        assert await store.purge_expired(ttl_seconds=3600) == 0
        assert await store.purge_expired(ttl_seconds=-1) == 1  # tudo "expirado"
        assert not await store.threads.exists(kept)


def test_history_limit_must_fit_one_full_turn() -> None:
    with pytest.raises(ValueError, match="MAX_HISTORY_MESSAGES"):
        Settings(agent_max_iterations=10, max_history_messages=10)
    assert Settings(agent_max_iterations=5, max_history_messages=12).max_history_messages == 12
