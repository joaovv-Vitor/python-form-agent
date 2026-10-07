"""Typed models shared by the audio transcription workflow."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TranscriptionSettings:
    """Deterministic parameters used to transcribe one audio file."""

    model: str = "small"
    language: str | None = None
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 5
    temperature: float = 0.0
    vad_filter: bool = False
    initial_prompt: str | None = None
    hotwords: str | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("O modelo de transcrição não pode ser vazio.")
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("device deve ser 'cpu' ou 'cuda'.")
        if not self.compute_type.strip():
            raise ValueError("compute_type não pode ser vazio.")
        if self.beam_size <= 0:
            raise ValueError("beam_size deve ser maior que zero.")
        if not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("temperature não pode ser negativa.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PreparedAudio:
    """A validated audio file ready for a speech-to-text engine."""

    input_path: Path
    resolved_path: Path
    media_format: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class TranscriptionSegment:
    """A time-bounded portion of the transcription."""

    start_seconds: float
    end_seconds: float
    text: str
    average_log_probability: float | None = None
    no_speech_probability: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EngineTranscription:
    """Raw normalized data returned by a speech-to-text implementation."""

    engine: str
    engine_version: str | None
    text: str
    language: str | None
    language_probability: float | None
    duration_seconds: float | None
    segments: tuple[TranscriptionSegment, ...]


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Stable result contract consumed by future data-treatment and evaluation agents."""

    audio_file: Path
    media_format: str
    size_bytes: int
    engine: str
    engine_version: str | None
    model: str
    configured_language: str | None
    language: str | None
    language_probability: float | None
    duration_seconds: float | None
    processing_time_seconds: float
    executed_at: datetime
    settings: TranscriptionSettings
    text: str
    segments: tuple[TranscriptionSegment, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "audio_file": str(self.audio_file),
            "media_format": self.media_format,
            "size_bytes": self.size_bytes,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "model": self.model,
            "configured_language": self.configured_language,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration_seconds": self.duration_seconds,
            "processing_time_seconds": self.processing_time_seconds,
            "executed_at": self.executed_at.isoformat(),
            "settings": self.settings.to_dict(),
            "text": self.text,
            "segments": [segment.to_dict() for segment in self.segments],
        }
