"""Configuração da aplicação carregada de variáveis de ambiente / arquivo .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Valores configuráveis. Nenhum segredo fica no código-fonte."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    # Opcional: os modelos Gemini mais novos usam amostragem fixa e ignoram a temperatura.
    gemini_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    agent_max_iterations: int = Field(default=5, ge=1, le=20)
    # Quantas mensagens do histórico da conversa são enviadas ao modelo.
    max_history_messages: int = Field(default=30, ge=4, le=200)
    default_timezone: str = "America/Sao_Paulo"
    reports_dir: Path = Path("reports")

    max_message_length: int = Field(default=2000, ge=1, le=20_000)

    # Memória persistente
    database_path: Path = Path("data/atlas.db")
    conversation_ttl_hours: float = Field(default=72, gt=0)

    # Segurança
    atlas_api_token: SecretStr | None = None
    rate_limit_per_minute: int = Field(default=20, ge=1)
    max_request_bytes: int = Field(default=64_000, ge=1_024)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def api_token_is_strong(self) -> Settings:
        if self.atlas_api_token is not None:
            token = self.atlas_api_token.get_secret_value()
            if not token:  # ATLAS_API_TOKEN= vazio no .env equivale a "não definido"
                self.atlas_api_token = None
            elif len(token) < 16:
                raise ValueError("ATLAS_API_TOKEN deve ter pelo menos 16 caracteres.")
        return self

    @model_validator(mode="after")
    def history_fits_one_full_turn(self) -> Settings:
        # Um turno pode gerar até 2 mensagens por iteração (pedido de ferramenta +
        # resultado) mais a pergunta e a resposta. O histórico enviado ao modelo
        # precisa caber ao menos um turno completo, senão o corte apagaria a
        # pergunta atual.
        minimum = 2 * self.agent_max_iterations + 2
        if self.max_history_messages < minimum:
            raise ValueError(
                f"MAX_HISTORY_MESSAGES deve ser >= {minimum} (2 x AGENT_MAX_ITERATIONS + 2)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Retorna uma instância única (cacheada) das configurações."""
    return Settings()
