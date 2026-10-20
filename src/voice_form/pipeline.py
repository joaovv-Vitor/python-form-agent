"""A small application service; neither component knows the other's infrastructure."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from audio_agent.agent import AudioAgent
from audio_agent.exceptions import AudioAgentError
from audio_agent.models import TranscriptionResult, TranscriptionSettings
from form_agent.core.agent import FormAgent, submission_denied
from form_agent.core.errors import (
    ConfigurationError,
    FormAgentError,
    ModelResponseError,
    error_code,
)
from form_agent.core.events import EventSink, discard_event
from form_agent.core.schemas import AgentResult, RunIssue

from .clarification import ClarificationRecord, ClarificationSession
from .context import contextualize
from .extraction import DataExtractor, ExtractionResponseError, ExtractionResult
from .normalization import NormalizationResult, normalize_spoken_data

type DataTreatment = Literal["raw", "rules", "deepseek"]


def treatment_name(
    normalize_data: bool = True, data_treatment: DataTreatment | None = None
) -> DataTreatment:
    return data_treatment if data_treatment is not None else "rules" if normalize_data else "raw"


@dataclass(frozen=True, slots=True)
class PipelineResult:
    transcription: TranscriptionResult | None
    form: AgentResult | None
    issues: tuple[RunIssue, ...]
    total_seconds: float
    form_seconds: float = 0.0
    normalization: NormalizationResult | None = None
    normalization_seconds: float = 0.0
    extraction: ExtractionResult | None = None
    extraction_seconds: float = 0.0
    data_treatment: DataTreatment = "raw"
    post_stt_seconds: float = 0.0
    clarifications: tuple[ClarificationRecord, ...] = ()
    clarification_seconds: float = 0.0
    initial_issues: tuple[RunIssue, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "transcription": self.transcription.to_dict() if self.transcription else None,
            "form": asdict(self.form) if self.form else None,
            "issues": [asdict(issue) for issue in self.issues],
            "total_seconds": self.total_seconds,
            "form_seconds": self.form_seconds,
            "normalization": self.normalization.to_dict() if self.normalization else None,
            "normalization_seconds": self.normalization_seconds,
            "extraction": self.extraction.to_dict() if self.extraction else None,
            "extraction_seconds": self.extraction_seconds,
            "data_treatment": self.data_treatment,
            "post_stt_seconds": self.post_stt_seconds,
            "clarifications": [asdict(item) for item in self.clarifications],
            "clarification_seconds": self.clarification_seconds,
            "initial_issues": [asdict(issue) for issue in self.initial_issues],
        }


class AudioFormPipeline:
    def __init__(
        self,
        audio: AudioAgent,
        form: FormAgent,
        *,
        events: EventSink = discard_event,
        extractor: DataExtractor | None = None,
        clarification: ClarificationSession | None = None,
    ) -> None:
        self.audio = audio
        self.form = form
        self.events = events
        self.extractor = extractor
        self.clarification = clarification

    async def run(
        self,
        path: Path,
        settings: TranscriptionSettings,
        *,
        authorize_submission: bool = False,
        normalize_data: bool = True,
        data_treatment: DataTreatment | None = None,
        auto_context: bool = True,
    ) -> PipelineResult:
        started = time.perf_counter()
        try:
            if (
                auto_context
                and path.expanduser().is_file()
                and (settings.initial_prompt is None or settings.hotwords is None)
            ):
                self.events("stt_context_started", {})
                try:
                    inventory = await self.form.tools.inspect_form()
                except FormAgentError as exc:
                    # Context is optional: retain STT even if the browser is unavailable.
                    self.events("stt_context_failed", {"code": error_code(exc), "error": str(exc)})
                else:
                    settings = contextualize(settings, inventory)
                    self.events(
                        "stt_context_created",
                        {"initial_prompt": settings.initial_prompt, "hotwords": settings.hotwords},
                    )
            self.events("audio_started", {"path": str(path), "settings": settings.to_dict()})
            transcription = await asyncio.to_thread(self.audio.transcribe, path, settings)
        except (AudioAgentError, OSError, ValueError) as exc:
            self.events("audio_failed", {"code": "STT_ERROR", "error": str(exc)})
            return PipelineResult(
                None,
                None,
                (RunIssue("STT_ERROR", "stt", str(exc)),),
                time.perf_counter() - started,
                data_treatment=treatment_name(normalize_data, data_treatment),
            )
        result = await self.run_transcription(
            transcription,
            authorize_submission=authorize_submission,
            normalize_data=normalize_data,
            data_treatment=data_treatment,
        )
        return replace(result, total_seconds=time.perf_counter() - started)

    async def run_transcription(
        self,
        transcription: TranscriptionResult,
        *,
        authorize_submission: bool = False,
        normalize_data: bool = True,
        data_treatment: DataTreatment | None = None,
    ) -> PipelineResult:
        """Run one condition on a shared, immutable STT result for paired experiments."""
        started = time.perf_counter()
        condition = treatment_name(normalize_data, data_treatment)
        self.events("audio_transcribed", transcription.to_dict())
        if not transcription.text.strip():
            return PipelineResult(
                transcription,
                None,
                (RunIssue("STT_EMPTY", "stt", "Transcrição vazia; formulário não acionado"),),
                transcription.processing_time_seconds + time.perf_counter() - started,
                data_treatment=condition,
            )
        normalization_started = time.perf_counter()
        normalization = normalize_spoken_data(transcription.text) if condition == "rules" else None
        normalization_seconds = (
            time.perf_counter() - normalization_started if normalization else 0.0
        )
        issues = normalization.issues if normalization else ()
        instruction = normalization.instruction if normalization else transcription.text
        if normalization:
            self.events(
                "data_normalized",
                {
                    **normalization.to_dict(),
                    "processing_seconds": normalization_seconds,
                },
            )
        extraction: ExtractionResult | None = None
        extraction_seconds = 0.0
        if condition == "deepseek":
            extraction_started = time.perf_counter()
            self.events(
                "extraction_started",
                {"version": self.extractor.manifest() if self.extractor else None},
            )
            try:
                if self.extractor is None:
                    raise ConfigurationError("Extrator DeepSeek necessário para esta condição.")
                inventory = await self.form.tools.inspect_form()
                extraction = await self.extractor.extract(transcription.text, inventory)
                extraction_seconds = time.perf_counter() - extraction_started
                issues = extraction.issues
                instruction = extraction.instruction
                self.events(
                    "data_extracted",
                    {**extraction.to_dict(), "processing_seconds": extraction_seconds},
                )
            except FormAgentError as exc:
                extraction_seconds = time.perf_counter() - extraction_started
                code = (
                    "EXTRACTION_ERROR" if isinstance(exc, ModelResponseError) else error_code(exc)
                )
                self.events(
                    "extraction_failed",
                    {
                        "code": code,
                        "error": str(exc),
                        "response_json": exc.response_json
                        if isinstance(exc, ExtractionResponseError)
                        else None,
                    },
                )
                elapsed = time.perf_counter() - started
                return PipelineResult(
                    transcription,
                    None,
                    (RunIssue(code, "extraction", str(exc)),),
                    transcription.processing_time_seconds + elapsed,
                    extraction_seconds=extraction_seconds,
                    data_treatment=condition,
                    post_stt_seconds=elapsed,
                )
        # Treatment must never remove an original veto or allow submission with
        # unresolved values. Authority remains external to both STT and treatment.
        can_submit = (
            authorize_submission
            and self.clarification is None
            and not issues
            and not submission_denied(transcription.text)
        )
        form_started = time.perf_counter()
        try:
            if extraction is not None:
                form = await self.form.run(
                    instruction, authorize_submission=can_submit, field_values=extraction.values
                )
            else:
                form = await self.form.run(instruction, authorize_submission=can_submit)
        except FormAgentError as exc:
            return PipelineResult(
                transcription,
                None,
                (*issues, RunIssue(error_code(exc), "form", str(exc))),
                transcription.processing_time_seconds + time.perf_counter() - started,
                time.perf_counter() - form_started,
                normalization,
                normalization_seconds,
                extraction,
                extraction_seconds,
                condition,
                time.perf_counter() - started,
            )
        form_seconds = time.perf_counter() - form_started
        initial_issues = (*issues, *form.issues)
        final_issues = initial_issues
        clarifications: tuple[ClarificationRecord, ...] = ()
        clarification_seconds = 0.0
        if self.clarification:
            clarification_started = time.perf_counter()
            clarified = await self.clarification.run(
                self.form.tools,
                form,
                initial_issues,
                normalization=normalization,
                extraction=extraction,
            )
            form = clarified.form
            final_issues = clarified.issues
            clarifications = clarified.records
            clarification_seconds = time.perf_counter() - clarification_started
        self.events(
            "pipeline_completed",
            {
                "total_seconds": transcription.processing_time_seconds
                + time.perf_counter()
                - started,
                "post_stt_seconds": time.perf_counter() - started,
                "data_treatment": condition,
            },
        )
        return PipelineResult(
            transcription,
            form,
            final_issues,
            transcription.processing_time_seconds + time.perf_counter() - started,
            form_seconds,
            normalization,
            normalization_seconds,
            extraction,
            extraction_seconds,
            condition,
            time.perf_counter() - started,
            clarifications,
            clarification_seconds,
            initial_issues if self.clarification else (),
        )
