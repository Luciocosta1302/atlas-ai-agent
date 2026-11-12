"""Ferramentas disponíveis para o agente."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool

from app.tools.calculator import calculator
from app.tools.datetime_tool import create_datetime_tool
from app.tools.report import create_report_tool


def build_tools(default_timezone: str, reports_dir: Path) -> list[BaseTool]:
    """Monta a lista de ferramentas que o modelo pode chamar."""
    return [
        calculator,
        create_datetime_tool(default_timezone),
        create_report_tool(reports_dir),
    ]


__all__ = ["build_tools"]
