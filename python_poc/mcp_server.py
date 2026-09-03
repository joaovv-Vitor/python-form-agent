from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from .browser import BrowserController

mcp = FastMCP("form-browser-mcp-python")
controller = BrowserController()


@mcp.tool()
async def inspect_form() -> dict[str, Any]:
    """Inspeciona semanticamente os controles do formulário."""
    return await controller.inspect_form()


@mcp.tool()
async def fill_field(field: str, value: str) -> dict[str, Any]:
    """Preenche um campo por label, name, id ou placeholder."""
    return await controller.fill_field(field, value)


@mcp.tool()
async def read_field(field: str) -> dict[str, Any]:
    """Lê o valor atual de um campo."""
    return await controller.read_field(field)


@mcp.tool()
async def click_button(button: str) -> dict[str, Any]:
    """Clica em um botão identificado semanticamente."""
    return await controller.click_button(button)


if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    finally:
        asyncio.run(controller.close())
