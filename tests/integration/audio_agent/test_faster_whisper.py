import os
from pathlib import Path

import pytest

from audio_agent.agent import AudioAgent
from audio_agent.engines import FasterWhisperSpeechToTextEngine
from audio_agent.models import TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor


@pytest.mark.integration
@pytest.mark.whisper_integration
def test_transcribes_configured_sample_audio():
    sample = Path(os.getenv("WHISPER_TEST_AUDIO", "samples/joao.wav"))
    if os.getenv("RUN_WHISPER_INTEGRATION") != "1":
        pytest.skip("Defina RUN_WHISPER_INTEGRATION=1 para carregar um modelo Whisper real.")
    if not sample.is_file():
        pytest.skip(f"Áudio de integração não encontrado: {sample}")

    result = AudioAgent(AudioPreprocessor(), FasterWhisperSpeechToTextEngine()).transcribe(
        sample, TranscriptionSettings(model="tiny", language="pt")
    )

    assert result.engine == "faster-whisper"
    assert result.duration_seconds is not None
    assert result.text
