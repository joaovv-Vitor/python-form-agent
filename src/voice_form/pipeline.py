"""A small application service; neither component knows the other's infrastructure."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from audio_agent.agent import AudioAgent
from audio_agent.exceptions import AudioAgentError
from audio_agent.models import TranscriptionResult, TranscriptionSettings
from form_agent.core.agent import FormAgent
from form_agent.core.errors import FormAgentError, error_code
from form_agent.core.events import EventSink, discard_event
from form_agent.core.schemas import AgentResult, RunIssue


@dataclass(frozen=True, slots=True)
class PipelineResult:
    transcription: TranscriptionResult | None
    form: AgentResult | None
    issues: tuple[RunIssue, ...]
    total_seconds: float
    form_seconds: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "transcription": self.transcription.to_dict() if self.transcription else None,
            "form": asdict(self.form) if self.form else None,
            "issues": [asdict(issue) for issue in self.issues],
            "total_seconds": self.total_seconds,
            "form_seconds": self.form_seconds,
        }


class AudioFormPipeline:
    def __init__(
        self, audio: AudioAgent, form: FormAgent, *, events: EventSink = discard_event
    ) -> None:
        self.audio = audio
        self.form = form
        self.events = events

    async def run(
        self,
        path: Path,
        settings: TranscriptionSettings,
        *,
        authorize_submission: bool = False,
    ) -> PipelineResult:
        started = time.perf_counter()
        self.events("audio_started", {"path": str(path), "settings": settings.to_dict()})
        try:
            transcription = await asyncio.to_thread(self.audio.transcribe, path, settings)
        except (AudioAgentError, OSError, ValueError) as exc:
            self.events("audio_failed", {"code": "STT_ERROR", "error": str(exc)})
            return PipelineResult(
                None,
                None,
                (RunIssue("STT_ERROR", "stt", str(exc)),),
                time.perf_counter() - started,
            )
        self.events("audio_transcribed", transcription.to_dict())
        if not transcription.text.strip():
            return PipelineResult(
                transcription,
                None,
                (RunIssue("STT_EMPTY", "stt", "Transcrição vazia; formulário não acionado"),),
                time.perf_counter() - started,
            )
        form_started = time.perf_counter()
        try:
            form = await self.form.run(
                transcription.text,
                authorize_submission=authorize_submission,
            )
        except FormAgentError as exc:
            return PipelineResult(
                transcription,
                None,
                (RunIssue(error_code(exc), "form", str(exc)),),
                time.perf_counter() - started,
                time.perf_counter() - form_started,
            )
        self.events("pipeline_completed", {"total_seconds": time.perf_counter() - started})
        return PipelineResult(
            transcription,
            form,
            form.issues,
            time.perf_counter() - started,
            time.perf_counter() - form_started,
        )
