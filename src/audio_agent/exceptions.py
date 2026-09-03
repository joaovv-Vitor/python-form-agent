"""Domain errors raised by the Audio Agent."""

from __future__ import annotations


class AudioAgentError(Exception):
    """Base error for the audio transcription workflow."""


class AudioFileNotFoundError(AudioAgentError):
    """Raised when the requested audio file does not exist."""


class UnsupportedAudioFormatError(AudioAgentError):
    """Raised when an audio extension is not supported by this PoC."""


class EmptyAudioFileError(AudioAgentError):
    """Raised when the requested audio file has no content."""


class TranscriptionEngineUnavailableError(AudioAgentError):
    """Raised when the selected speech-to-text engine is not installed."""


class TranscriptionError(AudioAgentError):
    """Raised when the speech-to-text engine cannot transcribe an audio file."""
