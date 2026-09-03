from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from types import TracebackType

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from .config import PROJECT_ROOT
from .errors import ToolClientError
from .schemas import FormInspection, JsonObject, ToolDefinition


class BrowserToolsClient:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds deve ser maior que zero")
        self._timeout_seconds = timeout_seconds
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> ClientSession:
        if self._session is not None:
            return self._session
        async with self._connect_lock:
            if self._session is not None:
                return self._session
            stack = AsyncExitStack()
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "python_poc.mcp_server"],
                env=dict(os.environ),
                cwd=PROJECT_ROOT,
            )
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
            except Exception as exc:
                await stack.aclose()
                raise ToolClientError(
                    "Não foi possível iniciar o servidor MCP do navegador."
                ) from exc
            self._stack = stack
            self._session = session
            return session

    async def list_tools(self) -> list[ToolDefinition]:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await (await self.connect()).list_tools()
        except ToolClientError:
            raise
        except Exception as exc:
            raise ToolClientError("Não foi possível listar as tools do navegador.") from exc
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.inputSchema),
            )
            for tool in response.tools
        ]

    async def inspect_form(self) -> FormInspection:
        return FormInspection.from_mapping(await self.call_tool("inspect_form"))

    async def call_tool(self, name: str, arguments: JsonObject | None = None) -> JsonObject:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await (await self.connect()).call_tool(name, arguments or {})
        except ToolClientError:
            raise
        except Exception as exc:
            raise ToolClientError(f"Falha ao executar a tool {name}.") from exc
        if result.isError:
            details = " ".join(
                item.text for item in result.content if isinstance(item, TextContent) and item.text
            )
            raise ToolClientError(f"A tool {name} falhou: {details or 'erro não informado'}")
        structured = getattr(result, "structuredContent", None) or getattr(
            result, "structured_content", None
        )
        if isinstance(structured, dict):
            return structured
        for item in result.content:
            if isinstance(item, TextContent):
                try:
                    value = json.loads(item.text)
                except json.JSONDecodeError as exc:
                    raise ToolClientError(f"A tool {name} retornou JSON inválido.") from exc
                if isinstance(value, dict):
                    return value
        raise ToolClientError(f"A tool {name} retornou uma resposta vazia.")

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._session = None
        if stack is not None:
            await stack.aclose()

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
