"""Bounded request/reply bridge to a user-selected Chrome document.

The browser polls a single outstanding command. Re-delivery uses the same ID;
the extension caches its reply so a lost acknowledgement never repeats a write.
No server-side navigation or submission exists in this transport.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from collections.abc import Mapping
from typing import Any

from form_agent.core.errors import ToolClientError
from form_agent.core.schemas import FormInspection, JsonObject, ToolDefinition


def extension_owner(headers: Mapping[str, str], token: str) -> str:
    client = headers.get("x-vozform-client", "")
    authorization = headers.get("authorization", "")
    supplied = authorization.removeprefix("Bearer ")
    if (
        not authorization.startswith("Bearer ")
        or not re.fullmatch(r"[a-p]{32}", client)
        or not secrets.compare_digest(supplied, token)
    ):
        raise ValueError("Conecte a extensão com o código exibido pelo servidor.")
    origin = headers.get("origin", "")
    if origin and origin != f"chrome-extension://{client}":
        raise ValueError("Origem da extensão não permitida.")
    return f"extension:{client}"


class ExtensionToolsClient:
    def __init__(self, url: str, document_id: str, *, timeout: float = 30) -> None:
        self.url, self.document_id, self.timeout = url, document_id, timeout
        self.pending: dict[str, Any] | None = None
        self._reply: asyncio.Future[JsonObject] | None = None
        self._lock = asyncio.Lock()
        self.closed = False

    async def list_tools(self) -> list[ToolDefinition]:
        field: JsonObject = {"type": "string"}
        return [
            ToolDefinition(
                "inspect_form",
                "Lê os campos da aba selecionada.",
                {"type": "object", "properties": {}},
            ),
            ToolDefinition(
                "fill_field",
                "Preenche um campo da aba selecionada, sem enviar o formulário.",
                {
                    "type": "object",
                    "properties": {"field": field, "value": field},
                    "required": ["field", "value"],
                },
            ),
            ToolDefinition(
                "read_field",
                "Relê o valor de um campo da aba selecionada.",
                {
                    "type": "object",
                    "properties": {"field": field},
                    "required": ["field"],
                },
            ),
        ]

    async def inspect_form(self) -> FormInspection:
        result = await self.call_tool("inspect_form")
        if result.get("success") is False:
            raise ToolClientError(str(result.get("error") or "Não foi possível ler a aba."))
        inspection = FormInspection.from_mapping(result)
        if inspection.url != self.url:
            raise ToolClientError("A página mudou. Encerre a sessão e selecione a aba novamente.")
        return inspection

    async def call_tool(self, name: str, arguments: JsonObject | None = None) -> JsonObject:
        if name not in {"inspect_form", "fill_field", "read_field"}:
            return {
                "success": False,
                "code": "SUBMISSION_BLOCKED",
                "error": "O envio deve ser feito pelo usuário no site.",
            }
        arguments = arguments or {}
        expected = (
            {"field", "value"}
            if name == "fill_field"
            else {"field"}
            if name == "read_field"
            else set()
        )
        if set(arguments) != expected or any(
            not isinstance(value, str) for value in arguments.values()
        ):
            return {
                "success": False,
                "code": "TOOL_ERROR",
                "error": "Argumentos de campo inválidos.",
            }
        async with self._lock:
            if self.closed:
                raise ToolClientError("A conexão com a extensão foi encerrada.")
            reply = asyncio.get_running_loop().create_future()
            self._reply = reply
            self.pending = {
                "id": secrets.token_hex(16),
                "name": name,
                "arguments": arguments,
                "document_id": self.document_id,
                "url": self.url,
            }
            try:
                return await asyncio.wait_for(reply, self.timeout)
            except TimeoutError as exc:
                self.abort()
                raise ToolClientError(
                    "A extensão não respondeu. Abra o painel e inicie outra sessão.", "TIMEOUT"
                ) from exc
            finally:
                self.pending = None
                self._reply = None

    def resolve(self, command_id: str, result: JsonObject) -> bool:
        if (
            not self.pending
            or command_id != self.pending["id"]
            or not self._reply
            or self._reply.done()
        ):
            return False
        self._reply.set_result(result)
        return True

    def abort(self) -> None:
        self.closed = True
        self.pending = None
        if self._reply and not self._reply.done():
            self._reply.set_exception(ToolClientError("A conexão com a extensão foi encerrada."))

    async def close(self) -> None:
        self.abort()

    async def set_submission_authorized(self, authorized: bool) -> None:
        if authorized:
            raise ToolClientError("O envio deve ser feito pelo usuário no site.")
