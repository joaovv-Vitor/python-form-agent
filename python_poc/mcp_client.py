from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class BrowserToolsClient:
    def __init__(self) -> None:
        self.stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> ClientSession:
        if self.session:
            return self.session
        params = StdioServerParameters(command=sys.executable, args=["-m", "python_poc.mcp_server"], env=dict(os.environ))
        read, write = await self.stack.enter_async_context(stdio_client(params))
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        return self.session

    async def list_tools(self) -> list[dict[str, Any]]:
        response = await (await self.connect()).list_tools()
        return [{"name": tool.name, "description": tool.description or "", "inputSchema": tool.inputSchema} for tool in response.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await (await self.connect()).call_tool(name, arguments or {})
        if result.isError:
            raise RuntimeError(f"Tool {name} falhou: {result.content}")
        structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            return structured
        for item in result.content:
            if getattr(item, "type", None) == "text":
                return json.loads(item.text)
        return {}

    async def close(self) -> None:
        await self.stack.aclose()
        self.session = None
