"""Minimal, non-destructive validation for supported audio files."""

from __future__ import annotations

from pathlib import Path

from .exceptions import AudioFileNotFoundError, EmptyAudioFileError, UnsupportedAudioFormatError
from .models import PreparedAudio

SUPPORTED_AUDIO_FORMATS = frozenset({".wav", ".mp3", ".m4a", ".flac"})


class AudioPreprocessor:
    """Validate files before delegating decoding to the selected STT engine."""

    def prepare(self, audio_path: Path) -> PreparedAudio:
        input_path = audio_path.expanduser()
        resolved_path = input_path.resolve(strict=False)
        if not resolved_path.exists() or not resolved_path.is_file():
            raise AudioFileNotFoundError(f"Arquivo de áudio não encontrado: {input_path}")

        extension = resolved_path.suffix.lower()
        if extension not in SUPPORTED_AUDIO_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_AUDIO_FORMATS))
            raise UnsupportedAudioFormatError(
                f"Formato não suportado: {extension or '(sem extensão)'}. Use: {supported}."
            )

        size_bytes = resolved_path.stat().st_size
        if size_bytes == 0:
            raise EmptyAudioFileError(f"O arquivo de áudio está vazio: {input_path}")

        return PreparedAudio(
            input_path=input_path,
            resolved_path=resolved_path,
            media_format=extension.removeprefix("."),
            size_bytes=size_bytes,
        )
