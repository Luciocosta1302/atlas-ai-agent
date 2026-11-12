"""Contratos (schemas) de entrada e saída da API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Limite rígido do schema; o limite configurável (MAX_MESSAGE_LENGTH) é
# verificado na rota, pois o schema é definido em tempo de importação.
HARD_MAX_MESSAGE_LENGTH = 20_000


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        ...,
        min_length=1,
        max_length=HARD_MAX_MESSAGE_LENGTH,
        description="Tarefa em linguagem natural.",
        examples=["Quanto é (15 * 4) + 7?"],
    )

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A mensagem não pode ser vazia.")
        return value


class ToolCallOut(BaseModel):
    name: str
    args: dict[str, Any]
    output: str


class ChatResponse(BaseModel):
    answer: str
    iterations: int = Field(description="Quantas vezes o modelo foi chamado.")
    tool_calls: list[ToolCallOut] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    detail: str
