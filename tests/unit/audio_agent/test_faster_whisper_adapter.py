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
