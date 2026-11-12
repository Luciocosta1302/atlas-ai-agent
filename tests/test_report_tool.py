from pathlib import Path

import pytest

from app.tools.report import (
    MAX_CONTENT_LENGTH,
    ReportError,
    create_report_tool,
    slugify,
    write_report,
)


def test_write_report_creates_txt_inside_reports_dir(reports_dir: Path) -> None:
    path = write_report("Vendas de Março", "Total: R$ 1.000", reports_dir)

    assert path.parent == reports_dir.resolve()
    assert path.suffix == ".txt"
    assert "vendas-de-marco" in path.name
    content = path.read_text(encoding="utf-8")
    assert content.startswith("Vendas de Março\n===============\n")
    assert "Total: R$ 1.000" in content


@pytest.mark.parametrize("title", ["../../etc/passwd", "/tmp/evil", "..\\..\\windows"])
def test_title_cannot_escape_reports_dir(reports_dir: Path, title: str) -> None:
    path = write_report(title, "conteúdo", reports_dir)
    assert path.parent == reports_dir.resolve()
    assert list(reports_dir.iterdir()) == [path]


def test_reports_never_overwrite_each_other(reports_dir: Path) -> None:
    first = write_report("Mesmo título", "a", reports_dir)
    second = write_report("Mesmo título", "b", reports_dir)
    assert first != second
    assert len(list(reports_dir.iterdir())) == 2


@pytest.mark.parametrize(
    ("title", "content", "message"),
    [
        ("   ", "x", "título"),
        ("Título", "  ", "conteúdo"),
        ("T" * 101, "x", "título excede"),
        ("Título", "x" * (MAX_CONTENT_LENGTH + 1), "conteúdo excede"),
    ],
)
def test_validation_errors(reports_dir: Path, title: str, content: str, message: str) -> None:
    with pytest.raises(ReportError, match=message):
        write_report(title, content, reports_dir)
    assert not reports_dir.exists() or not any(reports_dir.iterdir())


def test_slugify() -> None:
    assert slugify("Relatório de Vendas!") == "relatorio-de-vendas"
    assert slugify("!!!") == "relatorio"


def test_tool_returns_only_file_name(reports_dir: Path) -> None:
    tool = create_report_tool(reports_dir)
    result = tool.invoke({"title": "Resumo", "content": "Tudo certo."})
    assert result.startswith("Relatório salvo como '")
    assert str(reports_dir) not in result  # não expõe o caminho absoluto
    assert tool.invoke({"title": "", "content": "x"}).startswith("Erro:")
