"""Session-owned browser actors, shared serial STT and bounded event history."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import shutil
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from audio_agent.agent import AudioAgent
from audio_agent.engines import FasterWhisperSpeechToTextEngine
from audio_agent.models import TranscriptionResult, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.bootstrap import Application, create_application
from form_agent.config import BrowserConfig, load_model_config
from form_agent.confirmation import submit_confirmed
from form_agent.core.agent import submission_denied
from form_agent.core.events import EventSink
from form_agent.core.interfaces import ToolClient
from form_agent.core.schemas import FormInspection, JsonObject, ToolDefinition
from form_agent.experiments import RunTrace, metadata
from voice_form.clarification import ClarificationSession
from voice_form.interaction import ReviewInput
from voice_form.pipeline import AudioFormPipeline, PipelineResult
from voice_form.review import ReviewSession
from voice_form.service import apply_review, submission_block

from .config import WebConfig, asset
from .extension import ExtensionToolsClient
from .forms import FormTarget, resolve_target

LOGGER = logging.getLogger(__name__)
TERMINAL = {"closed", "expired"}
IDLE = {"ready", "reviewing", "awaiting_answer", "review_complete", "sent", "error"}


class SessionError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class GuardedTools:
    """Stop issuing browser operations after cooperative shutdown is requested."""

    def __init__(self, tools: ToolClient, session: Session) -> None:
        self.tools, self.session = tools, session

    def check(self) -> None:
        if self.session.closing:
            raise SessionError("Sessão encerrando.")

    async def list_tools(self) -> list[ToolDefinition]:
        self.check()
        return await self.tools.list_tools()

    async def inspect_form(self) -> FormInspection:
        self.check()
        return await self.tools.inspect_form()

    async def call_tool(self, name: str, arguments: JsonObject | None = None) -> JsonObject:
        self.check()
        return await self.tools.call_tool(name, arguments)

    async def close(self) -> None:
        await self.tools.close()


class SessionAudio(AudioAgent):
    """One shared model, one inference at a time, including review audio."""

    def __init__(self, manager: SessionManager, session: Session) -> None:
        self.manager, self.session = manager, session

    def transcribe(self, path: Path, settings: TranscriptionSettings) -> TranscriptionResult:
        with self.manager.speech_lock:
            if self.session.closing:
                raise SessionError("Sessão encerrando.")
            self.session.loop.call_soon_threadsafe(self.session.set_state, "transcribing")
            result = self.manager.audio.transcribe(path, settings)
            if self.session.closing:
                raise SessionError("Sessão encerrando.")
            return result


class Session:
    def __init__(
        self,
        manager: SessionManager,
        owner: str,
        target: FormTarget | None = None,
        bridge: ExtensionToolsClient | None = None,
    ) -> None:
        self.manager, self.owner = manager, owner
        self.bridge = bridge
        self.target = target or resolve_target()
        self.settings = (
            manager.config.settings
            if self.target.browser.url == asset("form.html").as_uri()
            else replace(manager.config.settings, initial_prompt=None, hotwords=None)
        )
        self.id = uuid4().hex
        self.loop = asyncio.get_running_loop()
        self.directory = manager.config.data_dir / "uploads" / self.id
        self.directory.mkdir(parents=True, mode=0o700)
        self.application: Application | None = None
        self.trace: RunTrace | None = None
        self.result: PipelineResult | None = None
        self.inspection: FormInspection | None = None
        self.issues: list[dict[str, Any]] = []
        self.messages: deque[dict[str, str]] = deque(maxlen=100)
        self.transcriptions: deque[dict[str, str]] = deque(maxlen=50)
        self.corrections: deque[dict[str, Any]] = deque(maxlen=100)
        self.events: deque[dict[str, Any]] = deque(maxlen=manager.config.event_buffer)
        self.inputs: asyncio.Queue[ReviewInput] = asyncio.Queue(maxsize=1)
        self.changed = asyncio.Event()
        self.state = "preparing"
        self.sequence = self.revision = 0
        self.question = ""
        self.phase = ""
        self.waiting = False
        self.denied = False
        self.closing = False
        self.submit_attempted = False
        self.interrupted = False
        self.active_field = ""
        self.last_active = self.operation_started = time.monotonic()
        self.task: asyncio.Task[None] | None = None
        self.close_task: asyncio.Task[None] | None = None
        self.audio = SessionAudio(manager, self)

    def public(self) -> dict[str, Any]:
        fields = []
        if self.inspection:
            fields = [{**f.to_dict(), "reference": f.reference} for f in self.inspection.fields]
        blocked = self.question or any(i["code"] != "SUBMISSION_BLOCKED" for i in self.issues)
        return {
            "id": self.id,
            "transport": "extension" if self.bridge else "web",
            "state": self.state,
            "revision": self.revision,
            "sequence": self.sequence,
            "form_name": self.target.name,
            "form_url": self.target.public_url,
            "is_demo": self.target.demo,
            "submission_supported": self.target.demo,
            "fields": fields,
            "issues": [
                {**i, "message": self.public_text(str(i.get("message", "")))} for i in self.issues
            ],
            "question": self.question,
            "messages": list(self.messages),
            "transcriptions": list(self.transcriptions),
            "corrections": list(self.corrections),
            "phase": self.phase,
            "active_field": self.active_field,
            "can_message": self.waiting and not self.closing,
            "can_correct_audio": self.waiting and self.phase == "review" and not self.closing,
            "can_complete": self.waiting and self.phase == "review" and not blocked,
            "can_submit": self.state == "review_complete"
            and self.target.demo
            and not blocked
            and not self.denied
            and not self.submit_attempted,
            "submission_denied": self.denied,
        }

    def publish(self, kind: str = "state") -> None:
        self.sequence += 1
        self.events.append(
            {
                "id": self.sequence,
                "session_id": self.id,
                "timestamp": datetime.now(UTC).isoformat(),
                "type": kind,
                "state": self.public(),
            }
        )
        self.changed.set()

    def set_state(self, state: str) -> None:
        if self.closing and state not in {"closing", *TERMINAL}:
            return
        if state in IDLE and state != self.state:
            self.last_active = time.monotonic()
        self.state = state
        self.publish()

    def notify(self, text: str, who: str = "system") -> None:
        if not text:
            return
        if who == "system":
            text = self.public_text(text)
            if text.startswith("Revisão aberta."):
                text = "Peça uma correção por texto ou envie outro áudio. Use os botões para concluir a revisão ou descartar um pedido."
        self.messages.append({"who": who, "text": text, "time": datetime.now(UTC).isoformat()})
        self.publish("message")

    def public_text(self, text: str) -> str:
        return (
            text.replace(str(self.directory), "[áudio enviado]")
            .replace(self.target.browser.url, self.target.public_url)
            .replace(str(asset("form.html")), "[formulário de cadastro]")
            .replace(" ou digite PULAR ou ENCERRAR", " ou use os controles da sessão")
            .replace(
                "Digite o número ou identificador, PULAR ou ENCERRAR: ",
                "Responda com o número ou identificador do campo: ",
            )
        )

    def snapshot(self, value: FormInspection) -> None:
        if value != self.inspection:
            self.revision += 1
        self.inspection = value

    def emit(self, name: str, data: Mapping[str, object]) -> None:
        """Called on the actor's loop; raw paths/provider details stay in private traces."""
        if self.trace:
            self.trace.emit(name, data)
        if self.closing:
            return
        inspection = data.get("final_inspection")
        if name == "form_inspected":
            inspection = data
        if isinstance(inspection, dict):
            self.snapshot(FormInspection.from_mapping(inspection))
        states = {
            "audio_started": "queued",
            "review_audio_started": "queued",
            "form_started": "filling",
            "field_verified": "verifying",
            "review_proposed": "correcting",
            "clarification_question": "awaiting_answer",
        }
        if name in states:
            self.state = states[name]
        if name in {"audio_transcribed", "review_audio_transcribed"}:
            self.transcriptions.append(
                {
                    "kind": "initial" if name == "audio_transcribed" else "correction",
                    "text": str(data.get("text", "")),
                }
            )
        if name == "fill_field_completed" and self.inspection:
            output = data.get("output")
            if isinstance(output, dict) and output.get("success") is True:
                ref = output.get("field_ref") or output.get("field")
                self.active_field = str(ref or "")
                self.snapshot(
                    replace(
                        self.inspection,
                        fields=tuple(
                            replace(
                                f,
                                value=output.get("value"),
                                valid=output.get("valid"),
                                validation_message=str(output.get("validation_message") or ""),
                            )
                            if ref == f.reference
                            else f
                            for f in self.inspection.fields
                        ),
                    )
                )
        if name in {"review_question", "clarification_question"}:
            self.question = str(data.get("question", ""))
            self.notify(self.question)
        if name == "review_waiting":
            self.active_field = ""
            raw_issues = data.get("issues")
            self.issues = list(raw_issues) if isinstance(raw_issues, list) else []
            self.question = str(data.get("question", ""))
        if name == "review_record":
            record = {k: v for k, v in data.items() if k != "audio_file"}
            if record.get("reason"):
                record["reason"] = "Confira os dados e a mensagem de validação do campo."
            self.corrections.append(record)
        self.publish(name)

    async def ask_review(self, prompt: str) -> ReviewInput:
        self.phase = "review"
        return await self._answer()

    async def ask_clarification(self, prompt: str) -> str:
        self.phase = "clarification"
        entry = await self._answer()
        return {"skip": "PULAR", "close": "ENCERRAR"}.get(entry.kind, entry.text)

    async def _answer(self) -> ReviewInput:
        if self.closing:
            return ReviewInput("close")
        self.waiting = True
        self.set_state("awaiting_answer" if self.question else "reviewing")
        entry = await self.inputs.get()
        self.waiting = False
        self.operation_started = time.monotonic()
        self.set_state("correcting")
        return entry

    def deliver(self, entry: ReviewInput) -> None:
        if not self.waiting or self.closing:
            raise SessionError("Aguarde a operação atual terminar.")
        if entry.kind == "complete" and not self.public()["can_complete"]:
            raise SessionError("Responda à pergunta ou resolva as pendências antes de concluir.")
        self.waiting = False
        self.last_active = self.operation_started = time.monotonic()
        if entry.kind == "text":
            self.notify(entry.text, "user")
        self.inputs.put_nowait(entry)
        self.set_state("correcting")

    async def open(self) -> None:
        try:
            app = self.manager.factory(self.emit, self.target.browser)
            self.application = app
            if self.bridge:
                await app.client.close()
                app.client = self.bridge
                app.agent.tools = self.bridge
            app.agent.tools = GuardedTools(app.agent.tools, self)
            self.trace = RunTrace(
                self.manager.config.data_dir / "runs",
                {
                    **metadata(
                        model=app.config,
                        browser=self.target.browser,
                        stt_settings=self.settings.to_dict(),
                    ),
                    "entrypoint": "web-v1",
                    "web_target": {
                        "url": self.target.public_url,
                        "name": self.target.name,
                        "is_demo": self.target.demo,
                    },
                },
                run_id=self.id,
                data_directory=self.manager.config.data_dir / "sessions",
            )
            inventory = await app.agent.tools.inspect_form()
            if not inventory.fields:
                raise SessionError("Nenhum campo foi encontrado nesse formulário.")
            if len({field.reference for field in inventory.fields}) != len(inventory.fields):
                raise SessionError(
                    "O formulário possui campos com referências repetidas. Use campos com identificadores únicos."
                )
            supported = {
                "text",
                "search",
                "email",
                "tel",
                "date",
                "number",
                "url",
                "textarea",
                "select",
                "checkbox",
                "radio",
                "time",
                "datetime-local",
                "month",
                "week",
            }
            if any(
                field.type not in supported and not field.disabled for field in inventory.fields
            ):
                raise SessionError(
                    "Esse formulário contém controles ainda não suportados, como senha ou envio de arquivos. Use um formulário com campos HTML comuns."
                )
            self.snapshot(inventory)
            if self.closing:
                return
            self.set_state("ready")
            self.notify(
                "Consulte os campos e grave pelo microfone ou envie um arquivo de áudio para preencher."
            )
        except Exception as exc:
            LOGGER.exception("Falha ao abrir sessão %s", self.id)
            self.set_state("error")
            self.notify(
                str(exc)
                if isinstance(exc, SessionError)
                else "Não foi possível ler a aba. Abra o painel da extensão e selecione um formulário HTML comum."
                if self.bridge
                else "Não foi possível preparar o formulário. Confira a URL e a configuração do servidor. Use uma página com um único formulário HTML, sem login ou redirecionamento."
            )

    async def fill(self, path: Path) -> None:
        app = self.application
        assert app is not None
        try:
            pipeline = AudioFormPipeline(
                self.audio,
                app.agent,
                events=self.emit,
                clarification=ClarificationSession(
                    self.ask_clarification, notify=self.notify, events=self.emit
                ),
            )
            result = await pipeline.run(path, self.settings, data_treatment="rules")
            self.result = result
            self.issues = [asdict(i) for i in result.issues]
            if self.closing:
                return
            if not result.form or not result.form.verification_complete:
                self.set_state("error")
                self.notify(
                    "Não foi possível concluir o preenchimento com estado verificável. Encerre e inicie outra sessão."
                )
                return
            self.denied = bool(
                result.transcription and submission_denied(result.transcription.text)
            )
            self.snapshot(result.form.final_inspection or result.form.inspection)
            self.notify("Preenchimento conferido. Revise os dados ou peça uma correção.")
            reviewed = await ReviewSession(
                app.agent.tools,
                app.model,
                self.audio,
                self.settings,
                ask=self.ask_review,
                notify=self.notify,
                events=self.emit,
            ).run(
                result.form,
                result.issues,
                normalization=result.normalization,
                extraction=result.extraction,
                denied=self.denied,
            )
            self.result = apply_review(result, reviewed)
            self.denied = reviewed.submission_denied
            self.issues = [asdict(i) for i in reviewed.issues]
            if self.closing:
                return
            if reviewed.completed:
                self.question = ""
                self.set_state("review_complete")
                self.notify(
                    "Revisão concluída. O envio simulado exige sua confirmação separada."
                    if self.target.demo
                    else "Revisão concluída. O envio automático não está habilitado para este endereço."
                )
            else:
                self.set_state("error")
                self.notify("A revisão foi interrompida. O envio está bloqueado.")
            self.emit("run_completed", self.result.to_dict())
        except Exception:
            LOGGER.exception("Falha na operação da sessão %s", self.id)
            self.set_state("error")
            self.notify("O processamento falhou. Encerre a sessão e tente novamente.")

    async def submit(self) -> None:
        assert self.application and self.result and self.result.form
        try:
            output = await submit_confirmed(self.application, self.result.form)
            self.result = replace(
                self.result,
                form=replace(
                    self.result.form,
                    submitted=output.get("submitted") is True,
                    submission_attempted=True,
                    verification_complete=output.get("submitted") is True,
                ),
            )
            self.emit("human_submission", output)
            self.emit(
                "form_completed",
                {
                    "final_inspection": self.inspection.to_dict() if self.inspection else None,
                    "submitted": output.get("submitted") is True,
                    "verification_complete": output.get("submitted") is True,
                },
            )
            if output.get("submitted") is True:
                self.set_state("sent")
                self.notify("Envio simulado confirmado pelo formulário.")
            else:
                self.set_state("error")
                self.notify("Envio não confirmado. A operação não será repetida automaticamente.")
            self.emit("run_completed", {**self.result.to_dict(), "human_submission": output})
        except Exception:
            LOGGER.exception("Falha no envio da sessão %s", self.id)
            self.set_state("error")
            self.notify("O resultado do envio é incerto; não repita a operação.")

    async def stream(self, after: int) -> AsyncIterator[str]:
        while True:
            self.changed.clear()
            pending = [e for e in self.events if e["id"] > after]
            if not pending or (self.events and after < self.events[0]["id"] - 1):
                pending = [{"id": self.sequence, "type": "snapshot", "state": self.public()}]
            for event in pending:
                after = event["id"]
                yield f"id: {after}\nevent: session\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if self.state in TERMINAL:
                return
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=15)
            except TimeoutError:
                yield ": heartbeat\n\n"


class SessionManager:
    def __init__(
        self,
        config: WebConfig,
        *,
        factory: Callable[[EventSink, BrowserConfig], Application] | None = None,
        audio: AudioAgent | None = None,
    ) -> None:
        self.config = config
        self.factory = factory or self._application
        self.audio = audio or AudioAgent(AudioPreprocessor(), FasterWhisperSpeechToTextEngine())
        self.speech_lock = threading.Lock()
        self.sessions: dict[str, Session] = {}
        self.reaper: asyncio.Task[None] | None = None

    @staticmethod
    def _application(events: EventSink, browser: BrowserConfig) -> Application:
        return create_application(
            events=events,
            browser_config=browser,
            model_config=load_model_config(
                profiles_file=Path(
                    os.getenv("MODEL_PROFILES_FILE", str(asset("model-profiles.json")))
                )
            ),
        )

    def create(
        self,
        owner: str,
        target: FormTarget | None = None,
        *,
        bridge: ExtensionToolsClient | None = None,
    ) -> Session:
        active = sum(s.state not in TERMINAL for s in self.sessions.values())
        if active >= self.config.max_sessions:
            raise SessionError("Servidor ocupado. Aguarde o encerramento da sessão ativa.", 503)
        session = Session(self, owner, target, bridge)
        self.sessions[session.id] = session
        session.task = asyncio.create_task(session.open())
        return session

    def get(self, session_id: str, owner: str) -> Session:
        session = self.sessions.get(session_id)
        if session is None or not owner or not secrets.compare_digest(session.owner, owner):
            raise SessionError("Sessão não encontrada ou expirada.", 404)
        return session

    def start_fill(self, session: Session, path: Path) -> None:
        if session.closing:
            raise SessionError("Sessão encerrando.")
        session.operation_started = time.monotonic()
        session.set_state("queued")
        session.task = asyncio.create_task(session.fill(path))

    def start_submit(self, session: Session, revision: int) -> None:
        if (
            not session.public()["can_submit"]
            or revision != session.revision
            or session.result is None
            or submission_block(session.result, session.denied)
        ):
            raise SessionError("Envio bloqueado: confirme uma revisão válida e atual.")
        session.submit_attempted = True
        session.operation_started = time.monotonic()
        session.set_state("sending")
        session.task = asyncio.create_task(session.submit())

    def close(self, session: Session, *, expired: bool = False) -> None:
        if session.close_task or session.state in TERMINAL:
            return
        session.interrupted = session.state not in IDLE
        session.closing = True
        if session.bridge:
            session.bridge.abort()
        session.set_state("closing")
        session.waiting = False
        if session.inputs.empty():
            session.inputs.put_nowait(ReviewInput("close"))
        session.close_task = asyncio.create_task(self._close(session, expired))

    async def _close(self, session: Session, expired: bool) -> None:
        if session.task:
            with contextlib.suppress(Exception):
                await asyncio.shield(session.task)
        if session.application:
            await session.application.close()
        if session.trace:
            if session.result:
                session.trace.emit("run_completed", session.result.to_dict())
            if session.interrupted:
                session.trace.emit("run_interrupted", {"error_type": "SessionClosed"})
            session.trace.__exit__(None, None, None)
        await asyncio.to_thread(shutil.rmtree, session.directory, True)
        session.set_state("expired" if expired else "closed")
        last = session.events[-1]
        session.events.clear()
        session.events.append(last)
        session.last_active = time.monotonic()

    async def reap(self) -> None:
        while True:
            await asyncio.sleep(min(5, self.config.idle_seconds))
            now = time.monotonic()
            for s in list(self.sessions.values()):
                if s.state in TERMINAL:
                    if now - s.last_active > self.config.idle_seconds:
                        del self.sessions[s.id]
                    continue
                if s.closing:
                    continue
                if (s.state in IDLE and now - s.last_active > self.config.idle_seconds) or (
                    s.state not in IDLE
                    and now - s.operation_started > self.config.operation_seconds
                ):
                    self.close(s, expired=True)

    async def shutdown(self) -> None:
        if self.reaper:
            self.reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reaper
        for s in self.sessions.values():
            self.close(s)
        await asyncio.gather(*(s.close_task for s in self.sessions.values() if s.close_task))
