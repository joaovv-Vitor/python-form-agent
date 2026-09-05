from datetime import UTC
from pathlib import Path

from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription, TranscriptionSegment, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor


class FakeSpeechToTextEngine:
    def __init__(self) -> None:
        self.called_with = None

    def transcribe(self, audio, settings):
        self.called_with = (audio, settings)
        return EngineTranscription(
            engine="fake-engine",
            engine_version="1.0",
            text="Meu nome é João.",
            language="pt",
            language_probability=0.99,
            duration_seconds=1.5,
            segments=(TranscriptionSegment(0.0, 1.5, "Meu nome é João."),),
        )


def test_agent_coordinates_preprocessing_and_transcription(tmp_path: Path):
    audio_file = tmp_path / "joao.wav"
    audio_file.write_bytes(b"audio")
    engine = FakeSpeechToTextEngine()
    settings = TranscriptionSettings(model="small", language="pt")

    result = AudioAgent(AudioPreprocessor(), engine).transcribe(audio_file, settings)

    assert engine.called_with is not None
    assert result.audio_file == audio_file
    assert result.engine == "fake-engine"
    assert result.model == "small"
    assert result.text == "Meu nome é João."
    assert result.processing_time_seconds >= 0
    assert result.executed_at.tzinfo == UTC
    assert result.to_dict()["executed_at"] == result.executed_at.isoformat()


def test_result_serializes_reproducibility_metadata(tmp_path: Path):
    audio_file = tmp_path / "joao.wav"
    audio_file.write_bytes(b"audio")
    engine = FakeSpeechToTextEngine()

    result = AudioAgent(AudioPreprocessor(), engine).transcribe(audio_file, TranscriptionSettings())

    payload = result.to_dict()
    assert payload["settings"] == TranscriptionSettings().to_dict()
    assert payload["segments"] == [
        {
            "start_seconds": 0.0,
            "end_seconds": 1.5,
            "text": "Meu nome é João.",
            "average_log_probability": None,
            "no_speech_probability": None,
        }
    ]
