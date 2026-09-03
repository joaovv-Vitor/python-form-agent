from pathlib import Path

import pytest

from audio_agent.exceptions import (
    AudioFileNotFoundError,
    EmptyAudioFileError,
    UnsupportedAudioFormatError,
)
from audio_agent.preprocessing import AudioPreprocessor


def test_prepare_accepts_supported_audio_file(tmp_path: Path):
    audio_file = tmp_path / "sample.WAV"
    audio_file.write_bytes(b"audio")

    prepared = AudioPreprocessor().prepare(audio_file)

    assert prepared.input_path == audio_file
    assert prepared.resolved_path == audio_file.resolve()
    assert prepared.media_format == "wav"
    assert prepared.size_bytes == 5


def test_prepare_rejects_missing_file(tmp_path: Path):
    with pytest.raises(AudioFileNotFoundError, match="não encontrado"):
        AudioPreprocessor().prepare(tmp_path / "missing.mp3")


def test_prepare_rejects_unsupported_extension(tmp_path: Path):
    audio_file = tmp_path / "sample.ogg"
    audio_file.write_bytes(b"audio")

    with pytest.raises(UnsupportedAudioFormatError, match="Formato não suportado"):
        AudioPreprocessor().prepare(audio_file)


def test_prepare_rejects_empty_file(tmp_path: Path):
    audio_file = tmp_path / "empty.flac"
    audio_file.touch()

    with pytest.raises(EmptyAudioFileError, match="vazio"):
        AudioPreprocessor().prepare(audio_file)
