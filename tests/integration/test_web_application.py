"""Complete web journey with real HTTP, MCP and Chromium; no remote model calls."""

import asyncio
import io
import json
import socket
import wave

import pytest
import uvicorn
from fastapi.responses import HTMLResponse, RedirectResponse
from playwright.async_api import async_playwright, expect

from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.adapters.mcp_client import BrowserToolsClient
from form_agent.bootstrap import Application
from form_agent.config import PROJECT_ROOT, BrowserConfig, ModelConfig
from form_agent.core.agent import FormAgent
from form_agent.core.errors import ToolClientError
from form_agent.core.schemas import ToolCall
from web_api.app import create_app
from web_api.config import WebConfig
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


@pytest.fixture
async def web_runtime(tmp_path):
    if not (PROJECT_ROOT / "frontend/dist/index.html").is_file():
        pytest.skip("Execute npm run build em frontend/ antes do teste web completo.")

    def factory(events, browser):
        client = BrowserToolsClient(browser_config=browser)
        config = ModelConfig("test", "test", "test", "test-key")
        model = Model()
        return Application(config, FormAgent(client, model, events=events), client, model)

    config = WebConfig(
        data_dir=tmp_path,
        frontend_dir=PROJECT_ROOT / "frontend/dist",
        allowed_form_hosts=("127.0.0.1",),
    )
    manager = SessionManager(
        config, factory=factory, audio=AudioAgent(AudioPreprocessor(), Speech())
    )
    app = create_app(config, manager=manager)
    # Register before the frontend catch-all mount.
    mount = app.routes.pop()

    @app.get("/external-form", response_class=HTMLResponse)
    async def external_form():
        return '<!doctype html><html><body><form><label for="nickname">Apelido público</label><input id="nickname" name="nickname" required><label for="notes">Observações adicionais</label><textarea id="notes" name="notes"></textarea><button type="submit">Salvar</button></form></body></html>'

    @app.get("/external-redirect")
    async def external_redirect():
        return RedirectResponse("http://localhost/private")

    app.routes.append(mount)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.02)
        assert server.started
        yield manager, f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        await task
        sock.close()


async def interrupt_first_stream(page, manager):
    reconnected = asyncio.Event()
    first = True

    async def events(route):
        nonlocal first
        if not first:
            reconnected.set()
            await route.continue_()
            return
        first = False
        session = next(iter(manager.sessions.values()))
        await asyncio.shield(session.task)
        event = session.events[-1]
        # Close just after delivering a valid snapshot, simulating a lost connection.
        await route.fulfill(
            content_type="text/event-stream",
            body=f"id: {event['id']}\nevent: session\ndata: {json.dumps(event)}\n\n",
        )

    await page.route("**/api/sessions/*/events", events)
    return reconnected


async def test_selecting_catalogue_and_custom_url_loads_the_actual_fields(web_runtime):
    manager, url = web_runtime
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            await page.goto(url)
            await expect(page.get_by_label("Nome completo")).to_be_visible()
            await expect(page.locator(".field-error, .field.invalid")).to_have_count(0)
            selector = page.get_by_label("Formulários de demonstração")
            await expect(selector.locator("option").first).to_have_text(
                "1. Cadastro — formulário original"
            )
            for form_id, label in [
                ("contato", "Sua mensagem"),
                ("inscricao", "Evento desejado"),
                ("suporte", "Prioridade do chamado"),
            ]:
                await selector.select_option(form_id)
                await page.get_by_role("button", name="Abrir formulário", exact=True).click()
                await expect(page.get_by_label(label)).to_be_visible(timeout=15000)
                await expect(page.locator(".field-error, .field.invalid")).to_have_count(0)
                await expect(
                    page.get_by_role("button", name="Usar microfone", exact=True)
                ).to_be_visible()
                assert len([s for s in manager.sessions.values() if not s.closing]) == 1
            await selector.select_option("custom")
            await page.get_by_label("URL do formulário", exact=True).fill(f"{url}/external-form")
            await page.get_by_role("button", name="Abrir formulário", exact=True).click()
            await expect(page.get_by_label("Apelido público")).to_be_visible(timeout=15000)
            await expect(page.get_by_label("Observações adicionais", exact=True)).to_be_visible()
            await expect(page.locator(".field-error, .field.invalid")).to_have_count(0)
            active_session = next(s for s in manager.sessions.values() if not s.closing)
            assert not active_session.target.demo
            assert not active_session.public()["can_submit"]
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            folder = PROJECT_ROOT / "reports/web-ui"
            folder.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(folder / "form-selector-mobile.png"), full_page=True)
            # A missing required value still becomes visible after the filling attempt.
            active_session.application.model.batches = iter(
                [[ToolCall("notes", "fill_field", {"field": "notes", "value": "Fortaleza"})], []]
            )
            audio = io.BytesIO()
            with wave.open(audio, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b"\0\0" * 1600)
            await page.locator("#audio-file").set_input_files(
                {"name": "arquivo.wav", "mimeType": "audio/wav", "buffer": audio.getvalue()}
            )
            await page.get_by_role("button", name="Preencher com áudio", exact=True).click()
            await expect(page.get_by_label("Observações adicionais", exact=True)).to_have_value(
                "Fortaleza", timeout=20000
            )
            await expect(page.locator(".field.invalid .field-error")).to_be_visible()
            await expect(page.get_by_label("Apelido público")).to_have_value("")
            await expect(
                page.get_by_role("button", name="Concluir revisão", exact=True)
            ).to_have_count(0)
            assert not active_session.public()["can_complete"]
        finally:
            await browser.close()


async def test_external_redirect_is_not_followed(web_runtime):
    manager, url = web_runtime
    client = BrowserToolsClient(
        browser_config=BrowserConfig(
            f"{url}/external-redirect",
            form_selector="form",
            restrict_network=True,
            allowed_hosts=("127.0.0.1",),
        )
    )
    try:
        with pytest.raises(ToolClientError, match="Não foi possível abrir"):
            await client.inspect_form()
    finally:
        await client.close()


async def test_chrome_extension_fills_real_tab_corrects_and_preserves_web(web_runtime, tmp_path):
    manager, url = web_runtime
    extension = PROJECT_ROOT / "extension/dist"
    if not (extension / "manifest.json").is_file():
        pytest.skip("Execute npm run build:extension em frontend/ antes do teste da extensão.")
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            tmp_path / "chrome",
            channel="chromium",
            headless=True,
            args=[
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ],
        )
        try:
            worker = (
                context.service_workers[0]
                if context.service_workers
                else await context.wait_for_event("serviceworker")
            )
            extension_id = worker.url.split("/")[2]
            target = await context.new_page()
            await target.goto(f"{url}/forms/cadastro")
            await target.evaluate(
                "window.cityChanges = 0; document.querySelector('#city').addEventListener('change', () => window.cityChanges++)"
            )
            panel = await context.new_page()
            await panel.set_viewport_size({"width": 390, "height": 1000})
            errors = []
            panel.on("pageerror", lambda error: errors.append(str(error)))
            await panel.goto(f"chrome-extension://{extension_id}/extension.html")
            # External-site metadata can omit URL without exposing browsing history.
            # The panel must use the tab ID and let Chrome enforce injection access.
            await panel.evaluate("""() => {
                const query = chrome.tabs.query.bind(chrome.tabs);
                chrome.tabs.query = async options => (await query(options)).map(tab => ({id: tab.id}));
            }""")
            assert await worker.evaluate("chrome.action.onClicked.hasListeners()")
            assert not (await worker.evaluate("chrome.sidePanel.getPanelBehavior()"))[
                "openPanelOnActionClick"
            ]
            setup = await context.new_page()
            await setup.goto(f"{url}/extension/setup")
            code = await setup.locator("#pairing").input_value()
            await setup.close()
            await panel.get_by_label("Servidor local").fill(url)
            await panel.get_by_label("Código de conexão").fill(code)
            await target.bring_to_front()
            await panel.get_by_role("button", name="Usar formulário desta aba").click()
            await expect(
                panel.get_by_role("button", name="Usar microfone", exact=True)
            ).to_be_enabled(timeout=15000)
            session = next(iter(manager.sessions.values()))
            assert session.bridge is not None
            assert session.public()["transport"] == "extension"
            # Opening a second page never redirects the selected session's writes.
            decoy = await context.new_page()
            await decoy.goto(f"{url}/forms/cadastro")
            await decoy.bring_to_front()
            dropped = False

            async def lose_first_fill_reply(route):
                nonlocal dropped
                if (
                    not dropped
                    and session.bridge.pending
                    and session.bridge.pending["name"] == "fill_field"
                    and route.request.post_data_json["result"].get("field") == "Cidade"
                ):
                    dropped = True
                    await route.fulfill(
                        status=503, json={"detail": "Simulated lost acknowledgement"}
                    )
                else:
                    await route.continue_()

            await panel.route("**/api/extension/sessions/*/results", lose_first_fill_reply)
            await panel.get_by_role("button", name="Usar microfone", exact=True).click()
            await expect(
                panel.get_by_role("button", name="Parar gravação", exact=True)
            ).to_be_visible()
            await asyncio.sleep(0.3)
            await panel.get_by_role("button", name="Parar gravação", exact=True).click()
            await expect(panel.locator("audio")).to_be_visible()
            assert not session.transcriptions
            audio = io.BytesIO()
            with wave.open(audio, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b"\0\0" * 1600)
            await panel.locator("#audio-file").set_input_files(
                {"name": "teste.wav", "mimeType": "audio/wav", "buffer": audio.getvalue()}
            )
            await panel.get_by_role("button", name="Preencher com áudio", exact=True).click()
            await expect(target.locator("#fullName")).to_have_value("Ana", timeout=20000)
            await expect(target.locator("#city")).to_have_value("Fortaleza", timeout=20000)
            await expect(panel.get_by_label("Peça uma correção por texto")).to_be_visible(
                timeout=15000
            )
            assert dropped
            assert await target.evaluate("window.cityChanges") == 1
            await expect(decoy.locator("#fullName")).to_have_value("")
            await expect(decoy.locator("#city")).to_have_value("")
            await panel.get_by_label("Peça uma correção por texto").fill(
                "Corrija minha cidade para Quixadá"
            )
            await panel.get_by_role("button", name="Enviar mensagem", exact=True).click()
            await expect(target.locator("#city")).to_have_value("Quixadá", timeout=15000)
            await expect(panel.get_by_label("Peça uma correção por texto")).to_be_enabled()
            # The same file can be selected again after the initial upload.
            await panel.locator("#audio-file").set_input_files(
                {"name": "teste.wav", "mimeType": "audio/wav", "buffer": audio.getvalue()}
            )
            await panel.get_by_role("button", name="Enviar áudio de correção", exact=True).click()
            await expect(target.locator("#city")).to_have_value("Sobral", timeout=15000)
            assert [item["kind"] for item in session.transcriptions] == ["initial", "correction"]
            await panel.get_by_role("button", name="Concluir revisão", exact=True).click()
            await expect(
                panel.get_by_text(
                    "Revisão concluída. Confira os valores na página e clique em Enviar no próprio site."
                )
            ).to_be_visible()
            assert not session.public()["can_submit"]
            assert await target.locator('[data-form-agent-submitted="true"]').count() == 0
            assert not errors
            folder = PROJECT_ROOT / "reports/web-ui"
            folder.mkdir(parents=True, exist_ok=True)
            await panel.screenshot(path=str(folder / "extension-panel.png"), full_page=True)
            await panel.get_by_role("button", name="Encerrar sessão", exact=True).click()
            await expect(
                panel.get_by_role("button", name="Usar formulário desta aba")
            ).to_be_visible()
            await asyncio.wait_for(session.close_task, 2)
            # The existing web application still starts its original independent flow.
            web_page = await context.new_page()
            await web_page.goto(url)
            await expect(web_page.get_by_label("Nome completo")).to_be_visible(timeout=15000)
        finally:
            await context.close()


async def test_extension_document_guards_and_controls_without_ids(web_runtime, tmp_path):
    _, url = web_runtime
    extension = PROJECT_ROOT / "extension/dist"
    if not (extension / "manifest.json").is_file():
        pytest.skip("Execute npm run build:extension em frontend/ antes do teste da extensão.")
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            tmp_path / "chrome",
            channel="chromium",
            headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            worker = (
                context.service_workers[0]
                if context.service_workers
                else await context.wait_for_event("serviceworker")
            )
            target = await context.new_page()
            await target.goto(f"{url}/external-form")
            await target.set_content("""<form>
                <label>Nome<input name="person" required></label>
                <label>Pequeno<input type="radio" name="size" value="small"></label>
                <label>Grande<input type="radio" name="size" value="large"></label>
                <label>Estado<select name="state"><option value="">Selecione</option><option value="CE">Ceará</option></select></label>
                <label>Mensagem<textarea name="message"></textarea></label>
                <label>Aceito<input type="checkbox" name="terms"></label>
                <button>Enviar</button></form>
                <script>window.changes = 0; document.querySelector('[name=person]').addEventListener('change', () => window.changes++)</script>""")
            tab_id = await worker.evaluate(
                "async url => (await chrome.tabs.query({url}))[0].id", target.url
            )
            await worker.evaluate(
                "async id => chrome.scripting.executeScript({target:{tabId:id},files:['content-script.js']})",
                tab_id,
            )

            async def send(message):
                return await worker.evaluate(
                    "async ({id,message}) => chrome.tabs.sendMessage(id, {source:'vozform',...message})",
                    {"id": tab_id, "message": message},
                )

            page = await send({"kind": "prepare"})
            assert page["success"]
            assert len({field["id"] for field in page["fields"]}) == 6
            sequence = 0

            async def command(name, arguments):
                nonlocal sequence
                sequence += 1
                return await send(
                    {
                        "kind": "command",
                        "command": {
                            "id": str(sequence),
                            "name": name,
                            "arguments": arguments,
                            "document_id": page["document_id"],
                            "url": page["url"],
                        },
                    }
                )

            await command("fill_field", {"field": "person", "value": "Ana"})
            # Replaying the same command reuses its reply without emitting another change.
            await send(
                {
                    "kind": "command",
                    "command": {
                        "id": "1",
                        "name": "fill_field",
                        "arguments": {"field": "person", "value": "Ana"},
                        "document_id": page["document_id"],
                        "url": page["url"],
                    },
                }
            )
            assert await target.evaluate("window.changes") == 1
            await command("fill_field", {"field": "Grande", "value": "true"})
            await expect(target.locator('[value="large"]')).to_be_checked()
            await expect(target.locator('[value="small"]')).not_to_be_checked()
            await command("fill_field", {"field": "state", "value": "Ceará"})
            await command("fill_field", {"field": "message", "value": "Teste acadêmico"})
            await command("fill_field", {"field": "terms", "value": "sim"})
            await expect(target.locator("select")).to_have_value("CE")
            await expect(target.locator("textarea")).to_have_value("Teste acadêmico")
            await expect(target.locator('[name="terms"]')).to_be_checked()
            assert not (await command("click_button", {"button": "Enviar"}))["success"]
            await target.evaluate("location.hash = 'outra-etapa'")
            assert not (await command("fill_field", {"field": "person", "value": "Outra pessoa"}))[
                "success"
            ]
            await expect(target.locator('[name="person"]')).to_have_value("Ana")
            await target.set_content(
                '<form><label>Senha<input type="password" value="do-not-transfer"></label></form>'
            )
            rejected = await send({"kind": "prepare"})
            assert not rejected["success"] and "senha" in rejected["error"]
            assert "do-not-transfer" not in str(rejected)
        finally:
            await context.close()


async def test_expired_session_after_dropped_stream_can_restart_without_reload(web_runtime):
    manager, url = web_runtime
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await interrupt_first_stream(page, manager)
            await page.goto(url)
            await expect(
                page.get_by_role("button", name="Preencher com áudio", exact=True)
            ).to_be_visible()
            session = next(iter(manager.sessions.values()))
            manager.close(session, expired=True)
            await session.close_task
            del manager.sessions[session.id]
            restart = page.get_by_role("button", name="Iniciar nova sessão", exact=True)
            await expect(restart).to_be_visible(timeout=15000)
            await expect(page.get_by_role("alert")).to_contain_text("Sua sessão expirou")
            await expect(
                page.get_by_role("button", name="Preencher com áudio", exact=True)
            ).to_have_count(0)
            await restart.click()
            await expect(
                page.get_by_role("button", name="Preencher com áudio", exact=True)
            ).to_be_visible(timeout=15000)
            assert len(manager.sessions) == 1 and session.id not in manager.sessions
        finally:
            await browser.close()


async def test_temporary_recovery_failure_reconnects_to_same_session(web_runtime):
    manager, url = web_runtime
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            attempts = 0

            async def unavailable_once(route):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    await route.fulfill(status=503, json={"detail": "Temporariamente indisponível"})
                else:
                    await route.continue_()

            await page.route("**/api/sessions/*", unavailable_once)
            reconnected = await interrupt_first_stream(page, manager)
            await page.goto(url)
            await asyncio.wait_for(reconnected.wait(), timeout=15)
            session = next(iter(manager.sessions.values()))
            session.notify("Conexão recuperada na mesma sessão.")
            await expect(page.get_by_text("Conexão recuperada na mesma sessão.")).to_be_visible()
            await expect(page.get_by_role("button", name="Iniciar nova sessão")).to_have_count(0)
            assert attempts >= 2 and len(manager.sessions) == 1
        finally:
            await browser.close()


async def test_microphone_can_cancel_record_preview_and_send_initial_and_correction_audio(
    web_runtime,
):
    manager, url = web_runtime
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        try:
            context = await browser.new_context(viewport={"width": 390, "height": 844})
            await context.add_init_script("""
                window.recordedStreams = [];
                const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                navigator.mediaDevices.getUserMedia = async (...args) => {
                    const stream = await getUserMedia(...args);
                    window.recordedStreams.push(stream);
                    return stream;
                };
            """)
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(url)
            microphone = page.get_by_role("button", name="Usar microfone", exact=True)
            await microphone.click()
            await expect(page.get_by_role("button", name="Parar gravação")).to_be_visible()
            await expect(page.locator("#audio-file")).to_be_disabled()
            await page.get_by_role("button", name="Cancelar gravação").click()
            await expect(microphone).to_be_visible()
            assert await page.locator(".upload audio").count() == 0
            assert await page.evaluate(
                "window.recordedStreams.every(s => s.getTracks().every(t => t.readyState === 'ended'))"
            )

            async def record():
                await microphone.click()
                await expect(page.locator(".recorder-status")).to_contain_text("00:01")
                await page.get_by_role("button", name="Parar gravação").click()
                await expect(page.locator(".upload audio")).to_be_visible()
                await page.wait_for_function("document.querySelector('.upload audio').duration > 0")
                assert await page.evaluate(
                    "window.recordedStreams.every(s => s.getTracks().every(t => t.readyState === 'ended'))"
                )

            await record()
            assert not any(s.result for s in manager.sessions.values())
            async with page.expect_response(
                lambda response: (
                    response.url.endswith("/audio") and response.request.method == "POST"
                )
            ) as uploaded:
                await page.get_by_role("button", name="Preencher com áudio", exact=True).click()
            assert (await uploaded.value).status == 202
            await expect(page.get_by_label("Nome completo")).to_have_value("Ana")
            await page.get_by_label("Peça uma correção por texto").fill(
                "Corrija minha cidade para Quixadá"
            )
            await page.get_by_role("button", name="Enviar mensagem", exact=True).click()
            await expect(page.get_by_label("Cidade", exact=True)).to_have_value("Quixadá")
            await record()
            await page.get_by_role("button", name="Enviar áudio de correção", exact=True).click()
            await expect(page.get_by_label("Cidade", exact=True)).to_have_value("Sobral")
            await expect(page.get_by_label("Nome completo")).to_have_value("Ana")
            await expect(page.locator("#audio-file")).to_be_enabled()
            assert len(manager.sessions) == 1
            assert len(next(iter(manager.sessions.values())).transcriptions) == 2
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors
            screenshots = PROJECT_ROOT / "reports/web-ui"
            screenshots.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshots / "microphone-mobile.png"), full_page=True)
            await microphone.click()
            await expect(page.get_by_role("button", name="Parar gravação")).to_be_visible()
            session = next(iter(manager.sessions.values()))
            manager.close(session, expired=True)
            await expect(page.get_by_role("button", name="Iniciar nova sessão")).to_be_visible()
            assert await page.evaluate(
                "window.recordedStreams.every(s => s.getTracks().every(t => t.readyState === 'ended'))"
            )
        finally:
            await browser.close()


async def test_cancelled_permission_request_does_not_leave_microphone_active(web_runtime):
    _, url = web_runtime
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        try:
            page = await browser.new_page()
            await page.add_init_script("""
                const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                navigator.mediaDevices.getUserMedia = () => new Promise(resolve => {
                    window.allowMicrophone = async () => {
                        window.lateStream = await getUserMedia({audio: true});
                        resolve(window.lateStream);
                    };
                });
            """)
            await page.goto(url)
            await page.get_by_role("button", name="Usar microfone", exact=True).click()
            await expect(page.locator(".recorder-status")).to_contain_text("Aguardando acesso")
            await page.get_by_role("button", name="Cancelar gravação").click()
            await page.evaluate("window.allowMicrophone()")
            await page.wait_for_function(
                "window.lateStream.getTracks().every(t => t.readyState === 'ended')"
            )
            await expect(
                page.get_by_role("button", name="Usar microfone", exact=True)
            ).to_be_enabled()
            assert await page.locator(".upload audio").count() == 0
        finally:
            await browser.close()


async def test_denied_microphone_keeps_file_upload_available(web_runtime):
    _, url = web_runtime
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script("""
                navigator.mediaDevices.getUserMedia = async () => {
                    throw new DOMException('Denied by test', 'NotAllowedError');
                };
            """)
            await page.goto(url)
            microphone = page.get_by_role("button", name="Usar microfone", exact=True)
            await microphone.click()
            await expect(page.get_by_role("alert")).to_contain_text("Permita o acesso ao microfone")
            await expect(microphone).to_be_enabled()
            await expect(page.locator("#audio-file")).to_be_enabled()
            audio = io.BytesIO()
            with wave.open(audio, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b"\0\0" * 1600)
            await page.locator("#audio-file").set_input_files(
                {"name": "arquivo.wav", "mimeType": "audio/wav", "buffer": audio.getvalue()}
            )
            await page.get_by_role("button", name="Preencher com áudio", exact=True).click()
            await expect(page.get_by_label("Nome completo")).to_have_value("Ana")
        finally:
            await browser.close()


@pytest.mark.parametrize("byte_limit", [26214400, 1])
async def test_microphone_respects_limits_without_automatically_uploading(web_runtime, byte_limit):
    manager, url = web_runtime
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.route(
                "**/api/health",
                lambda route: route.fulfill(
                    json={
                        "max_upload_bytes": byte_limit,
                        "max_audio_seconds": 1.5,
                    }
                ),
            )
            await page.goto(url)
            await page.get_by_role("button", name="Usar microfone", exact=True).click()
            if byte_limit == 1:
                await expect(page.get_by_role("alert")).to_contain_text("tamanho permitido")
                await expect(
                    page.get_by_role("button", name="Usar microfone", exact=True)
                ).to_be_enabled()
                assert await page.locator(".upload audio").count() == 0
                assert next(iter(manager.sessions.values())).state == "ready"
                return
            await expect(page.locator(".upload audio")).to_be_visible()
            await expect(
                page.get_by_role("button", name="Usar microfone", exact=True)
            ).to_be_enabled()
            await expect(
                page.get_by_role("button", name="Preencher com áudio", exact=True)
            ).to_be_enabled()
            assert next(iter(manager.sessions.values())).state == "ready"
            await page.get_by_role("button", name="Preencher com áudio", exact=True).click()
            await expect(page.get_by_label("Nome completo")).to_have_value("Ana")
        finally:
            await browser.close()


async def test_browser_upload_correct_confirm_and_close(tmp_path):
    if not (PROJECT_ROOT / "frontend/dist/index.html").is_file():
        pytest.skip("Execute npm run build em frontend/ antes do teste web completo.")

    def factory(events, browser):
        client = BrowserToolsClient(browser_config=browser)
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
                await expect(page.get_by_role("button", name="Usar microfone")).to_be_visible()
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
