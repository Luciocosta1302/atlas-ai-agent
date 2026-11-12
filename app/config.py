"""Configuração da aplicação carregada de variáveis de ambiente / arquivo .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
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
    default_timezone: str = "America/Sao_Paulo"
    reports_dir: Path = Path("reports")

    max_message_length: int = Field(default=2000, ge=1, le=20_000)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Retorna uma instância única (cacheada) das configurações."""
    return Settings()
