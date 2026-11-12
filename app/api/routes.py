"""Rotas HTTP."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from pathlib import Path as FilePath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.agent import AgentExecutionError, AgentService
from app.api.dependencies import get_agent_service
from app.api.schemas import (
    THREAD_ID_PATTERN,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    ToolCallOut,
)
from app.config import Settings, get_settings
from app.security import WEB_UI_CSP, enforce_rate_limit, require_api_token

logger = logging.getLogger(__name__)

STATIC_DIR = FilePath(__file__).resolve().parent.parent / "static"

# Rotas públicas: interface web e verificação de saúde.
public_router = APIRouter()
# Rotas que consomem o LLM ou mexem em conversas: limite de requisições + token.
protected_router = APIRouter(
    dependencies=[Depends(enforce_rate_limit), Depends(require_api_token)],
    responses={
        401: {"model": ErrorResponse, "description": "Token ausente ou inválido"},
        429: {"model": ErrorResponse, "description": "Limite de requisições atingido"},
    },
)


def validated_chat_request(
    request: ChatRequest, settings: Annotated[Settings, Depends(get_settings)]
) -> ChatRequest:
    """Aplica o limite de tamanho configurável (MAX_MESSAGE_LENGTH).

    Fica numa dependência para rodar antes do streaming começar: depois que a
    resposta SSE é iniciada, não dá mais para devolver um status 422.
    """
    if len(request.message) > settings.max_message_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A mensagem excede {settings.max_message_length} caracteres.",
        )
    return request


ValidChatRequest = Annotated[ChatRequest, Depends(validated_chat_request)]
Agent = Annotated[AgentService, Depends(get_agent_service)]


@public_router.get("/", include_in_schema=False)
async def web_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Content-Security-Policy": WEB_UI_CSP})


@public_router.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@protected_router.post(
    "/chat",
    response_model=ChatResponse,
    tags=["agent"],
    responses={
        404: {"model": ErrorResponse, "description": "Conversa não encontrada ou expirada"},
        422: {"description": "Entrada inválida"},
        502: {"model": ErrorResponse, "description": "Falha no provedor de LLM"},
        503: {"model": ErrorResponse, "description": "Agente não configurado"},
    },
)
async def chat(request: ValidChatRequest, agent: Agent) -> ChatResponse:
    result = await agent.run(request.message, request.thread_id)
    return ChatResponse(
        answer=result.answer,
        thread_id=result.thread_id,
        iterations=result.iterations,
        tool_calls=[
            ToolCallOut(name=c.name, args=c.args, output=c.output) for c in result.tool_calls
        ],
    )


async def resolved_thread_id(request: ValidChatRequest, agent: Agent) -> str:
    """Cria ou valida a conversa antes do streaming (para ainda poder responder 404)."""
    return await agent.resolve_thread(request.thread_id)


@protected_router.post(
    "/chat/stream",
    response_class=EventSourceResponse,
    tags=["agent"],
    responses={
        404: {"model": ErrorResponse, "description": "Conversa não encontrada ou expirada"},
        422: {"description": "Entrada inválida"},
        503: {"model": ErrorResponse, "description": "Agente não configurado"},
    },
)
async def chat_stream(
    request: ValidChatRequest,
    agent: Agent,
    thread_id: Annotated[str, Depends(resolved_thread_id)],
) -> AsyncIterable[ServerSentEvent]:
    """Mesma tarefa do POST /chat, mas com Server-Sent Events.

    Eventos: ``token``, ``tool_call``, ``tool_result``, ``done`` e ``error``.
    Como o status HTTP (200) já foi enviado quando o streaming começa, falhas
    durante a execução chegam como um evento ``error``.
    """
    try:
        async for event in agent.stream(request.message, thread_id):
            yield ServerSentEvent(event=event.type, data=event.data)
    except AgentExecutionError as exc:
        yield ServerSentEvent(event="error", data={"detail": str(exc)})
    except Exception:
        logger.exception("Erro inesperado durante o streaming")
        yield ServerSentEvent(event="error", data={"detail": "Erro interno do servidor."})


@protected_router.delete(
    "/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["agent"]
)
async def delete_thread(
    thread_id: Annotated[str, Path(pattern=THREAD_ID_PATTERN)], agent: Agent
) -> Response:
    """Apaga o histórico de uma conversa (idempotente)."""
    await agent.delete_thread(thread_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
