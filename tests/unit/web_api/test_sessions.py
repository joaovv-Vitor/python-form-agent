import asyncio
import io
import wave
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx

from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.bootstrap import Application
from form_agent.config import ModelConfig
from form_agent.core.agent import FormAgent
from form_agent.core.schemas import (
    FormButton,
    FormField,
    FormInspection,
    FormOption,
    ToolCall,
    ToolDefinition,
)
from web_api.app import create_app
from web_api.config import WebConfig, asset
from web_api.sessions import SessionManager


def wav(seconds=0.03):
    data = io.BytesIO()
    with wave.open(data, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * int(16000 * seconds))
    return data.getvalue()


def call(name, value, source=None):
    args = {"field": name, "value": value}
    if source is not None:
        args["source_text"] = source
    return ToolCall("id", "fill_field", args)


class Tools:
    def __init__(self):
        types = {
            "email": "email",
            "phone": "tel",
            "birthDate": "date",
            "state": "select",
            "acceptTerms": "checkbox",
        }
        self.inspection = FormInspection(
            "file:///private/form.html",
            tuple(
                FormField(
                    n,
                    n,
                    n,
                    types.get(n, "text"),
                    "textbox",
                    value=False if n == "acceptTerms" else "",
                    valid=True,
                    options=(FormOption("Ceará", "CE"),) if n == "state" else (),
                )
                for n in ["fullName", "email", "phone", "birthDate", "city", "state", "acceptTerms"]
            ),
            (FormButton("Enviar", "submitButton", "submitButton", "submit"),),
        )
        self.closed = False
        self.authorized = False
        self.calls = []

    async def inspect_form(self):
        return self.inspection

    async def list_tools(self):
        return [
            ToolDefinition(n, n)
            for n in ["inspect_form", "fill_field", "read_field", "click_button"]
        ]

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if name == "click_button":
            assert self.authorized
            return {"success": True, "submitted": True}
        if name == "fill_field":
            self.inspection = replace(
                self.inspection,
                fields=tuple(
                    replace(f, value=arguments["value"]) if f.reference == arguments["field"] else f
                    for f in self.inspection.fields
                ),
            )
        f = next(f for f in self.inspection.fields if f.reference == arguments["field"])
        return {
            "success": True,
            "field": f.label,
            "field_ref": f.reference,
            "value": f.value,
            "valid": True,
        }

    async def set_submission_authorized(self, value):
        self.authorized = value

    async def close(self):
        self.closed = True


class Model:
    def __init__(self, batches):
        self.batches = deque(batches)
        self.closed = False

    def create_session(self, instruction, inspection, tools):
        return self

    async def next(self, completed):
        return self.batches.popleft()

    async def close(self):
        self.closed = True


class Speech:
    def __init__(self, texts=None):
        self.texts = deque(texts or ["Meu nome é Ana. Moro em Fortaleza."])
        self.calls = 0

    def transcribe(self, audio, settings):
        self.calls += 1
        return EngineTranscription("test", "1", self.texts.popleft(), "pt", 1.0, 0.03, ())


@asynccontextmanager
async def web(tmp_path, batches=None, texts=None, **settings):
    apps = []

    def factory(events):
        model = Model(
            batches
            if batches is not None
            else [[call("fullName", "Ana"), call("city", "Fortaleza")], []]
        )
        tools = Tools()
        config = ModelConfig("test", "test", "test", "test-key")
        app = Application(config, FormAgent(tools, model, events=events), tools, model)
        apps.append(app)
        return app

    speech = Speech(texts)
    config = WebConfig(data_dir=tmp_path, frontend_dir=tmp_path / "dist", **settings)
    manager = SessionManager(config, factory=factory, audio=AudioAgent(AudioPreprocessor(), speech))
    app = create_app(config, manager=manager)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client, manager, apps, speech


async def wait(client, sid, state):
    for _ in range(500):
        response = await client.get(f"/api/sessions/{sid}")
        value = response.json()
        if value["state"] == state:
            return value
        await asyncio.sleep(0.002)
    raise AssertionError(value)


async def start(client):
    r = await client.post("/api/sessions")
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    await wait(client, sid, "ready")
    return sid


async def fill(client, sid):
    r = await client.post(
        f"/api/sessions/{sid}/audio", files={"file": ("voice.wav", wav(), "audio/wav")}
    )
    assert r.status_code == 202, r.text
    return await wait(client, sid, "reviewing")


async def test_real_pipeline_review_confirmation_and_cleanup(tmp_path):
    async with web(
        tmp_path,
        batches=[
            [call("fullName", "Ana"), call("city", "Fortaleza")],
            [],
            [ToolCall("ask", "ask_clarification", {"question": "Qual cidade?"})],
            [call("city", "Quixadá", "Quixadá")],
        ],
    ) as (client, manager, apps, speech):
        sid = await start(client)
        assert len((await client.get(f"/api/sessions/{sid}")).json()["fields"]) == 7
        data = await fill(client, sid)
        assert not data["can_submit"]
        assert "/private/" not in str(data)
        await client.post(
            f"/api/sessions/{sid}/messages", json={"text": "Minha cidade está errada"}
        )
        data = await wait(client, sid, "awaiting_answer")
        assert data["question"] == "Qual cidade?"
        assert (await client.post(f"/api/sessions/{sid}/review/complete")).status_code == 409
        await client.post(f"/api/sessions/{sid}/messages", json={"text": "Quixadá"})
        data = await wait(client, sid, "reviewing")
        values = {f["reference"]: f["value"] for f in data["fields"]}
        assert values["fullName"] == "Ana" and values["city"] == "Quixadá"
        assert (
            await client.post(
                f"/api/sessions/{sid}/submit",
                json={"confirmation": "ENVIAR", "revision": data["revision"]},
            )
        ).status_code == 409
        await client.post(f"/api/sessions/{sid}/review/complete")
        data = await wait(client, sid, "review_complete")
        assert (
            await client.post(
                f"/api/sessions/{sid}/submit",
                json={"confirmation": "ENVIAR", "revision": data["revision"] - 1},
            )
        ).status_code == 409
        assert (
            await client.post(
                f"/api/sessions/{sid}/submit",
                json={"confirmation": "ENVIAR", "revision": data["revision"]},
            )
        ).status_code == 202
        await wait(client, sid, "sent")
        assert (
            await client.post(
                f"/api/sessions/{sid}/submit",
                json={"confirmation": "ENVIAR", "revision": data["revision"]},
            )
        ).status_code == 409
        assert not apps[0].client.authorized
        await client.delete(f"/api/sessions/{sid}")
        await wait(client, sid, "closed")
        assert apps[0].client.closed and apps[0].model.closed
        assert not manager.sessions[sid].directory.exists()
        assert (tmp_path / "sessions" / sid / "form_data.json").is_file()
        import json

        assert (
            json.loads((tmp_path / "sessions" / sid / "form_data.json").read_text())["submitted"]
            is True
        )


async def test_uploaded_audio_correction_uses_same_session(tmp_path):
    async with web(
        tmp_path,
        batches=[[call("city", "Fortaleza")], [], [call("city", "Quixadá", "Quixadá")]],
        texts=["Moro em Fortaleza", "Minha cidade é Quixadá"],
    ) as (client, manager, apps, speech):
        sid = await start(client)
        await fill(client, sid)
        r = await client.post(
            f"/api/sessions/{sid}/corrections/audio", files={"file": ("fix.wav", wav())}
        )
        assert r.status_code == 202
        data = await wait(client, sid, "reviewing")
        assert data["corrections"][0]["status"] == "applied"
        assert len(data["transcriptions"]) == 2 and speech.calls == 2 and len(apps) == 1


async def test_owner_origin_capacity_and_input_validation(tmp_path):
    async with web(tmp_path) as (client, manager, apps, speech):
        assert (
            await client.post("/api/sessions", headers={"Origin": "https://evil.test"})
        ).status_code == 403
        sid = await start(client)
        assert (await client.post("/api/sessions")).status_code == 503
        async with httpx.AsyncClient(transport=client._transport, base_url="http://test") as other:
            assert (await other.get(f"/api/sessions/{sid}")).status_code == 404
            assert (await other.delete(f"/api/sessions/{sid}")).status_code == 404
        for name, content, expected in [
            ("test.txt", b"x", 415),
            ("test.wav", b"", 422),
            ("bad.wav", b"bad", 422),
        ]:
            r = await client.post(f"/api/sessions/{sid}/audio", files={"file": (name, content)})
            assert r.status_code == expected, r.text
        assert (
            await client.post(
                f"/api/sessions/{sid}/messages", json={"text": "hi", "path": "/etc/passwd"}
            )
        ).status_code == 422
        assert speech.calls == 0
        assert (await client.get(f"/api/sessions/{sid}")).json()["state"] == "ready"


async def test_audio_limits_and_bounded_event_recovery(tmp_path):
    async with web(tmp_path, max_audio_seconds=0.01, max_upload_bytes=2000, event_buffer=2) as (
        client,
        manager,
        apps,
        speech,
    ):
        sid = await start(client)
        r = await client.post(f"/api/sessions/{sid}/audio", files={"file": ("long.wav", wav())})
        assert r.status_code == 422 and "segundos" in r.text
        r = await client.post(
            f"/api/sessions/{sid}/audio", files={"file": ("big.wav", b"0" * 2001)}
        )
        assert r.status_code == 413
        s = manager.sessions[sid]
        s.notify("one")
        s.notify("two")
        s.notify("three")
        stream = s.stream(0)
        first = await anext(stream)
        assert '"type": "snapshot"' in first and '"fields"' in first
        await stream.aclose()
        assert s.state == "ready" and speech.calls == 0


def test_packaged_runtime_assets_match_standard_form():
    from form_agent.config import PROJECT_ROOT

    assert (
        asset("form.html").read_bytes()
        == (PROJECT_ROOT / "examples/test-form/index.html").read_bytes()
    )
    assert asset("model-profiles.json").is_file()


async def test_expiration_and_lost_tab_reuse(tmp_path):
    async with web(tmp_path, idle_seconds=0.04) as (client, manager, apps, speech):
        sid = await start(client)
        assert (await client.get("/api/session")).json()["id"] == sid
        for _ in range(100):
            if manager.sessions[sid].state == "expired":
                break
            await asyncio.sleep(0.01)
        assert manager.sessions[sid].state == "expired"
        assert apps[0].client.closed
        assert (await client.get("/api/session")).status_code == 404


async def test_close_during_native_inference_waits_and_prevents_writes(tmp_path):
    import threading

    entered, release = threading.Event(), threading.Event()
    async with web(tmp_path) as (client, manager, apps, speech):
        original = speech.transcribe

        def blocked(audio, settings):
            entered.set()
            release.wait(5)
            return original(audio, settings)

        speech.transcribe = blocked
        sid = await start(client)
        await client.post(f"/api/sessions/{sid}/audio", files={"file": ("voice.wav", wav())})
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        try:
            assert entered.is_set()
            assert (await client.delete(f"/api/sessions/{sid}")).status_code == 202
            assert manager.sessions[sid].state == "closing"
            assert not apps[0].client.closed
        finally:
            release.set()
        await wait(client, sid, "closed")
        assert not apps[0].client.calls and apps[0].client.closed


async def test_two_sessions_never_share_values(tmp_path):
    async with web(tmp_path, max_sessions=2) as (client, manager, apps, speech):
        first = await start(client)
        second = await start(client)
        await fill(client, first)
        untouched = (await client.get(f"/api/sessions/{second}")).json()
        assert all(f["value"] in ("", False) for f in untouched["fields"])
        await client.delete(f"/api/sessions/{first}")
        await wait(client, first, "closed")
        assert manager.sessions[second].state == "ready" and not apps[1].client.closed
