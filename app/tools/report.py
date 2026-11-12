"""Ferramenta de geração de relatórios TXT em um diretório isolado.

Regras de segurança:
- O modelo NUNCA escolhe o caminho do arquivo: o nome é gerado pelo servidor
  a partir do título (slug) + timestamp + sufixo aleatório.
- O arquivo é sempre criado dentro de ``reports_dir``; o caminho final é
  verificado após ``resolve()`` para impedir path traversal.
- Título e conteúdo têm tamanho máximo.
- O arquivo é criado em modo exclusivo ("x"): nunca sobrescreve outro relatório.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool

MAX_TITLE_LENGTH = 100
MAX_CONTENT_LENGTH = 10_000


class ReportError(ValueError):
    """Erro de validação ou de escrita do relatório."""


def slugify(text: str, max_length: int = 50) -> str:
    """Converte "Relatório de Vendas!" em "relatorio-de-vendas"."""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:max_length].strip("-") or "relatorio"


def write_report(title: str, content: str, reports_dir: Path) -> Path:
    """Grava o relatório e retorna o caminho do arquivo criado."""
    title = title.strip()
    content = content.strip()
    if not title:
        raise ReportError("O título não pode ser vazio.")
    if not content:
        raise ReportError("O conteúdo não pode ser vazio.")
    if len(title) > MAX_TITLE_LENGTH:
        raise ReportError(f"O título excede {MAX_TITLE_LENGTH} caracteres.")
    if len(content) > MAX_CONTENT_LENGTH:
        raise ReportError(f"O conteúdo excede {MAX_CONTENT_LENGTH} caracteres.")

    base_dir = reports_dir.resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    filename = f"{now:%Y%m%d-%H%M%S}-{slugify(title)}-{secrets.token_hex(3)}.txt"
    path = (base_dir / filename).resolve()
    if not path.is_relative_to(base_dir):  # defesa em profundidade
        raise ReportError("Caminho de relatório inválido.")

    body = (
        f"{title}\n"
        f"{'=' * len(title)}\n"
        f"Gerado em: {now.isoformat(timespec='seconds')}\n\n"
        f"{content}\n"
    )
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(body)
    except OSError as exc:
        raise ReportError("Não foi possível gravar o relatório.") from exc
    return path


def create_report_tool(reports_dir: Path) -> BaseTool:
    """Cria a ferramenta presa ao diretório de relatórios configurado."""

    def generate_report(title: str, content: str) -> str:
        try:
            path = write_report(title, content, reports_dir)
        except ReportError as exc:
            return f"Erro: {exc}"
        return f"Relatório salvo como '{path.name}'."

    return StructuredTool.from_function(
        func=generate_report,
        name="generate_report",
        description=(
            "Gera um relatório em arquivo .txt com um título e um conteúdo em texto. "
            f"Título com até {MAX_TITLE_LENGTH} caracteres e conteúdo com até "
            f"{MAX_CONTENT_LENGTH} caracteres. Retorna o nome do arquivo criado."
        ),
    )
