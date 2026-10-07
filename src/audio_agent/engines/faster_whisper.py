"""Local faster-whisper adapter, isolated from the rest of the application."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from ..exceptions import TranscriptionEngineUnavailableError, TranscriptionError
from ..models import EngineTranscription, PreparedAudio, TranscriptionSegment, TranscriptionSettings


class FasterWhisperSpeechToTextEngine:
    """Use faster-whisper lazily, caching one model configuration per instance."""

    engine_name = "faster-whisper"

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_key: tuple[str, str, str] | None = None

    def _get_model(self, settings: TranscriptionSettings) -> Any:
        model_key = (settings.model, settings.device, settings.compute_type)
        if self._model is not None and self._model_key == model_key:
            return self._model

        try:
            # Optional, untyped dependency stays confined to this runtime adapter.
            whisper_model = import_module("faster_whisper").WhisperModel
        except ImportError as exc:
            raise TranscriptionEngineUnavailableError(
                "faster-whisper não está instalado. Execute: python -m pip install -e '.[audio]'"
            ) from exc

        try:
            self._model = whisper_model(
                settings.model,
                device=settings.device,
                compute_type=settings.compute_type,
            )
        except Exception as exc:
            raise TranscriptionError(
                f"Não foi possível carregar o modelo faster-whisper '{settings.model}'."
            ) from exc
        self._model_key = model_key
        return self._model

    def transcribe(
        self,
        audio: PreparedAudio,
        settings: TranscriptionSettings,
    ) -> EngineTranscription:
        model = self._get_model(settings)
        try:
            raw_segments, info = model.transcribe(
                str(audio.resolved_path),
                language=settings.language,
                task="transcribe",
                beam_size=settings.beam_size,
                temperature=settings.temperature,
                vad_filter=settings.vad_filter,
                word_timestamps=False,
                initial_prompt=settings.initial_prompt,
                hotwords=settings.hotwords,
            )
            segments = tuple(
                TranscriptionSegment(
                    start_seconds=float(segment.start),
                    end_seconds=float(segment.end),
                    text=segment.text.strip(),
                    average_log_probability=getattr(segment, "avg_logprob", None),
                    no_speech_probability=getattr(segment, "no_speech_prob", None),
                )
                for segment in raw_segments
            )
        except Exception as exc:
            raise TranscriptionError(
                f"Não foi possível transcrever o arquivo: {audio.input_path}"
            ) from exc

        try:
            engine_version = version("faster-whisper")
        except PackageNotFoundError:
            engine_version = None
        return EngineTranscription(
            engine=self.engine_name,
            engine_version=engine_version,
            text=" ".join(segment.text for segment in segments if segment.text).strip(),
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", None),
            segments=segments,
        )
