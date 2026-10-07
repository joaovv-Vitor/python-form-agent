import json
from types import SimpleNamespace

import pytest

from audio_agent.models import EngineTranscription
from form_agent.config import BrowserConfig, ModelConfig
from form_agent.core.schemas import AgentResult, FormField, FormInspection
from voice_form import cli


def application(monkeypatch, text, inventory=None):
    class Speech:
        def transcribe(self, audio, settings):
            return EngineTranscription("scripted", "1", text, "pt", 1.0, 1.0, ())

    class Agent:
        max_turns = 8

        async def run(self, instruction, *, authorize_submission=False, field_values=None):
            inspection = inventory or FormInspection("file:///form")
            return AgentResult(
                "Valores observados", inspection, (), False, True, final_inspection=inspection
            )

    closed = []

    async def close():
        closed.append(True)

    app = SimpleNamespace(
        config=ModelConfig("test", "test", "test", "unused"), agent=Agent(), close=close
    )

    async def inspect():
        return inventory or FormInspection("file:///form")

    app.agent.tools = SimpleNamespace(inspect_form=inspect)
    monkeypatch.setattr(cli, "create_application", lambda: app)
    monkeypatch.setattr(cli, "load_browser_config", lambda: BrowserConfig("file:///form"))
    monkeypatch.setattr(cli, "FasterWhisperSpeechToTextEngine", Speech)
    return closed


@pytest.mark.parametrize("raw", [True, False])
def test_cli_json_exposes_raw_and_treated_data_and_baseline_switch(
    tmp_path, monkeypatch, capsys, raw
):
    text = "E-mail: ana ponto silva arroba example ponto com"
    closed = application(monkeypatch, text)
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    args = [str(path), "--json", "--trace-directory", str(tmp_path / "runs")]
    if raw:
        args.append("--no-normalize-data")
    assert cli.main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["transcription"]["text"] == text
    if raw:
        assert data["normalization"] is None
    else:
        assert data["normalization"]["instruction"] == "E-mail: ana.silva@example.com"
    assert closed == [True]


@pytest.mark.parametrize("pending", [False, True])
def test_cli_deepseek_records_extraction_and_closes_both_resources(
    tmp_path, monkeypatch, capsys, pending
):
    from voice_form.extraction import validate_extraction

    text = "E-mail: ana ponto silva arroba example ponto com"
    inventory = FormInspection(
        "file:///form", (FormField("E-mail", "email", "email", "email", "textbox"),)
    )
    closed = application(monkeypatch, text, inventory)

    class Extractor:
        def manifest(self):
            return {"version": "test"}

        async def extract(self, transcription, observed):
            assert observed == inventory
            item = {
                "field": "email",
                "value": None if pending else "ana.silva@example.com",
                "source_text": "ana ponto silva arroba example ponto com",
                "status": "pending" if pending else "ready",
                "reason": "revise" if pending else None,
            }
            return validate_extraction(json.dumps({"fields": [item]}), transcription, observed)

        async def close(self):
            closed.append("extractor")

    monkeypatch.setattr(cli, "create_extractor", Extractor)
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    assert cli.main(
        [
            str(path),
            "--json",
            "--data-treatment",
            "deepseek",
            "--trace-directory",
            str(tmp_path / "runs"),
        ]
    ) == (2 if pending else 0)
    data = json.loads(capsys.readouterr().out)
    assert data["data_treatment"] == "deepseek"
    assert data["normalization"] is None
    assert data["extraction"]["fields"][0]["status"] == ("pending" if pending else "ready")
    assert data["transcription"]["text"] == text
    assert closed == [True, "extractor"]


def test_cli_does_not_offer_submission_with_pending_values(tmp_path, monkeypatch, capsys):
    closed = application(monkeypatch, "E-mail: João.pedroarrobajimeio.com. Pode enviar.")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Pending data must not reach submission confirmation")

    monkeypatch.setattr(cli, "confirm_submission", forbidden)
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    assert (
        cli.main([str(path), "--confirm-submit", "--trace-directory", str(tmp_path / "runs")]) == 2
    )
    assert "Revise os dados pendentes" in capsys.readouterr().out
    assert closed == [True]
