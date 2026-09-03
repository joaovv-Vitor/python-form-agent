from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from ..adapters.playwright_browser import BrowserController
from ..core.schemas import JsonObject

JsonRpcMessage = dict[str, Any]
ToolHandler = Callable[[JsonObject], Awaitable[JsonObject]]

controller = BrowserController()


async def inspect_form(_: JsonObject) -> JsonObject:
    """Inspeciona semanticamente os controles do formulário."""
    return (await controller.inspect_form()).to_dict()


async def fill_field(arguments: JsonObject) -> JsonObject:
    """Preenche um campo por label, name, id ou placeholder."""
    return await controller.fill_field(str(arguments["field"]), str(arguments["value"]))


async def read_field(arguments: JsonObject) -> JsonObject:
    """Lê o valor atual de um campo."""
    return await controller.read_field(str(arguments["field"]))


async def click_button(arguments: JsonObject) -> JsonObject:
    """Clica em um botão identificado semanticamente."""
    return await controller.click_button(str(arguments["button"]))


TOOLS: dict[str, tuple[str, JsonObject, ToolHandler]] = {
    "inspect_form": (
        "Inspeciona semanticamente os controles do formulário.",
        {"type": "object", "properties": {}},
        inspect_form,
    ),
    "fill_field": (
        "Preenche um campo por label, name, id ou placeholder.",
        {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["field", "value"],
        },
        fill_field,
    ),
    "read_field": (
        "Lê o valor atual de um campo.",
        {
            "type": "object",
            "properties": {"field": {"type": "string"}},
            "required": ["field"],
        },
        read_field,
    ),
    "click_button": (
        "Clica em um botão identificado semanticamente.",
        {
            "type": "object",
            "properties": {"button": {"type": "string"}},
            "required": ["button"],
        },
        click_button,
    ),
}


def _result(request_id: object, value: JsonObject) -> JsonRpcMessage:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(request_id: object, code: int, message: str) -> JsonRpcMessage:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


async def _handle(message: JsonRpcMessage) -> JsonRpcMessage | None:
    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str):
        return _error(request_id, -32600, "Requisição JSON-RPC inválida.")
    if "id" not in message:
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "form-browser-mcp-python", "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return _result(
            request_id,
            {
                "tools": [
                    {"name": name, "description": description, "inputSchema": schema}
                    for name, (description, schema, _) in TOOLS.items()
                ]
            },
        )
    if method != "tools/call":
        return _error(request_id, -32601, f"Método MCP desconhecido: {method}")
    params = message.get("params")
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        return _error(request_id, -32602, "Parâmetros inválidos para tools/call.")
    tool = TOOLS.get(params["name"])
    if tool is None:
        return _error(request_id, -32602, "Tool MCP desconhecida.")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "Os argumentos da tool devem ser um objeto.")
    try:
        output = await tool[2](arguments)
    except (KeyError, TypeError, ValueError) as exc:
        return _result(
            request_id,
            {"content": [{"type": "text", "text": str(exc)}], "isError": True},
        )
    except Exception:
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": "Falha ao executar a tool."}],
                "isError": True,
            },
        )
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}],
            "structuredContent": output,
            "isError": False,
        },
    )


async def serve_stdio() -> None:
    """Atende MCP por stdio sem o transporte AnyIO incompatível com Python 3.14."""
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    try:
        while line := await reader.readline():
            response: JsonRpcMessage | None
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                response = _error(None, -32700, "JSON inválido.")
            else:
                response = (
                    await _handle(message)
                    if isinstance(message, dict)
                    else _error(None, -32600, "Requisição JSON-RPC inválida.")
                )
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        await controller.close()


if __name__ == "__main__":
    asyncio.run(serve_stdio())
