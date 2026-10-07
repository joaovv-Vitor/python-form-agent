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


async def test_treated_instruction_reaches_form_and_trace_preserves_raw_values(tmp_path):
    import json

    from form_agent.experiments import RunTrace

    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    text = "E-mail: ana ponto silva arroba example ponto com. Telefone: 85 999123456."
    model = Model()
    with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "manual") as trace:
        form = FormAgent(Tools(), model, events=trace.emit)
        result = await AudioFormPipeline(
            AudioAgent(AudioPreprocessor(), Engine(text)), form, events=trace.emit
        ).run(path, TranscriptionSettings())
        trace.emit("run_completed", result.to_dict())
    assert model.instruction == "E-mail: ana.silva@example.com. Telefone: (85) 99912-3456."
    assert result.transcription.text == text
    assert result.normalization.original_text == text
    assert result.normalization_seconds >= 0
    data = json.loads((tmp_path / "manual" / trace.run_id / "form_data.json").read_text())
    assert data["transcription"] == text
    assert data["data_normalization"]["instruction"] == model.instruction
    assert (
        data["data_normalization"]["fields"][0]["source_text"]
        == "ana ponto silva arroba example ponto com"
    )


async def test_raw_baseline_can_be_selected(tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    text = "E-mail: ana arroba example ponto com"
    model = Model()
    result = await AudioFormPipeline(
        AudioAgent(AudioPreprocessor(), Engine(text)), FormAgent(Tools(), model)
    ).run(path, TranscriptionSettings(), normalize_data=False)
    assert model.instruction == text
    assert result.normalization is None
    assert result.normalization_seconds == 0


async def test_pending_data_is_not_forwarded_as_a_value_and_blocks_submission(tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    model = Model()
    result = await AudioFormPipeline(
        AudioAgent(AudioPreprocessor(), Engine("E-mail: João.pedroarrobajimeio.com. Pode enviar.")),
        FormAgent(Tools(), model),
    ).run(path, TranscriptionSettings(), authorize_submission=True)
    assert "João.pedroarrobajimeio.com" not in model.instruction
    assert "não preencher" in model.instruction
    assert result.issues[0].code == "DATA_PENDING"
    assert not result.form.submission_authorized


async def test_original_submission_veto_survives_treatment(tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    result = await AudioFormPipeline(
        AudioAgent(AudioPreprocessor(), Engine("Telefone: 85 999123456. Não envie.")),
        FormAgent(Tools(), Model()),
    ).run(path, TranscriptionSettings(), authorize_submission=True)
    assert not result.form.submission_authorized
    assert "Não envie." in result.normalization.instruction


async def test_invalid_extraction_preserves_stt_and_never_starts_form(tmp_path):
    from voice_form.extraction import validate_extraction

    class Extractor:
        def manifest(self):
            return {"version": "test"}

        async def extract(self, text, inventory):
            return validate_extraction("not-json", text, inventory)

    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    tools, model = Tools(), Model()
    events = []
    result = await AudioFormPipeline(
        AudioAgent(AudioPreprocessor(), Engine("Texto preservado")),
        FormAgent(tools, model),
        extractor=Extractor(),
        events=lambda name, data: events.append((name, data)),
    ).run(path, TranscriptionSettings(), data_treatment="deepseek")
    assert result.transcription.text == "Texto preservado"
    assert result.data_treatment == "deepseek"
    assert result.form is None
    assert model.instruction is None
    assert tools.calls == ["inspect"]
    assert result.issues[0].code == "EXTRACTION_ERROR"
    assert dict(events)["extraction_failed"]["response_json"] == "not-json"
