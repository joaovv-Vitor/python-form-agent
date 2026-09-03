from __future__ import annotations

import asyncio
import json
import os
import sys
from types import TracebackType
from typing import Any

from ..config import PROJECT_ROOT
from ..core.errors import ToolClientError
from ..core.schemas import FormInspection, JsonObject, ToolDefinition


class BrowserToolsClient:
    """Cliente MCP local via JSON-RPC sobre stdio.

    O transporte ``mcp.client.stdio`` do SDK usa cancel scopes do AnyIO que,
    no Python 3.14, podem encerrar em uma task diferente da que os abriu.
    Como o protocolo MCP em stdio e JSON-RPC delimitado por linhas, este
    cliente mantem o mesmo contrato sem depender dessa camada de transporte.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds deve ser maior que zero")
        self._timeout_seconds = timeout_seconds
        self._process: asyncio.subprocess.Process | None = None
        self._connect_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._next_request_id = 1

    async def connect(self) -> None:
        if self._is_connected():
            return
        async with self._connect_lock:
            if self._is_connected():
                return
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    self._process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "form_agent.mcp.server",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=PROJECT_ROOT,
                        env=dict(os.environ),
                    )
                    await self._request(
                        "initialize",
                        {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {"name": "form-agent", "version": "0.1.0"},
                        },
                    )
                    await self._notify("notifications/initialized")
            except Exception as exc:
                await self.close()
                raise ToolClientError(
                    "Não foi possível iniciar o servidor MCP do navegador."
                ) from exc

    async def list_tools(self) -> list[ToolDefinition]:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._request_after_connect("tools/list")
        except ToolClientError:
            raise
        except Exception as exc:
            raise ToolClientError("Não foi possível listar as tools do navegador.") from exc
        tools = response.get("tools")
        if not isinstance(tools, list):
            raise ToolClientError("O servidor MCP retornou uma lista de tools inválida.")
        definitions: list[ToolDefinition] = []
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                continue
            schema = tool.get("inputSchema")
            definitions.append(
                ToolDefinition(
                    name=str(tool["name"]),
                    description=str(tool.get("description") or ""),
                    input_schema=schema if isinstance(schema, dict) else {},
                )
            )
        return definitions

    async def inspect_form(self) -> FormInspection:
        return FormInspection.from_mapping(await self.call_tool("inspect_form"))

    async def call_tool(self, name: str, arguments: JsonObject | None = None) -> JsonObject:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._request_after_connect(
                    "tools/call", {"name": name, "arguments": arguments or {}}
                )
        except ToolClientError:
            raise
        except Exception as exc:
            raise ToolClientError(f"Falha ao executar a tool {name}.") from exc
        if result.get("isError"):
            details = " ".join(self._text_content(result))
            raise ToolClientError(f"A tool {name} falhou: {details or 'erro não informado'}")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        for text in self._text_content(result):
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ToolClientError(f"A tool {name} retornou JSON inválido.") from exc
            if isinstance(value, dict):
                return value
        raise ToolClientError(f"A tool {name} retornou uma resposta vazia.")

    @staticmethod
    def _text_content(result: JsonObject) -> list[str]:
        content = result.get("content")
        if not isinstance(content, list):
            return []
        return [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]

    async def _request_after_connect(
        self, method: str, params: dict[str, Any] | None = None
    ) -> JsonObject:
        await self.connect()
        return await self._request(method, params)

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> JsonObject:
        async with self._request_lock:
            process = self._require_process()
            request_id = self._next_request_id
            self._next_request_id += 1
            await self._write_message(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
            )
            while True:
                message = await self._read_message(process)
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise ToolClientError(f"O servidor MCP respondeu com erro: {message['error']}")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise ToolClientError("O servidor MCP retornou uma resposta inválida.")
                return result

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._write_message({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _write_message(self, message: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise ToolClientError("A entrada do servidor MCP não está disponível.")
        process.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
        await process.stdin.drain()

    async def _read_message(self, process: asyncio.subprocess.Process) -> JsonObject:
        if process.stdout is None:
            raise ToolClientError("A saída do servidor MCP não está disponível.")
        line = await process.stdout.readline()
        if not line:
            raise ToolClientError("O servidor MCP foi encerrado inesperadamente.")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ToolClientError("O servidor MCP escreveu uma resposta inválida.") from exc
        if not isinstance(message, dict):
            raise ToolClientError("O servidor MCP retornou uma mensagem inválida.")
        return message

    def _is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _require_process(self) -> asyncio.subprocess.Process:
        if not self._is_connected() or self._process is None:
            raise ToolClientError("O servidor MCP não está conectado.")
        return self._process

    async def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            async with asyncio.timeout(5):
                await process.wait()
        except TimeoutError:
            process.terminate()
            try:
                async with asyncio.timeout(5):
                    await process.wait()
            except TimeoutError:
                process.kill()
                await process.wait()

    async def __aenter__(self) -> BrowserToolsClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
