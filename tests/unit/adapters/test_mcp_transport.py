import asyncio

import pytest

from form_agent.adapters.mcp_client import BrowserToolsClient
from form_agent.core.errors import ToolClientError


async def test_concurrent_stdio_requests_are_serialized_and_shutdown():
    client = BrowserToolsClient()
    try:
        results = await asyncio.gather(*(client.list_tools() for _ in range(6)))
        assert all(
            {tool.name for tool in result}
            == {"inspect_form", "fill_field", "read_field", "click_button"}
            for result in results
        )
        process = client._process
    finally:
        await client.close()
    assert process.returncode == 0


async def test_timeout_invalidates_transport_without_retry(monkeypatch):
    client = BrowserToolsClient(timeout_seconds=1)
    await client.connect()
    process = client._process

    async def no_response(process):
        await asyncio.Event().wait()

    monkeypatch.setattr(client, "_read_message", no_response)
    try:
        with pytest.raises(ToolClientError) as error:
            await client.list_tools()
        assert error.value.code == "TIMEOUT"
        assert client._process is None
        assert process.returncode is not None
    finally:
        await client.close()
