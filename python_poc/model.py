from __future__ import annotations

import json
from typing import Any, Protocol

from openai import AsyncOpenAI

from .config import ModelConfig

SYSTEM_PROMPT = """Você é um agente de preenchimento de formulários web.
Use somente as tools fornecidas. Baseie-se no inventário do formulário. Não invente correspondências.
Confirme cada fill_field com read_field. Só clique em Enviar se a instrução atual pedir explicitamente.
Datas para input date devem usar YYYY-MM-DD; select usa texto visível; checkbox usa true ou false."""


class ModelSession(Protocol):
    async def next(self, completed: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class OpenAICompatibleModel:
    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

    def create_session(self, instruction: str, inspection: dict[str, Any], tools: list[dict[str, Any]]) -> ModelSession:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Instrução atual: {instruction}\n\nResultado de inspect_form:\n{json.dumps(inspection, ensure_ascii=False)}"},
        ]
        api_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}} for t in tools]
        client, config = self.client, self.config

        class Session:
            async def next(self, completed: list[dict[str, Any]]) -> list[dict[str, Any]]:
                for item in completed:
                    messages.append({"role": "tool", "tool_call_id": item["call_id"], "content": json.dumps(item["output"], ensure_ascii=False)})
                response = await client.chat.completions.create(model=config.model, messages=messages, tools=api_tools, tool_choice="auto")
                message = response.choices[0].message
                messages.append(message.model_dump(exclude_none=True))
                return [{"call_id": call.id, "name": call.function.name, "arguments": json.loads(call.function.arguments or "{}")} for call in message.tool_calls or []]

        return Session()
