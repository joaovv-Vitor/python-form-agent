"""Speech-to-text abstraction used by the Audio Agent."""

from __future__ import annotations

from typing import Protocol

from .models import EngineTranscription, PreparedAudio, TranscriptionSettings


class SpeechToTextEngine(Protocol):
    """Contract that allows the TCC to compare STT engines later."""

    def transcribe(
        self,
        audio: PreparedAudio,
        settings: TranscriptionSettings,
    ) -> EngineTranscription:
        """Transcribe a prepared audio file into normalized domain data."""
