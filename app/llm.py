"""Criação do modelo de linguagem (Gemini)."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import Settings


class MissingAPIKeyError(RuntimeError):
    """A chave da API do Gemini não foi configurada."""


def create_chat_model(settings: Settings) -> BaseChatModel:
    """Cria o chat model do Gemini a partir das configurações.

    A chave vem exclusivamente da variável de ambiente GEMINI_API_KEY (ou .env).
    """
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
        raise MissingAPIKeyError(
            "GEMINI_API_KEY não configurada. Copie .env.example para .env e preencha a chave."
        )
    optional_params = {}
    if settings.gemini_temperature is not None:
        optional_params["temperature"] = settings.gemini_temperature

    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        **optional_params,
    )
