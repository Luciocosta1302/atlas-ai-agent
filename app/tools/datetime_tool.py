"""Ferramenta de consulta de data e hora atuais."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import BaseTool, StructuredTool

WEEKDAYS_PT = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


def describe_now(timezone: str, now: datetime | None = None) -> str:
    """Retorna a data/hora atual em um fuso horário IANA (ex.: "America/Sao_Paulo").

    ``now`` permite injetar um instante fixo nos testes (precisa ter tzinfo).

    Raises:
        ValueError: se o fuso horário não existir.
    """
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Fuso horário desconhecido: '{timezone}'.") from exc

    current = (now or datetime.now(tz)).astimezone(tz)
    weekday = WEEKDAYS_PT[current.weekday()]
    return (
        f"Data: {current.strftime('%d/%m/%Y')} ({weekday}); "
        f"hora: {current.strftime('%H:%M:%S')}; "
        f"fuso: {timezone} (UTC{current.strftime('%z')}); "
        f"ISO 8601: {current.isoformat(timespec='seconds')}"
    )


def create_datetime_tool(
    default_timezone: str, clock: Callable[[], datetime] | None = None
) -> BaseTool:
    """Cria a ferramenta com o fuso padrão configurado na aplicação."""

    def get_current_datetime(timezone: str = default_timezone) -> str:
        try:
            return describe_now(timezone, now=clock() if clock else None)
        except ValueError as exc:
            return f"Erro: {exc}"

    return StructuredTool.from_function(
        func=get_current_datetime,
        name="get_current_datetime",
        description=(
            "Retorna a data, a hora e o dia da semana atuais. "
            "Use para qualquer pergunta sobre 'hoje', 'agora' ou datas relativas. "
            f"O parâmetro opcional 'timezone' é um fuso IANA (padrão: {default_timezone})."
        ),
    )
