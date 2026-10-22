"""Complete web journey with real HTTP, MCP and Chromium; no remote model calls."""

import asyncio
import io
import socket
import wave

import pytest
import uvicorn
from playwright.async_api import async_playwright, expect

from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.adapters.mcp_client import BrowserToolsClient
from form_agent.bootstrap import Application
from form_agent.config import PROJECT_ROOT, BrowserConfig, ModelConfig
from form_agent.core.agent import FormAgent
from form_agent.core.schemas import ToolCall
from web_api.app import create_app
from web_api.config import WebConfig, asset
from web_api.sessions import SessionManager

pytestmark = pytest.mark.integration


class Model:
    def __init__(self):
        self.batches = iter(
            [
                [
                    ToolCall("name", "fill_field", {"field": "fullName", "value": "Ana"}),
                    ToolCall("city", "fill_field", {"field": "city", "value": "Fortaleza"}),
                ],
                [],
                [
                    ToolCall(
                        "correction",
                        "fill_field",
                        {"field": "city", "value": "Quixadá", "source_text": "Quixadá"},
                    )
                ],
                [
                    ToolCall(
                        "audio-correction",
                        "fill_field",
                        {"field": "city", "value": "Sobral", "source_text": "Sobral"},
                    )
                ],
            ]
        )

    def create_session(self, instruction, inspection, tools):
        return self

    async def next(self, completed):
        return next(self.batches)

    async def close(self):
        pass


class Speech:
    def __init__(self):
        self.texts = iter(
            ["Meu nome é Ana. Moro em Fortaleza.", "Corrija minha cidade para Sobral"]
        )

    def transcribe(self, audio, settings):
        return EngineTranscription("simulated", "1", next(self.texts), "pt", 1.0, 0.1, ())


async def test_browser_upload_correct_confirm_and_close(tmp_path):
    if not (PROJECT_ROOT / "frontend/dist/index.html").is_file():
        pytest.skip("Execute npm run build em frontend/ antes do teste web completo.")

    def factory(events):
        client = BrowserToolsClient(browser_config=BrowserConfig(asset("form.html").as_uri()))
        config = ModelConfig("test", "test", "test", "test-key")
        model = Model()
        return Application(config, FormAgent(client, model, events=events), client, model)

    config = WebConfig(data_dir=tmp_path, frontend_dir=PROJECT_ROOT / "frontend/dist")
    manager = SessionManager(
        config, factory=factory, audio=AudioAgent(AudioPreprocessor(), Speech())
    )
    app = create_app(config, manager=manager)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.02)
        assert server.started
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                await page.goto(f"http://127.0.0.1:{port}")
                await expect(
                    page.get_by_role("button", name="Preencher com áudio", exact=True)
                ).to_be_visible()
                await expect(page.get_by_label("Nome completo")).to_have_value("")
                assert await page.locator(".fields .field").count() == 7
                assert await page.get_by_role("button", name="Começar a falar").count() == 0
                audio = io.BytesIO()
                with wave.open(audio, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(b"\0\0" * 1600)
                await page.locator("#audio-file").set_input_files(
                    {"name": "audio.wav", "mimeType": "audio/wav", "buffer": audio.getvalue()}
                )
                await page.get_by_role("button", name="Preencher com áudio", exact=True).click()
                await expect(page.get_by_label("Nome completo")).to_have_value("Ana", timeout=20000)
                await expect(page.get_by_label("Peça uma correção por texto")).to_be_visible(
                    timeout=10000
                )
                # Reconnect must recover the same state, without another transcription.
                sid = next(iter(manager.sessions))
                await page.reload()
                await expect(page.get_by_label("Nome completo")).to_have_value("Ana")
                assert list(manager.sessions) == [sid]
                await page.get_by_label("Peça uma correção por texto").fill(
                    "Corrija minha cidade para Quixadá"
                )
                await page.get_by_role("button", name="Enviar mensagem", exact=True).click()
                await expect(page.get_by_label("Cidade", exact=True)).to_have_value("Quixadá")
                await expect(page.get_by_label("Nome completo")).to_have_value("Ana")
                # Audio correction is visible without expanding a hidden section.
                await expect(
                    page.get_by_role("heading", name="Corrigir campo por áudio", exact=True)
                ).to_be_visible()
                audio_correction = page.get_by_role(
                    "button", name="Enviar áudio de correção", exact=True
                )
                await expect(audio_correction).to_be_visible()
                await expect(audio_correction).to_be_disabled()
                await page.locator("#audio-file").set_input_files(
                    {"name": "correcao.wav", "mimeType": "audio/wav", "buffer": audio.getvalue()}
                )
                async with page.expect_response(
                    lambda response: (
                        response.url.endswith(f"/{sid}/corrections/audio")
                        and response.request.method == "POST"
                    )
                ) as audio_response:
                    await audio_correction.click()
                assert (await audio_response.value).status == 202
                await expect(page.get_by_label("Cidade", exact=True)).to_have_value("Sobral")
                await expect(page.get_by_label("Nome completo")).to_have_value("Ana")
                await expect(page.get_by_label("E-mail", exact=True)).to_have_value("")
                assert list(manager.sessions) == [sid]
                assert [t["kind"] for t in manager.sessions[sid].transcriptions] == [
                    "initial",
                    "correction",
                ]
                screenshots = PROJECT_ROOT / "reports/web-ui"
                screenshots.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshots / "desktop.png"), full_page=True)
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                await page.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
                await page.get_by_role("button", name="Concluir revisão", exact=True).click()
                await page.get_by_role("button", name="Revisar e confirmar envio").click()
                await expect(page.get_by_role("dialog")).to_be_visible()
                await page.get_by_role("button", name="Confirmar envio", exact=True).click()
                await expect(page.locator(".success-banner")).to_contain_text(
                    "Envio simulado confirmado", timeout=10000
                )
                await page.get_by_role("button", name="Encerrar sessão").click()
                await expect(page.get_by_role("button", name="Iniciar nova sessão")).to_be_visible()
                assert not errors
                assert not manager.sessions[sid].directory.exists()
            finally:
                await browser.close()
    finally:
        server.should_exit = True
        await task
        sock.close()
