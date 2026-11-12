"""Controles de segurança da API.

- Token de acesso opcional (``ATLAS_API_TOKEN``) para proteger a cota do LLM.
- Limite de requisições por cliente (janela deslizante de 60 s, em memória).
- Limite de tamanho do corpo e cabeçalhos de segurança (middlewares).
"""

from __future__ import annotations

import math
import secrets
import time
from collections import deque
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import Settings, get_settings

# ---------------------------------------------------------------- autenticação

_bearer = HTTPBearer(auto_error=False)


def require_api_token(
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Exige ``Authorization: Bearer <token>`` quando ATLAS_API_TOKEN está definido."""
    expected = settings.atlas_api_token
    if expected is None:
        return  # modo aberto (desenvolvimento local)
    provided = credentials.credentials if credentials else ""
    # compare_digest leva o mesmo tempo para qualquer valor: evita ataques de tempo.
    if not secrets.compare_digest(provided.encode(), expected.get_secret_value().encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso inválido ou ausente.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ------------------------------------------------------- limite de requisições


class RateLimiter:
    """Permite até ``limit`` requisições por cliente a cada ``window`` segundos.

    Guarda os horários das requisições recentes de cada cliente (janela
    deslizante). Fica em memória: vale para um único processo do servidor.
    """

    def __init__(
        self,
        limit: int,
        window: float = 60.0,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window
        self.max_clients = max_clients
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> float | None:
        """Registra uma requisição. Retorna ``None`` se permitida, ou quantos
        segundos o cliente deve esperar."""
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_clients:
                self._forget_idle_clients(now)
            hits = self._hits[key] = deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return hits[0] + self.window - now
        hits.append(now)
        return None

    def _forget_idle_clients(self, now: float) -> None:
        # Impede que muitos clientes diferentes esgotem a memória do servidor.
        idle = [k for k, h in self._hits.items() if not h or h[-1] <= now - self.window]
        for key in idle:
            del self._hits[key]
        if len(self._hits) >= self.max_clients:
            self._hits.clear()


def client_key(request: Request) -> str:
    # Usa o IP da conexão. Cabeçalhos como X-Forwarded-For NÃO são usados de
    # propósito: muitas plataformas (ex.: Render) repassam o valor enviado pelo
    # próprio cliente, que poderia forjar um IP novo a cada requisição para
    # escapar do limite. Atrás de um proxy, todos os clientes compartilham o
    # mesmo IP; o limite global abaixo continua protegendo a cota do LLM.
    return request.client.host if request.client else "desconhecido"


def enforce_rate_limit(request: Request) -> None:
    state = request.app.state
    # Primeiro o limite do cliente: quem abusa é barrado sem gastar a cota global.
    retry_after = state.rate_limiter.check(client_key(request))
    if retry_after is None:
        retry_after = state.global_rate_limiter.check("global")
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas requisições. Aguarde um pouco e tente novamente.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )


# ----------------------------------------------------------------- middlewares

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}

# Aplicada só à interface web: os arquivos JS/CSS são servidos pela própria
# API, então nenhum script inline ou de outro domínio é permitido.
WEB_UI_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Recusa (413) corpos maiores que ``max_bytes`` antes de lê-los."""

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if request.method in {"POST", "PUT", "PATCH"}:
            if content_length is None:
                return JSONResponse(
                    status_code=status.HTTP_411_LENGTH_REQUIRED,
                    content={"detail": "Cabeçalho Content-Length obrigatório."},
                )
            if not content_length.isdigit() or int(content_length) > self.max_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": f"Corpo da requisição maior que {self.max_bytes} bytes."},
                )
        return await call_next(request)
