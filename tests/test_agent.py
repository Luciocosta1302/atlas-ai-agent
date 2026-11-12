"""Testes do loop do agente usando um modelo falso (sem chave de API)."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from app.agent import AgentExecutionError
from app.agent.graph import ITERATION_LIMIT_MESSAGE
from tests.fakes import tool_call


async def test_answers_directly_without_tools(make_service) -> None:
    service, model = make_service([AIMessage(content="Olá! Como posso ajudar?")])

    result = await service.run("Oi")

    assert result.answer == "Olá! Como posso ajudar?"
    assert result.iterations == 1
    assert result.tool_calls == []
    assert isinstance(model.calls[0][0], SystemMessage)
    assert {t.name for t in model.bound_tools} == {
        "calculator",
        "get_current_datetime",
        "generate_report",
    }


async def test_executes_tool_and_feeds_result_back_to_model(make_service) -> None:
    service, model = make_service(
        [
            tool_call("calculator", {"expression": "(15 * 4) + 7"}, "call_1"),
            AIMessage(content="O resultado é 67."),
        ]
    )

    result = await service.run("Quanto é (15 * 4) + 7?")

    assert result.answer == "O resultado é 67."
    assert result.iterations == 2
    assert [(c.name, c.output) for c in result.tool_calls] == [("calculator", "67")]
    # A segunda chamada ao modelo deve conter a observação da ferramenta.
    observation = model.calls[1][-1]
    assert isinstance(observation, ToolMessage)
    assert observation.content == "67"


async def test_chains_multiple_tools(make_service, reports_dir: Path) -> None:
    service, _ = make_service(
        [
            tool_call("calculator", {"expression": "1200 * 12"}, "c1"),
            tool_call(
                "generate_report",
                {"title": "Receita anual", "content": "Receita anual: 14400"},
                "c2",
            ),
            AIMessage(content="Relatório criado."),
        ]
    )

    result = await service.run("Calcule 1200*12 e gere um relatório")

    assert [c.name for c in result.tool_calls] == ["calculator", "generate_report"]
    files = list(reports_dir.iterdir())
    assert len(files) == 1
    assert "14400" in files[0].read_text(encoding="utf-8")


async def test_tool_error_is_returned_to_model_not_raised(make_service) -> None:
    service, model = make_service(
        [
            tool_call("calculator", {"expression": "1 / 0"}, "c1"),
            AIMessage(content="Não é possível dividir por zero."),
        ]
    )

    result = await service.run("1/0?")

    assert result.tool_calls[0].output == "Erro: Divisão por zero."
    assert result.answer == "Não é possível dividir por zero."


async def test_unknown_tool_is_reported_to_model(make_service) -> None:
    service, model = make_service(
        [
            tool_call("delete_files", {"path": "/"}, "c1"),
            AIMessage(content="Não tenho essa ferramenta."),
        ]
    )

    result = await service.run("apague tudo")

    observation = model.calls[1][-1]
    assert isinstance(observation, ToolMessage)
    assert observation.status == "error"
    assert result.answer == "Não tenho essa ferramenta."


async def test_stops_at_iteration_limit(make_service) -> None:
    # O modelo "insiste" em chamar ferramentas para sempre.
    looping = [tool_call("calculator", {"expression": "1 + 1"}, f"c{i}") for i in range(10)]
    service, model = make_service(looping, max_iterations=3)

    result = await service.run("loop")

    assert result.answer == ITERATION_LIMIT_MESSAGE
    assert result.iterations == 3
    assert len(model.calls) == 3
    assert len(result.tool_calls) == 2  # a 3ª chamada não chega a ser executada


async def test_llm_failure_becomes_agent_error(make_service) -> None:
    service, _ = make_service([])  # o modelo falso lança erro sem respostas

    with pytest.raises(AgentExecutionError, match="Falha ao consultar"):
        await service.run("oi")


async def test_empty_model_answer_is_an_error(make_service) -> None:
    service, _ = make_service([AIMessage(content="")])

    with pytest.raises(AgentExecutionError, match="resposta em texto"):
        await service.run("oi")


async def test_gemini_style_content_blocks_are_supported(make_service) -> None:
    service, _ = make_service([AIMessage(content=[{"type": "text", "text": "Pronto."}])])

    result = await service.run("oi")

    assert result.answer == "Pronto."
