import pytest

from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.core.agent import FormAgent
from form_agent.core.errors import ModelCommunicationError, ToolClientError
from form_agent.core.schemas import FormField, FormInspection, ToolCall, ToolDefinition
from voice_form.pipeline import AudioFormPipeline


class Tools:
    def __init__(self, inventory=None):
        self.calls = []
        self.inventory = inventory or FormInspection("file:///form.html")

    async def list_tools(self):
        return [ToolDefinition("click_button", "send", {})]

    async def inspect_form(self):
        self.calls.append("inspect")
        return self.inventory

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
        self.settings = settings
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


async def test_empty_or_missing_audio_never_starts_form_filling(tmp_path):
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
        assert tools.calls == (["inspect"] if exists else [])
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
    assert tools.calls == ["inspect", "inspect"]
    assert result.issues[0].code == "EXTRACTION_ERROR"
    assert dict(events)["extraction_failed"]["response_json"] == "not-json"


async def test_form_context_is_read_before_stt_and_effective_settings_are_traced(tmp_path):
    import json

    from form_agent.experiments import RunTrace

    tools = Tools(
        FormInspection(
            "file:///form.html",
            (FormField("E-mail de contato", "email", "email", "email", "textbox"),),
        )
    )

    class Speech(Engine):
        def transcribe(self, audio, settings):
            assert tools.calls == ["inspect"]
            return super().transcribe(audio, settings)

    speech = Speech("Não envie.")
    settings = TranscriptionSettings()
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "manual") as trace:
        result = await AudioFormPipeline(
            AudioAgent(AudioPreprocessor(), speech),
            FormAgent(tools, Model()),
            events=trace.emit,
        ).run(path, settings)
    assert "E-mail de contato" in speech.settings.initial_prompt
    assert "arroba" in speech.settings.hotwords
    assert result.transcription.settings == speech.settings
    assert settings.initial_prompt is settings.hotwords is None
    assert not result.form.submission_authorized
    events = [json.loads(line) for line in trace.path.read_text().splitlines()]
    names = [event["event"] for event in events]
    assert names.index("stt_context_created") < names.index("audio_started")
    data = json.loads((tmp_path / "manual" / trace.run_id / "form_data.json").read_text())
    assert data["stt_settings"] == speech.settings.to_dict()


@pytest.mark.parametrize("manual", [False, True])
async def test_opt_out_or_fully_manual_context_skips_inspection_before_stt(tmp_path, manual):
    tools = Tools()

    class Speech(Engine):
        def transcribe(self, audio, settings):
            assert not tools.calls
            return super().transcribe(audio, settings)

    speech = Speech("Não envie.")
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    settings = (
        TranscriptionSettings(initial_prompt="Contexto manual", hotwords="Vocabulário manual")
        if manual
        else TranscriptionSettings()
    )
    await AudioFormPipeline(AudioAgent(AudioPreprocessor(), speech), FormAgent(tools, Model())).run(
        path, settings, auto_context=manual
    )
    assert speech.settings == settings


async def test_browser_context_failure_preserves_stt_and_reports_form_failure(tmp_path):
    class OfflineTools(Tools):
        async def inspect_form(self):
            raise ToolClientError("offline", "TIMEOUT")

    events = []
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    result = await AudioFormPipeline(
        AudioAgent(AudioPreprocessor(), Engine("Texto preservado")),
        FormAgent(OfflineTools(), Model()),
        events=lambda name, data: events.append((name, data)),
    ).run(path, TranscriptionSettings())
    assert result.transcription.text == "Texto preservado"
    assert result.transcription.settings.initial_prompt is None
    assert result.form is None
    assert result.issues[0].code == "TIMEOUT"
    assert dict(events)["stt_context_failed"]["code"] == "TIMEOUT"
