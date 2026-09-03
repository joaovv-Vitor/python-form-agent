from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from ..adapters.playwright_browser import BrowserController
from ..core.schemas import JsonObject

logging.getLogger("mcp").setLevel(logging.WARNING)

controller = BrowserController()


@asynccontextmanager
async def server_lifespan(_: FastMCP[None]) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await controller.close()


mcp: FastMCP[None] = FastMCP(
    "form-browser-mcp-python",
    lifespan=server_lifespan,
    log_level="WARNING",
)


@mcp.tool()
async def inspect_form() -> JsonObject:
    """Inspeciona semanticamente os controles do formulário."""
    return (await controller.inspect_form()).to_dict()


@mcp.tool()
async def fill_field(field: str, value: str) -> JsonObject:
    """Preenche um campo por label, name, id ou placeholder."""
    return await controller.fill_field(field, value)


@mcp.tool()
async def read_field(field: str) -> JsonObject:
    """Lê o valor atual de um campo."""
    return await controller.read_field(field)


@mcp.tool()
async def click_button(button: str) -> JsonObject:
    """Clica em um botão identificado semanticamente."""
    return await controller.click_button(button)


if __name__ == "__main__":
    mcp.run(transport="stdio")
