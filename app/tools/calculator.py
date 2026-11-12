"""Calculadora segura baseada em AST.

Por que não usar ``eval``? Porque ``eval`` executa qualquer código Python
(ex.: ``__import__('os').system('rm -rf /')``). Aqui a expressão é convertida
em uma árvore sintática (AST) e apenas um conjunto pequeno e explícito de nós
é aceito: números, operadores aritméticos e algumas funções matemáticas.
Qualquer outra coisa (nomes, atributos, chamadas arbitrárias) é rejeitada.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

from langchain_core.tools import tool

MAX_EXPRESSION_LENGTH = 200
MAX_EXPONENT = 100
MAX_ABS_RESULT = 1e100

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCTIONS: dict[str, Callable[..., float]] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
}

_ALLOWED_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
}


class CalculatorError(ValueError):
    """Erro de validação ou de cálculo da expressão."""


def evaluate_expression(expression: str) -> int | float:
    """Avalia uma expressão aritmética de forma segura.

    Raises:
        CalculatorError: se a expressão for inválida, insegura ou impossível de calcular.
    """
    expression = expression.strip()
    if not expression:
        raise CalculatorError("A expressão está vazia.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError(
            f"A expressão excede o limite de {MAX_EXPRESSION_LENGTH} caracteres."
        )

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError("Expressão com sintaxe inválida.") from exc

    try:
        result = _evaluate_node(tree.body)
    except ZeroDivisionError as exc:
        raise CalculatorError("Divisão por zero.") from exc
    except (OverflowError, ValueError) as exc:
        if isinstance(exc, CalculatorError):
            raise
        raise CalculatorError(f"Não foi possível calcular: {exc}") from exc

    if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
        raise CalculatorError("O resultado não é um número finito.")
    if abs(result) > MAX_ABS_RESULT:
        raise CalculatorError("O resultado é grande demais.")
    return result


def _evaluate_node(node: ast.AST) -> int | float:
    """Percorre a AST recursivamente aceitando apenas nós da lista branca."""
    if isinstance(node, ast.Constant):
        # bool é subclasse de int em Python, por isso é excluído explicitamente.
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise CalculatorError("Apenas números são permitidos.")

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculatorError(f"Expoente maior que {MAX_EXPONENT} não é permitido.")
        return _BINARY_OPERATORS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand))

    if isinstance(node, ast.Name) and node.id in _ALLOWED_CONSTANTS:
        return _ALLOWED_CONSTANTS[node.id]

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _ALLOWED_FUNCTIONS
        and not node.keywords
    ):
        args = [_evaluate_node(arg) for arg in node.args]
        return _ALLOWED_FUNCTIONS[node.func.id](*args)

    raise CalculatorError(f"Elemento não permitido na expressão: {type(node).__name__}.")


@tool
def calculator(expression: str) -> str:
    """Calcula uma expressão matemática.

    Suporta + - * / // % ** e parênteses, as constantes pi e e,
    e as funções sqrt(x), abs(x) e round(x, n). Exemplo: "(2 + 3) * sqrt(16)".
    """
    try:
        return str(evaluate_expression(expression))
    except CalculatorError as exc:
        return f"Erro: {exc}"
