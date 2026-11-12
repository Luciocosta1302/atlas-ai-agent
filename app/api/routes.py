"""Rotas HTTP."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.agent import AgentService
from app.api.dependencies import get_agent_service
from app.api.schemas import ChatRequest, ChatResponse, ErrorResponse, ToolCallOut
from app.config import Settings, get_settings

router = APIRouter()


@router.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/chat",
    response_model=ChatResponse,
    tags=["agent"],
    responses={
        422: {"description": "Entrada inválida"},
        502: {"model": ErrorResponse, "description": "Falha no provedor de LLM"},
        503: {"model": ErrorResponse, "description": "Agente não configurado"},
    },
)
async def chat(
    request: ChatRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    agent: Annotated[AgentService, Depends(get_agent_service)],
) -> ChatResponse:
    if len(request.message) > settings.max_message_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A mensagem excede {settings.max_message_length} caracteres.",
        )

    result = await agent.run(request.message)
    return ChatResponse(
        answer=result.answer,
        iterations=result.iterations,
        tool_calls=[
            ToolCallOut(name=c.name, args=c.args, output=c.output) for c in result.tool_calls
        ],
    )
