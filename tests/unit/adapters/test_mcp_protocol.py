import pytest

from form_agent.mcp.server import _handle


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "1.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 1},
    ],
)
async def test_invalid_envelope(message):
    response = await _handle(message)
    assert response["error"]["code"] == -32600


async def test_permission_cannot_be_forged_as_tool_argument():
    response = await _handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "click_button",
                "arguments": {"button": "Enviar", "authorized": "true"},
            },
        }
    )
    assert response["error"]["code"] == -32602


async def test_permission_is_not_a_tool():
    response = await _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "form-agent/authorize-submission" not in [t["name"] for t in response["result"]["tools"]]


async def test_unknown_tool_and_wrong_type_are_rejected():
    for name, arguments in [("missing", {}), ("fill_field", {"field": "Nome", "value": True})]:
        response = await _handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        assert response["error"]["code"] == -32602


async def test_browser_error_provenance_survives_protocol(monkeypatch):
    from form_agent.core.errors import AmbiguousElementError
    from form_agent.mcp import server

    async def ambiguous(arguments):
        raise AmbiguousElementError("Dois campos Nome")

    definition = server.TOOLS["fill_field"]
    monkeypatch.setitem(server.TOOLS, "fill_field", (definition[0], definition[1], ambiguous))
    response = await _handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "fill_field", "arguments": {"field": "Nome", "value": "Ana"}},
        }
    )
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["code"] == "FIELD_AMBIGUOUS"
