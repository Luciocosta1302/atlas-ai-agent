"""Ponto de entrada da API.

Execução local:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app import __version__
from app.agent import AgentExecutionError
from app.api.routes import router
from app.config import get_settings
from app.llm import MissingAPIKeyError

logger = logging.getLogger("atlas")


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
    )
    app.include_router(router)

    # Os handlers convertem exceções de domínio em respostas HTTP sem expor
    # detalhes internos (stack traces, mensagens do provedor, etc.).
    @app.exception_handler(MissingAPIKeyError)
    async def missing_key_handler(_: Request, exc: MissingAPIKeyError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
        )

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
