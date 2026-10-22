"""HTTP commands and reconnectable events for the standard form."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import secrets
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from audio_agent.preprocessing import SUPPORTED_AUDIO_FORMATS
from voice_form.interaction import ReviewInput

from .config import WebConfig
from .schemas import SubmitInput, TextInput
from .sessions import Session, SessionError, SessionManager
from .uploads import validate_audio

COOKIE = "form_session_owner"


class RequestLimits:
    def __init__(self, app: ASGIApp, config: WebConfig) -> None:
        self.app, self.config = app, config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get(b"origin", b"").decode()
            allowed = (
                self.config.public_origin
                or f"{scope['scheme']}://{headers.get(b'host', b'').decode()}"
            )
            if (origin and origin != allowed) or headers.get(b"sec-fetch-site") == b"cross-site":
                await JSONResponse({"detail": "Origem da requisição não permitida."}, 403)(
                    scope, receive, send
                )
                return
        limit = self.config.max_upload_bytes + 65536
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = limit + 1
        if declared > limit:
            await JSONResponse({"detail": "Arquivo excede o limite de upload."}, 413)(
                scope, receive, send
            )
            return
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(413, "Arquivo excede o limite de upload.")
            return message

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        await self.app(scope, bounded_receive, private_send)


def create_app(
    config: WebConfig | None = None, *, manager: SessionManager | None = None
) -> FastAPI:
    config = config or WebConfig.from_env()
    manager = manager or SessionManager(config)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        manager.reaper = asyncio.create_task(manager.reap())
        try:
            yield
        finally:
            await manager.shutdown()

    app = FastAPI(title="Formulários por áudio", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.manager = manager
    app.add_middleware(RequestLimits, config=config)

    @app.exception_handler(SessionError)
    async def session_error(request: Request, exc: SessionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    def owned(request: Request, session_id: str) -> Session:
        return manager.get(session_id, request.cookies.get(COOKIE, ""))

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "max_upload_bytes": config.max_upload_bytes,
            "max_audio_seconds": config.max_audio_seconds,
        }

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: Request) -> JSONResponse:
        owner = request.cookies.get(COOKIE) or secrets.token_urlsafe(32)
        session = manager.create(owner)
        response = JSONResponse(session.public(), status_code=201)
        response.set_cookie(
            COOKIE,
            owner,
            httponly=True,
            secure=config.cookie_secure,
            samesite="strict",
            max_age=86400,
        )
        return response

    @app.get("/api/session")
    async def current_session(request: Request) -> dict[str, object]:
        owner = request.cookies.get(COOKIE, "")
        for session in reversed(list(manager.sessions.values())):
            if (
                owner
                and secrets.compare_digest(session.owner, owner)
                and session.state not in {"closed", "expired"}
            ):
                return session.public()
        raise SessionError("Nenhuma sessão ativa.", 404)

    @app.get("/api/sessions/{session_id}")
    async def get_session(request: Request, session_id: str) -> dict[str, object]:
        session = owned(request, session_id)
        session.last_active = time.monotonic()
        return session.public()

    @app.get("/api/sessions/{session_id}/events")
    async def events(request: Request, session_id: str) -> StreamingResponse:
        session = owned(request, session_id)
        try:
            after = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            after = 0
        if after > session.sequence:
            after = 0
        return StreamingResponse(
            session.stream(after),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    async def upload(session: Session, file: UploadFile, correction: bool) -> JSONResponse:
        if session.closing or (not correction and session.state != "ready"):
            raise SessionError("O formulário não está pronto para receber este áudio.")
        if correction and not session.public()["can_correct_audio"]:
            raise SessionError("Aguarde a revisão para enviar um áudio de correção.")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_AUDIO_FORMATS:
            raise SessionError("Use um arquivo WAV, MP3, MP4, M4A ou FLAC.", 415)
        old_state = session.state
        session.waiting = False
        session.last_active = session.operation_started = time.monotonic()
        session.set_state("validating")
        path = session.directory / f"{uuid4().hex}{suffix}"
        try:
            size = 0
            digest = hashlib.sha256()
            with path.open("xb") as output:
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > config.max_upload_bytes:
                        raise SessionError("Arquivo excede o limite de upload.", 413)
                    digest.update(chunk)
                    output.write(chunk)
            if not size:
                raise SessionError("O arquivo está vazio.", 422)
            try:
                await asyncio.to_thread(validate_audio, path, config.max_audio_seconds)
            except ValueError as exc:
                raise SessionError(str(exc), 422) from exc
            if session.closing:
                raise SessionError("Sessão encerrando.")
            session.emit(
                "web_upload_received",
                {
                    "sha256": digest.hexdigest(),
                    "size_bytes": size,
                    "kind": "correction" if correction else "initial",
                },
            )
            session.notify(
                "Áudio de correção enviado." if correction else "Áudio enviado para preenchimento.",
                "user",
            )
            if correction:
                session.waiting = True
                session.deliver(ReviewInput("audio", audio_path=path))
            else:
                manager.start_fill(session, path)
        except Exception:
            path.unlink(missing_ok=True)
            if not session.closing:
                session.waiting = correction
                session.set_state(old_state)
            raise
        finally:
            await file.close()
        return JSONResponse(session.public(), status_code=202)

    @app.post("/api/sessions/{session_id}/audio", status_code=202)
    async def initial_audio(
        request: Request, session_id: str, file: Annotated[UploadFile, File()]
    ) -> JSONResponse:
        return await upload(owned(request, session_id), file, False)

    @app.post("/api/sessions/{session_id}/corrections/audio", status_code=202)
    async def correction_audio(
        request: Request, session_id: str, file: Annotated[UploadFile, File()]
    ) -> JSONResponse:
        return await upload(owned(request, session_id), file, True)

    @app.post("/api/sessions/{session_id}/messages", status_code=202)
    async def message(request: Request, session_id: str, body: TextInput) -> dict[str, object]:
        session = owned(request, session_id)
        text = body.text.strip()
        if not text:
            raise SessionError("Digite uma mensagem.", 422)
        session.deliver(ReviewInput("text", text))
        return session.public()

    @app.post("/api/sessions/{session_id}/review/skip", status_code=202)
    async def skip(request: Request, session_id: str) -> dict[str, object]:
        session = owned(request, session_id)
        session.deliver(ReviewInput("skip"))
        return session.public()

    @app.post("/api/sessions/{session_id}/review/complete", status_code=202)
    async def complete(request: Request, session_id: str) -> dict[str, object]:
        session = owned(request, session_id)
        session.deliver(ReviewInput("complete"))
        return session.public()

    @app.post("/api/sessions/{session_id}/submit", status_code=202)
    async def submit(request: Request, session_id: str, body: SubmitInput) -> dict[str, object]:
        session = owned(request, session_id)
        manager.start_submit(session, body.revision)
        return session.public()

    @app.delete("/api/sessions/{session_id}", status_code=202)
    async def close(request: Request, session_id: str) -> dict[str, object]:
        session = owned(request, session_id)
        manager.close(session)
        return session.public()

    if config.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=config.frontend_dir, html=True), name="frontend")
    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        "web_api.app:create_app",
        factory=True,
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("WEB_PORT", "8000")),
        workers=1,
        timeout_graceful_shutdown=30,
    )
