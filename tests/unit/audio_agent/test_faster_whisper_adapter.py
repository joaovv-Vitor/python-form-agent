from types import SimpleNamespace

import pytest

from audio_agent.engines.faster_whisper import FasterWhisperSpeechToTextEngine
from audio_agent.exceptions import TranscriptionError
from audio_agent.models import PreparedAudio, TranscriptionSettings


def test_optional_engine_loads_lazily_and_reuses_model(monkeypatch, tmp_path):
    constructed, received = [], []

    class Whisper:
        def __init__(self, model, **kwargs):
            constructed.append((model, kwargs))

        def transcribe(self, path, **kwargs):
            received.append(kwargs)
            return iter([SimpleNamespace(start=0, end=1, text=" Pessoa Alfa ")]), SimpleNamespace(
                language="pt", duration=1.0
            )

    monkeypatch.setattr(
        "audio_agent.engines.faster_whisper.import_module",
        lambda name: SimpleNamespace(WhisperModel=Whisper),
    )
    engine = FasterWhisperSpeechToTextEngine()
    assert not constructed
    audio = PreparedAudio(tmp_path / "audio.wav", tmp_path / "audio.wav", "wav", 10)
    settings = TranscriptionSettings(model="tiny", language="pt", vad_filter=True)
    for _ in range(2):
        assert engine.transcribe(audio, settings).text == "Pessoa Alfa"
    assert len(constructed) == 1
    assert received[0]["vad_filter"] is True
    assert received[0]["language"] == "pt"
    assert received[0]["beam_size"] == 5
    assert received[0]["initial_prompt"] is None
    assert received[0]["hotwords"] is None


def test_cli_email_hints_reach_whisper_and_remain_in_metadata(monkeypatch, tmp_path):
    from audio_agent.cli import (
        EMAIL_HOTWORDS,
        EMAIL_INITIAL_PROMPT,
        _build_parser,
        settings_from_arguments,
    )

    received = {}

    def transcribe(path, **kwargs):
        received.update(kwargs)
        return iter(
            [SimpleNamespace(start=0, end=1, text="Meu e-mail é ana arroba example.com")]
        ), SimpleNamespace()

    model = SimpleNamespace(transcribe=transcribe)
    monkeypatch.setattr(
        "audio_agent.engines.faster_whisper.import_module",
        lambda name: SimpleNamespace(WhisperModel=lambda *args, **kwargs: model),
    )
    settings = settings_from_arguments(
        _build_parser().parse_args(["audio.wav", "--email-hints", "--model", "large-v3"])
    )
    audio = PreparedAudio(tmp_path / "audio.wav", tmp_path / "audio.wav", "wav", 10)
    result = FasterWhisperSpeechToTextEngine().transcribe(audio, settings)
    assert result.text == "Meu e-mail é ana arroba example.com"
    assert (
        received["initial_prompt"] == settings.to_dict()["initial_prompt"] == EMAIL_INITIAL_PROMPT
    )
    assert received["hotwords"] == settings.to_dict()["hotwords"] == EMAIL_HOTWORDS
    assert "joao" not in EMAIL_INITIAL_PROMPT
    assert "pedro" not in EMAIL_HOTWORDS


def test_errors_during_segment_iteration_are_normalized(monkeypatch, tmp_path):
    def segments():
        raise RuntimeError("decode failed while consuming lazy generator")
        yield

    model = SimpleNamespace(transcribe=lambda *args, **kwargs: (segments(), SimpleNamespace()))
    monkeypatch.setattr(
        "audio_agent.engines.faster_whisper.import_module",
        lambda name: SimpleNamespace(WhisperModel=lambda *args, **kwargs: model),
    )
    audio = PreparedAudio(tmp_path / "audio.wav", tmp_path / "audio.wav", "wav", 10)
    with pytest.raises(TranscriptionError):
        FasterWhisperSpeechToTextEngine().transcribe(audio, TranscriptionSettings())
