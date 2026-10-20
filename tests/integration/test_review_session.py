import json

import pytest

from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.adapters.mcp_client import BrowserToolsClient
from form_agent.config import PROJECT_ROOT, BrowserConfig
from form_agent.core.schemas import AgentResult, FilledField, ToolCall
from form_agent.experiments import RunTrace
from voice_form.review import ReviewSession

pytestmark = pytest.mark.integration


class Model:
    def __init__(self, *calls):
        self.calls = iter(calls)

    def create_session(self, instruction, inspection, tools):
        assert {t.name for t in tools} == {"fill_field", "ask_clarification"}
        return self

    async def next(self, completed):
        return [next(self.calls)]


class Speech:
    def transcribe(self, audio, settings):
        return EngineTranscription(
            "scripted",
            "1",
            "Corrija meu telefone para oitenta e cinco nove oito oito oito oito um dois três quatro",
            "pt",
            1.0,
            2.0,
            (),
        )


def change(ref, value, source):
    return ToolCall("change", "fill_field", {"field": ref, "value": value, "source_text": source})


async def test_audio_and_text_corrections_share_real_browser_and_preserve_original_evidence(
    tmp_path,
):
    client = BrowserToolsClient(
        browser_config=BrowserConfig((PROJECT_ROOT / "examples/test-form/index.html").as_uri())
    )
    try:
        for ref, value in [
            ("fullName", "Ana"),
            ("phone", "(85) 99912-3456"),
            ("city", "Fortaleza"),
        ]:
            await client.call_tool("fill_field", {"field": ref, "value": value})
        inspection = await client.inspect_form()
        process = client._process
        form = AgentResult(
            "Inicial",
            inspection,
            tuple(FilledField(f.label, f.value, f.reference) for f in inspection.fields if f.value),
            False,
            False,
            final_inspection=inspection,
        )
        model = Model(
            change(
                "phone",
                "85988881234",
                "oitenta e cinco nove oito oito oito oito um dois três quatro",
            ),
            ToolCall("ask", "ask_clarification", {"question": "Qual é a cidade correta?"}),
            change("city", "Quixadá", "Quixadá"),
        )
        path = tmp_path / "correcao.wav"
        path.write_bytes(b"scripted STT; real MCP and browser")
        answers = iter(
            [f"AUDIO {path}", "Minha cidade está errada", "Quixadá", "MOSTRAR", "CONCLUIR"]
        )

        async def ask(_):
            return next(answers)

        with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "manual") as trace:
            trace.emit("audio_transcribed", {"text": "Transcrição inicial preservada"})
            trace.emit("form_inspected", inspection.to_dict())
            result = await ReviewSession(
                client,
                model,
                AudioAgent(AudioPreprocessor(), Speech()),
                TranscriptionSettings(),
                ask=ask,
                notify=lambda _: None,
                events=trace.emit,
            ).run(form, ())
        assert result.completed and not result.issues
        assert result.form.verification_complete
        assert client._process is process
        assert not result.form.submitted and not result.form.submission_attempted
        final = await client.inspect_form()
        values = {f.reference: f.value for f in final.fields}
        assert values["fullName"] == "Ana"
        assert values["phone"] == "(85) 98888-1234"
        assert values["city"] == "Quixadá"
        assert final == result.form.final_inspection
        data = json.loads((tmp_path / "manual" / trace.run_id / "form_data.json").read_text())
        assert data["transcription"] == "Transcrição inicial preservada"
        assert data["filled_fields"] == {"phone": "(85) 98888-1234", "city": "Quixadá"}
        assert [r["field"] for r in data["review_records"]] == ["phone", "city"]
        assert len(data["review_transcriptions"]) == 1
    finally:
        await client.close()


async def test_page_side_effect_invalidates_review_and_preserves_observed_failure(tmp_path):
    page = tmp_path / "form.html"
    page.write_text("""<!doctype html><html><body>
      <label>Nome<input id="name" value="Ana"></label>
      <label>Cidade<input id="city" value="Fortaleza" oninput="document.getElementById('name').value='alterado'"></label>
      <button type="submit">Enviar</button>
    </body></html>""")
    client = BrowserToolsClient(browser_config=BrowserConfig(page.as_uri()))
    try:
        inspection = await client.inspect_form()
        form = AgentResult("Inicial", inspection, (), False, False, final_inspection=inspection)
        model = Model(change("city", "Quixadá", "Quixadá"))

        async def ask(_):
            return "Corrija a cidade para Quixadá"

        result = await ReviewSession(
            client,
            model,
            AudioAgent(AudioPreprocessor(), Speech()),
            TranscriptionSettings(),
            ask=ask,
            notify=lambda _: None,
        ).run(form, ())
        assert not result.completed and not result.form.verification_complete
        assert len(result.records) == 1 and result.records[0].status == "failed"
        assert result.issues[0].code == "VERIFICATION_ERROR"
        final = await client.inspect_form()
        assert final == result.form.final_inspection
        assert next(f.value for f in final.fields if f.reference == "name") == "alterado"
    finally:
        await client.close()
