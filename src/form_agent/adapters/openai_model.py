"""OpenAI-compatible language-model adapter."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
)

from ..config import ModelConfig
from ..core.errors import (
    ModelAuthenticationError,
    ModelCommunicationError,
    ModelResponseError,
    ModelTimeoutError,
)
from ..core.interfaces import ModelSession
from ..core.schemas import FormInspection, ToolCall, ToolCompletion, ToolDefinition

SYSTEM_PROMPT = """Você é um agente de preenchimento de formulários web.
Use somente as tools fornecidas. Baseie-se no inventário do formulário. Não invente correspondências.
Confirme cada fill_field com read_field. Só clique em Enviar se a instrução atual pedir explicitamente.
Datas para input date devem usar YYYY-MM-DD; select usa texto visível; checkbox usa true ou false."""


class OpenAIModelSession:
    """Conversation state for one agent instruction."""

    def __init__(
        self,
        client: AsyncOpenAI,
        config: ModelConfig,
        instruction: str,
        inspection: FormInspection,
        tools: Sequence[ToolDefinition],
    ) -> None:
        self._client = client
        self._config = config
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Instrução atual: {instruction}\n\n"
                    f"Resultado de inspect_form:\n{json.dumps(inspection.to_dict(), ensure_ascii=False)}"
                ),
            },
        ]
        self._tools = [tool.to_api_dict() for tool in tools]

    async def next(self, completed: Sequence[ToolCompletion]) -> list[ToolCall]:
        for item in completed:
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.call_id,
                    "content": json.dumps(item.output, ensure_ascii=False),
                }
            )
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                messages=cast(Any, self._messages),
                tools=cast(Any, self._tools),
                tool_choice="auto",
            )
        except AuthenticationError as exc:
            raise ModelAuthenticationError(
                "A chave da API foi recusada. Verifique as credenciais no arquivo .env."
            ) from exc
        except APITimeoutError as exc:
            raise ModelTimeoutError("O provedor do modelo demorou demais para responder.") from exc
        except APIConnectionError as exc:
            raise ModelCommunicationError(
                "Não foi possível conectar ao provedor do modelo."
            ) from exc
        except APIStatusError as exc:
            raise ModelCommunicationError(
                f"O provedor do modelo recusou a requisição (HTTP {exc.status_code})."
            ) from exc
        except OpenAIError as exc:
            raise ModelCommunicationError("Falha inesperada na comunicação com o modelo.") from exc

        if not response.choices:
            raise ModelResponseError("O modelo retornou uma resposta sem alternativas.")
        message = response.choices[0].message
        self._messages.append(message.model_dump(exclude_none=True))

        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            if call.type != "function":
                raise ModelResponseError(
                    f"O modelo solicitou um tipo de tool não suportado: {call.type}."
                )
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise ModelResponseError(
                    f"O modelo retornou argumentos JSON inválidos para a tool {call.function.name}."
                ) from exc
            if not isinstance(arguments, dict):
                raise ModelResponseError(
                    f"Os argumentos da tool {call.function.name} devem ser um objeto JSON."
                )
            calls.append(
                ToolCall(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )
        return calls


class OpenAICompatibleModel:
    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    def create_session(
        self,
        instruction: str,
        inspection: FormInspection,
        tools: Sequence[ToolDefinition],
    ) -> ModelSession:
        return OpenAIModelSession(self.client, self.config, instruction, inspection, tools)

    async def close(self) -> None:
        await self.client.close()
