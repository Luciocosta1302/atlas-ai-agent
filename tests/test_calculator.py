import math

import pytest

from app.tools.calculator import CalculatorError, calculator, evaluate_expression


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3", 5),
        ("(15 * 4) + 7", 67),
        ("10 / 4", 2.5),
        ("10 // 4", 2),
        ("10 % 4", 2),
        ("2 ** 10", 1024),
        ("-3 + +5", 2),
        ("sqrt(16) * 2", 8.0),
        ("abs(-7)", 7),
        ("round(3.14159, 2)", 3.14),
        ("pi", math.pi),
    ],
)
def test_valid_expressions(expression: str, expected: float) -> None:
    assert evaluate_expression(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('ls')",
        "open('/etc/passwd').read()",
        "(1).__class__",
        "[x for x in range(10)]",
        "lambda: 1",
        "x + 1",
        "'a' * 3",
        "True + 1",
        "sqrt(x=4)",
    ],
)
def test_rejects_unsafe_or_unsupported_code(expression: str) -> None:
    with pytest.raises(CalculatorError):
        evaluate_expression(expression)


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("1 / 0", "Divisão por zero"),
        ("", "vazia"),
        ("2 +", "sintaxe"),
        ("9 ** 9999", "Expoente"),
        ("1" * 201, "limite"),
        ("sqrt(-1)", "Não foi possível calcular"),
        ("10.0 ** 100 * 10.0 ** 100", "grande demais"),
    ],
)
def test_errors_have_clear_messages(expression: str, message: str) -> None:
    with pytest.raises(CalculatorError, match=message):
        evaluate_expression(expression)


def test_tool_returns_error_text_instead_of_raising() -> None:
    assert calculator.invoke({"expression": "1 / 0"}) == "Erro: Divisão por zero."
    assert calculator.invoke({"expression": "6 * 7"}) == "42"
