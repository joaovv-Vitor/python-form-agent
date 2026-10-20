import pytest

from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.adapters.mcp_client import BrowserToolsClient
from form_agent.bootstrap import Application
from form_agent.config import PROJECT_ROOT, BrowserConfig, ModelConfig
from form_agent.core.agent import FormAgent
from form_agent.core.schemas import ToolCall
from form_agent.evaluation.cases import EvaluationCase
from form_agent.experiments import RunTrace
from voice_form.evaluation import run_audio_attempt, summarize

pytestmark = pytest.mark.integration


class ScriptedModel:
    def create_session(self, instruction, inspection, tools):
        self.instruction = instruction
        self.batches = iter(
            [[ToolCall("fill", "fill_field", {"field": "Estado", "value": "Ceara"})], []]
        )
        return self

    async def next(self, completed):
        return next(self.batches, [])

    async def close(self):
        pass


class ScriptedSpeech:
    def transcribe(self, audio, settings):
        return EngineTranscription("scripted", "1", "Meu estado é Ceara.", "pt", 1.0, 2.0, ())


async def test_audio_to_real_mcp_browser_reports_success_despite_wer(tmp_path):
    audio_path = tmp_path / "fixture.wav"
    audio_path.write_bytes(b"contract fixture; decoding is provided by scripted STT")
    config = BrowserConfig((PROJECT_ROOT / "examples/test-form/index.html").as_uri(), headless=True)
    client = BrowserToolsClient(browser_config=config)
    model = ScriptedModel()
    agent = FormAgent(client, model)
    application = Application(
        ModelConfig("scripted", "scripted", "scripted", "unused"), agent, client, model
    )
    case = EvaluationCase(
        "ceara", "Meu estado é Ceará.", {"Estado": "CE"}, False, False, audio_file=audio_path
    )
    try:
        with RunTrace(
            tmp_path / "runs", {"test": "scripted STT/LLM; real MCP/Playwright"}
        ) as trace:
            agent.events = trace.emit
            row = await run_audio_attempt(
                case,
                1,
                "pipeline",
                AudioAgent(AudioPreprocessor(), ScriptedSpeech()),
                TranscriptionSettings(),
                trace,
                application,
            )
        assert model.instruction == "Meu estado é Ceara."
        assert row.wer == 0.25
        assert row.functional_success
        assert row.returned_data == {"Estado": "CE"}
        assert row.error_codes == ()
        assert summarize([row])["pipeline_wer_positive_form_success"] == 1
        assert "field_verified" in trace.path.read_text()
    finally:
        await application.close()


async def test_validated_extraction_constrains_writes_through_real_mcp(tmp_path):
    import json

    from voice_form.extraction import validate_extraction

    text = "E-mail: ana ponto silva arroba example ponto com. Não envie."

    class Speech:
        def transcribe(self, audio, settings):
            return EngineTranscription("scripted", "1", text, "pt", 1.0, 2.0, ())

    class Extractor:
        def manifest(self):
            return {"version": "scripted"}

        async def extract(self, transcription, inventory):
            return validate_extraction(
                json.dumps(
                    {
                        "fields": [
                            {
                                "field": "email",
                                "value": "ana.silva@example.com",
                                "source_text": "ana ponto silva arroba example ponto com",
                                "status": "ready",
                                "reason": None,
                            }
                        ]
                    }
                ),
                transcription,
                inventory,
            )

    class Model(ScriptedModel):
        def create_session(self, instruction, inspection, tools):
            assert "Não envie" in instruction
            self.batches = iter(
                [
                    [
                        ToolCall(
                            "bad",
                            "fill_field",
                            {
                                "field": "fullName",
                                "value": "Nome inventado",
                            },
                        ),
                        ToolCall(
                            "wrong",
                            "fill_field",
                            {
                                "field": "email",
                                "value": "outro@example.com",
                            },
                        ),
                        ToolCall(
                            "good",
                            "fill_field",
                            {
                                "field": "E-mail",
                                "value": "ana.silva@example.com",
                            },
                        ),
                    ],
                    [],
                ]
            )
            return self

    path = tmp_path / "extraction.wav"
    path.write_bytes(b"scripted audio")
    browser = BrowserConfig((PROJECT_ROOT / "examples/test-form/index.html").as_uri())
    client, model = BrowserToolsClient(browser_config=browser), Model()
    agent = FormAgent(client, model)
    application = Application(
        ModelConfig("scripted", "scripted", "scripted", "unused"), agent, client, model
    )
    case = EvaluationCase(
        "extraction", text, {"email": "ana.silva@example.com"}, False, False, audio_file=path
    )
    try:
        with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "data") as trace:
            agent.events = trace.emit
            row = await run_audio_attempt(
                case,
                1,
                "pipeline",
                AudioAgent(AudioPreprocessor(), Speech()),
                TranscriptionSettings(),
                trace,
                application,
                data_treatment="deepseek",
                extractor=Extractor(),
            )
        assert row.returned_data == case.expected
        assert row.unexpected_changes == {}
        assert row.data_treatment == "deepseek"
        assert row.wer == 0
        assert "DATA_BLOCKED" in row.error_codes
        final = await client.inspect_form()
        assert next(f for f in final.fields if f.id == "fullName").value == ""
        data = json.loads((tmp_path / "data" / trace.run_id / "form_data.json").read_text())
        assert data["data_extraction"]["fields"][0]["value"] == "ana.silva@example.com"
    finally:
        await application.close()


@pytest.mark.parametrize(
    "phone", ["85 999123456", "oitenta e cinco nove nove nove um dois três quatro cinco seis"]
)
async def test_spoken_values_are_treated_before_real_browser_and_wer_uses_raw_text(tmp_path, phone):
    text = (
        "Meu e-mail é ana ponto silva arroba example ponto com. "
        f"Meu telefone é {phone}. Minha data de nascimento é quinze de março de 2001."
    )

    class Speech:
        def transcribe(self, audio, settings):
            return EngineTranscription("scripted", "1", text, "pt", 1.0, 2.0, ())

    class Model(ScriptedModel):
        def create_session(self, instruction, inspection, tools):
            assert instruction == (
                "Meu e-mail é ana.silva@example.com. Meu telefone é (85) 99912-3456. "
                "Minha data de nascimento é 2001-03-15."
            )
            self.batches = iter(
                [
                    [
                        ToolCall(str(index), "fill_field", {"field": field, "value": value})
                        for index, (field, value) in enumerate(
                            [
                                ("email", "ana.silva@example.com"),
                                ("phone", "(85) 99912-3456"),
                                ("birthDate", "2001-03-15"),
                            ]
                        )
                    ],
                    [],
                ]
            )
            return self

    path = tmp_path / "spoken.wav"
    path.write_bytes(b"contract fixture; STT and LLM are simulated")
    browser = BrowserConfig((PROJECT_ROOT / "examples/test-form/index.html").as_uri())
    client, model = BrowserToolsClient(browser_config=browser), Model()
    agent = FormAgent(client, model)
    application = Application(
        ModelConfig("scripted", "scripted", "scripted", "unused"), agent, client, model
    )
    case = EvaluationCase(
        "spoken",
        text,
        {
            "email": "ana.silva@example.com",
            "phone": "(85) 99912-3456",
            "birthDate": "2001-03-15",
        },
        False,
        False,
        audio_file=path,
    )
    try:
        with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "data") as trace:
            agent.events = trace.emit
            row = await run_audio_attempt(
                case,
                1,
                "pipeline",
                AudioAgent(AudioPreprocessor(), Speech()),
                TranscriptionSettings(),
                trace,
                application,
            )
        assert row.passed
        assert row.returned_data == case.expected
        assert row.wer == row.cer == 0
        assert row.transcription == text
        assert "data_normalized" in trace.path.read_text()
        if "oitenta" in phone:
            assert "phone_text2num_pt" in trace.path.read_text()
        assert "phone_phonenumbers_br" in trace.path.read_text()
    finally:
        await application.close()


async def test_clarification_updates_real_browser_preserves_fields_and_records_history(tmp_path):
    import json

    from voice_form.clarification import ClarificationSession
    from voice_form.pipeline import AudioFormPipeline

    text = "Meu nome é Ana. E-mail: incompleto. Pode enviar."
    transcriptions = []

    class Speech:
        def transcribe(self, audio, settings):
            transcriptions.append(audio)
            return EngineTranscription("scripted", "1", text, "pt", 1.0, 2.0, ())

    class Model(ScriptedModel):
        def create_session(self, instruction, inspection, tools):
            assert "click_button" not in {tool.name for tool in tools}
            self.batches = iter(
                [
                    [ToolCall("fill", "fill_field", {"field": "fullName", "value": "Ana"})],
                    [],
                ]
            )
            return self

    prompts = []

    async def ask(question):
        prompts.append(question)
        return "ana@example.com"

    path = tmp_path / "spoken.wav"
    path.write_bytes(b"scripted STT input")
    browser = BrowserConfig((PROJECT_ROOT / "examples/test-form/index.html").as_uri())
    client, model = BrowserToolsClient(browser_config=browser), Model()
    agent = FormAgent(client, model)
    try:
        with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "manual") as trace:
            agent.events = trace.emit
            pipeline = AudioFormPipeline(
                AudioAgent(AudioPreprocessor(), Speech()),
                agent,
                events=trace.emit,
                clarification=ClarificationSession(ask, notify=lambda _: None, events=trace.emit),
            )
            result = await pipeline.run(path, TranscriptionSettings(), authorize_submission=True)
            trace.emit("run_completed", result.to_dict())
        assert len(transcriptions) == len(prompts) == 1
        assert result.issues == ()
        assert result.initial_issues[0].code == "DATA_PENDING"
        assert result.clarifications[0].status == "resolved"
        assert result.normalization.fields[0].status == "pending"
        assert result.form.verification_complete
        assert not result.form.submission_authorized
        assert not result.form.submission_attempted
        current = await client.inspect_form()
        assert current == result.form.final_inspection
        values = {f.reference: f.value for f in current.fields}
        assert values["fullName"] == "Ana"
        assert values["email"] == "ana@example.com"
        data = json.loads((tmp_path / "manual" / trace.run_id / "form_data.json").read_text())
        assert data["form_fields"]["email"] == "ana@example.com"
        assert data["filled_fields"] == {"fullName": "Ana", "email": "ana@example.com"}
        assert data["clarifications"][0]["value"] == "ana@example.com"
        assert data["data_normalization"]["fields"][0]["status"] == "pending"
        assert data["verification_complete"] is True
        assert data["transcription"] == text
    finally:
        await client.close()


async def test_real_form_metadata_reaches_whisper_before_form_filling(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from audio_agent.engines import FasterWhisperSpeechToTextEngine
    from voice_form.pipeline import AudioFormPipeline

    received = []

    def transcribe(path, **kwargs):
        received.append(kwargs)
        assert "Nome completo" in kwargs["initial_prompt"]
        assert "E-mail" in kwargs["initial_prompt"]
        assert "arroba" in kwargs["hotwords"]
        assert "Ceará" in kwargs["hotwords"]
        return iter(
            [SimpleNamespace(start=0, end=1, text="Meu estado é Ceara.")]
        ), SimpleNamespace()

    monkeypatch.setattr(
        "audio_agent.engines.faster_whisper.import_module",
        lambda _: SimpleNamespace(
            WhisperModel=lambda *args, **kwargs: SimpleNamespace(transcribe=transcribe)
        ),
    )
    path = tmp_path / "audio.wav"
    path.write_bytes(b"scripted decoder; real MCP/Playwright inspection")
    client = BrowserToolsClient(
        browser_config=BrowserConfig((PROJECT_ROOT / "examples/test-form/index.html").as_uri())
    )
    agent = FormAgent(client, ScriptedModel())
    try:
        with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "manual") as trace:
            agent.events = trace.emit
            result = await AudioFormPipeline(
                AudioAgent(AudioPreprocessor(), FasterWhisperSpeechToTextEngine()),
                agent,
                events=trace.emit,
            ).run(path, TranscriptionSettings())
        assert len(received) == 1
        assert not result.issues
        assert result.form.verification_complete
        assert not result.form.submission_authorized
        inspection = await client.inspect_form()
        assert next(f for f in inspection.fields if f.id == "state").value == "CE"
        assert next(f for f in inspection.fields if f.id == "email").value == ""
        events = [json.loads(line) for line in trace.path.read_text().splitlines()]
        names = [event["event"] for event in events]
        assert names.index("stt_context_created") < names.index("audio_started")
        assert names.index("audio_transcribed") < names.index("form_started")
        settings = result.transcription.settings
        assert received[0]["initial_prompt"] == settings.initial_prompt
        data = json.loads((tmp_path / "manual" / trace.run_id / "form_data.json").read_text())
        assert data["stt_settings"]["hotwords"] == received[0]["hotwords"]
    finally:
        await client.close()
