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
