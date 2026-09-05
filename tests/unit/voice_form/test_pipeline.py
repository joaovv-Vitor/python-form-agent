from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.core.agent import FormAgent
from form_agent.core.errors import ModelCommunicationError
from form_agent.core.schemas import FormInspection, ToolCall, ToolDefinition
from voice_form.pipeline import AudioFormPipeline


class Tools:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [ToolDefinition("click_button", "send", {})]

    async def inspect_form(self):
        self.calls.append("inspect")
        return FormInspection("file:///form.html")

    async def call_tool(self, name, arguments=None):
        self.calls.append(name)
        return {"success": True}

    async def close(self):
        pass


class Model:
    def __init__(self):
        self.instruction = None
        self.count = 0

    def create_session(self, instruction, inspection, tools):
        self.instruction = instruction
        return self

    async def next(self, completed):
        self.count += 1
        return [ToolCall("1", "click_button", {"button": "Enviar"})] if self.count == 1 else []

    async def close(self):
        pass


class Engine:
    def __init__(self, text):
        self.text = text

    def transcribe(self, audio, settings):
        return EngineTranscription("fake", "1", self.text, "pt", 1.0, 2.0, ())


async def test_transcription_reaches_real_form_agent_without_granting_authority(tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"fake audio for contract test")
    tools, model = Tools(), Model()
    text = "Meu nome é Ana. Pode preencher e enviar."
    pipeline = AudioFormPipeline(
        AudioAgent(AudioPreprocessor(), Engine(text)), FormAgent(tools, model)
    )
    result = await pipeline.run(path, TranscriptionSettings())
    assert model.instruction == text
    assert result.transcription.text == text
    assert not result.form.submission_authorized
    assert "click_button" not in tools.calls
    assert result.to_dict()["form"]["submitted"] is False
    assert result.total_seconds >= result.form_seconds >= 0


async def test_empty_or_missing_audio_never_reaches_form(tmp_path):
    for exists in (False, True):
        path = tmp_path / "audio.wav"
        if exists:
            path.write_bytes(b"audio")
        tools, model = Tools(), Model()
        result = await AudioFormPipeline(
            AudioAgent(AudioPreprocessor(), Engine("  ")),
            FormAgent(tools, model),
        ).run(path, TranscriptionSettings())
        assert result.form is None
        assert not tools.calls
        assert model.instruction is None
        assert result.issues[0].code == ("STT_EMPTY" if exists else "STT_ERROR")


async def test_provider_failure_preserves_transcription(tmp_path):
    class BrokenModel(Model):
        async def next(self, completed):
            raise ModelCommunicationError("offline")

    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    result = await AudioFormPipeline(
        AudioAgent(AudioPreprocessor(), Engine("Texto preservado")),
        FormAgent(Tools(), BrokenModel()),
    ).run(path, TranscriptionSettings())
    assert result.transcription.text == "Texto preservado"
    assert result.form is None
    assert result.issues[0].code == "PROVIDER_ERROR"
