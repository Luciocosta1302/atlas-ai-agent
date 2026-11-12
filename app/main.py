"""Ponto de entrada da API.

Execução local:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.agent import AgentExecutionError, ThreadNotFoundError
from app.api.routes import STATIC_DIR, protected_router, public_router
from app.config import Settings, get_settings
from app.llm import MissingAPIKeyError
from app.memory import ConversationStore, open_sqlite_store
from app.security import MaxBodySizeMiddleware, RateLimiter, SecurityHeadersMiddleware

logger = logging.getLogger("atlas")

PURGE_INTERVAL_SECONDS = 3600


async def purge_expired_periodically(store: ConversationStore, settings: Settings) -> None:
    """Apaga conversas inativas na inicialização e depois a cada hora."""
    ttl_seconds = settings.conversation_ttl_hours * 3600
    while True:
        try:
            await store.purge_expired(ttl_seconds)
        except Exception:
            logger.exception("Falha ao apagar conversas expiradas")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.atlas_api_token is None:
        logger.warning(
            "ATLAS_API_TOKEN não definido: a API está aberta. "
            "Defina um token antes de expor o servidor na internet."
        )
    app.state.rate_limiter = RateLimiter(limit=settings.rate_limit_per_minute)
    app.state.global_rate_limiter = RateLimiter(limit=settings.global_rate_limit_per_minute)
    async with open_sqlite_store(settings.database_path) as store:
        app.state.store = store
        purge_task = asyncio.create_task(purge_expired_periodically(store, settings))
        try:
            yield
        finally:
            purge_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await purge_task
            app.state.agent_service = None


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = FastAPI(
        title="Atlas AI",
        version=__version__,
        description="Agente que recebe tarefas em linguagem natural e usa ferramentas.",
        lifespan=lifespan,
    )
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(public_router)
    app.include_router(protected_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Os handlers convertem exceções de domínio em respostas HTTP sem expor
    # detalhes internos (stack traces, mensagens do provedor, etc.).
    @app.exception_handler(MissingAPIKeyError)
    async def missing_key_handler(_: Request, exc: MissingAPIKeyError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
        )

    @app.exception_handler(ThreadNotFoundError)
    async def thread_not_found_handler(_: Request, exc: ThreadNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})

    @app.exception_handler(AgentExecutionError)
    async def agent_error_handler(_: Request, exc: AgentExecutionError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Erro inesperado", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Erro interno do servidor."},
        )

    return app


app = create_app()
