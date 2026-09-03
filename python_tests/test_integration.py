import pytest

from python_poc.mcp_client import BrowserToolsClient


@pytest.mark.asyncio
@pytest.mark.integration
async def test_python_mcp_playwright_roundtrip(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HEADLESS", "true")
    client = BrowserToolsClient()
    try:
        tools = await client.list_tools()
        inspection = await client.inspect_form()
        filled = await client.call_tool(
            "fill_field", {"field": "Nome completo", "value": "Teste Python"}
        )
        read = await client.call_tool("read_field", {"field": "Nome completo"})
        assert {tool.name for tool in tools} == {
            "inspect_form",
            "fill_field",
            "read_field",
            "click_button",
        }
        assert len(inspection.fields) == 7
        assert filled["success"] is True
        assert read["value"] == "Teste Python"
    finally:
        await client.close()
