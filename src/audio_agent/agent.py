"""Application service that coordinates audio preparation and transcription."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from .models import TranscriptionResult, TranscriptionSettings
from .preprocessing import AudioPreprocessor
from .transcriber import SpeechToTextEngine


class AudioAgent:
    """Transcribe a file without depending on a specific STT implementation."""

    def __init__(self, preprocessor: AudioPreprocessor, engine: SpeechToTextEngine) -> None:
        self._preprocessor = preprocessor
        self._engine = engine

    def transcribe(
        self,
        audio_path: Path,
        settings: TranscriptionSettings,
    ) -> TranscriptionResult:
        started = time.perf_counter()
        executed_at = datetime.now(UTC)
        audio = self._preprocessor.prepare(audio_path)
        transcription = self._engine.transcribe(audio, settings)
        elapsed = time.perf_counter() - started
        return TranscriptionResult(
            audio_file=audio.input_path,
            media_format=audio.media_format,
            size_bytes=audio.size_bytes,
            engine=transcription.engine,
            engine_version=transcription.engine_version,
            model=settings.model,
            configured_language=settings.language,
            language=transcription.language,
            language_probability=transcription.language_probability,
            duration_seconds=transcription.duration_seconds,
            processing_time_seconds=elapsed,
            executed_at=executed_at,
            settings=settings,
            text=transcription.text,
            segments=transcription.segments,
        )
