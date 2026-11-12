from datetime import UTC, datetime

import pytest

from app.tools.datetime_tool import create_datetime_tool, describe_now

FIXED_UTC = datetime(2026, 11, 12, 15, 30, 0, tzinfo=UTC)


def test_describe_now_converts_to_requested_timezone() -> None:
    text = describe_now("America/Sao_Paulo", now=FIXED_UTC)
    assert "12/11/2026" in text
    assert "quinta-feira" in text
    assert "12:30:00" in text
    assert "UTC-0300" in text


def test_describe_now_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="desconhecido"):
        describe_now("Mars/Olympus_Mons", now=FIXED_UTC)


def test_tool_uses_default_timezone_and_handles_errors() -> None:
    tool = create_datetime_tool("Asia/Tokyo", clock=lambda: FIXED_UTC)
    assert "00:30:00" in tool.invoke({})
    assert "13/11/2026" in tool.invoke({})
    assert tool.invoke({"timezone": "../../etc"}).startswith("Erro:")
