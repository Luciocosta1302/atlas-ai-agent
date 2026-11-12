"""Modelo de chat falso para testes: devolve respostas roteirizadas, sem rede."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class ScriptedChatModel(BaseChatModel):
    """Retorna, em ordem, as mensagens de ``responses`` a cada chamada.

    Também guarda as mensagens recebidas em ``calls`` e as ferramentas
    vinculadas em ``bound_tools`` para que os testes possam inspecioná-las.
    """

    responses: list[AIMessage]
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        self.bound_tools = list(tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        if not self.responses:
            raise RuntimeError("ScriptedChatModel: sem respostas restantes.")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    """Atalho para criar uma AIMessage que pede a execução de uma ferramenta."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
