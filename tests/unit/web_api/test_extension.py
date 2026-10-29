import asyncio

import httpx
import pytest
from test_sessions import web

from form_agent.core.errors import ToolClientError
from web_api.app import create_app
from web_api.extension import ExtensionToolsClient, extension_owner


def headers(token, client="a" * 32, **extra):
    return {"Authorization": f"Bearer {token}", "X-VozForm-Client": client, **extra}


async def test_bridge_delivers_once_rejects_unmatched_ack_and_blocks_submission():
    bridge = ExtensionToolsClient("https://example.com/form", "document")
    task = asyncio.create_task(bridge.call_tool("fill_field", {"field": "name", "value": "Ana"}))
    await asyncio.sleep(0)
    command = bridge.pending.copy()
    assert bridge.pending == command  # Polling does not dequeue or regenerate a command.
    assert not bridge.resolve("wrong-id", {"success": True})
    assert bridge.resolve(command["id"], {"success": True, "value": "Ana"})
    assert not bridge.resolve(command["id"], {"success": True})
    assert (await task)["value"] == "Ana"
    assert bridge.pending is None
    assert (await bridge.call_tool("click_button", {"button": "submit"}))[
        "code"
    ] == "SUBMISSION_BLOCKED"
    with pytest.raises(ToolClientError, match="envio"):
        await bridge.set_submission_authorized(True)


async def test_close_interrupts_pending_operation_and_timeout_fails_closed():
    bridge = ExtensionToolsClient("https://example.com", "document")
    task = asyncio.create_task(bridge.inspect_form())
    await asyncio.sleep(0)
    await bridge.close()
    with pytest.raises(ToolClientError, match="encerrada"):
        await task
    with pytest.raises(ToolClientError, match="encerrada"):
        await bridge.inspect_form()
    bridge = ExtensionToolsClient("https://example.com", "document", timeout=0.01)
    with pytest.raises(ToolClientError, match="não respondeu"):
        await bridge.inspect_form()
    assert bridge.closed and bridge.pending is None


async def test_inventory_cannot_switch_to_a_different_url():
    bridge = ExtensionToolsClient("https://example.com", "document")
    task = asyncio.create_task(bridge.inspect_form())
    await asyncio.sleep(0)
    bridge.resolve(bridge.pending["id"], {"url": "https://other.example"})
    with pytest.raises(ToolClientError, match="página mudou"):
        await task


@pytest.mark.parametrize(
    "authorization,client,origin",
    [
        ("wrong", "a" * 32, ""),
        ("secret", "not-an-extension", ""),
        ("secret", "a" * 32, "https://evil.example"),
        ("secret", "a" * 32, "chrome-extension://" + "b" * 32),
    ],
)
def test_pairing_rejects_invalid_codes_and_web_origins(authorization, client, origin):
    with pytest.raises(ValueError):
        extension_owner(
            {
                "authorization": f"Bearer {authorization}",
                "x-vozform-client": client,
                "origin": origin,
            },
            "secret",
        )


async def test_extension_sessions_are_isolated_from_web_and_close_without_a_reply(tmp_path):
    async with web(tmp_path, max_sessions=2) as (client, manager, apps, speech):
        # The ordinary web flow and its cookie continue to work.
        existing = (await client.post("/api/sessions")).json()
        app = client._transport.app
        paired = headers(app.state.extension_token, Origin="chrome-extension://" + "a" * 32)
        assert (await client.get("/extension/setup")).status_code == 403
        setup = await client.get("http://127.0.0.1/extension/setup")
        assert app.state.extension_token in setup.text
        assert setup.headers["cache-control"] == "no-store"
        assert (
            await client.post(
                "/api/extension/sessions", json={"url": "https://example.com", "document_id": "doc"}
            )
        ).status_code == 401
        response = await client.post(
            "/api/extension/sessions",
            headers=paired,
            json={"url": "https://example.com", "document_id": "doc"},
        )
        assert response.status_code == 201
        session = response.json()
        assert session["transport"] == "extension" and not session["submission_supported"]
        sid = session["id"]
        for _ in range(100):
            poll = (await client.get(f"/api/extension/sessions/{sid}/poll", headers=paired)).json()
            if poll["command"]:
                break
            await asyncio.sleep(0)
        assert poll["command"]["name"] == "inspect_form"
        assert (await client.get(f"/api/sessions/{sid}")).status_code == 404
        assert (
            await client.get(f"/api/sessions/{existing['id']}", headers=paired)
        ).status_code == 404
        assert (
            await client.get(
                f"/api/sessions/{sid}", headers=headers(app.state.extension_token, "b" * 32)
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/api/sessions/{sid}/submit",
                headers=paired,
                json={"confirmation": "ENVIAR", "revision": 0},
            )
        ).status_code == 409
        assert (await client.delete(f"/api/sessions/{sid}", headers=paired)).status_code == 202
        await asyncio.wait_for(manager.sessions[sid].close_task, 1)
        assert manager.sessions[sid].state == "closed"
        assert apps[-1].agent.tools.tools is manager.sessions[sid].bridge
        assert not manager.sessions[existing["id"]].closing


async def test_extension_code_rotates_between_server_starts(tmp_path):
    async with web(tmp_path) as (_, manager, _, _):
        first = create_app(manager.config, manager=manager)
        second = create_app(manager.config, manager=manager)
        assert first.state.extension_token != second.state.extension_token
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=second), base_url="http://test"
        ) as client:
            response = await client.get("/api/health", headers=headers(first.state.extension_token))
            assert response.status_code == 401
