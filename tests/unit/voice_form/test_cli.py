import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from audio_agent.models import EngineTranscription
from form_agent.config import BrowserConfig, ModelConfig
from form_agent.core.schemas import AgentResult, FormField, FormInspection
from voice_form import cli


def application(monkeypatch, text, inventory=None):
    observed = inventory or FormInspection("file:///form")

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
        return observed

    async def call_tool(name, arguments):
        nonlocal observed
        assert name == "fill_field"
        observed = replace(
            observed,
            fields=tuple(
                replace(f, value=arguments["value"], valid=True)
                if f.reference == arguments["field"]
                else f
                for f in observed.fields
            ),
        )
        return {
            "success": True,
            "field": arguments["field"],
            "field_ref": arguments["field"],
            "value": arguments["value"],
        }

    app.agent.tools = SimpleNamespace(inspect_form=inspect, call_tool=call_tool)
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


def test_cli_rejects_json_with_interactive_clarification(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["audio.wav", "--json", "--clarify"])
    assert exc.value.code == 2
    assert "--json e --clarify" in capsys.readouterr().err


@pytest.mark.parametrize(
    "answer,denied,expected",
    [
        ("ana@example.com", False, 0),
        ("PULAR", False, 2),
        ("ana@example.com", True, 2),
    ],
)
def test_cli_clarification_precedes_submission_and_preserves_original_veto(
    tmp_path,
    monkeypatch,
    capsys,
    answer,
    denied,
    expected,
):
    inventory = FormInspection(
        "file:///form", (FormField("E-mail", "email", "email", "email", "textbox", value=""),)
    )
    text = "E-mail: incompleto. " + ("Não envie." if denied else "Pode enviar.")
    closed = application(monkeypatch, text, inventory)
    monkeypatch.setattr("builtins.input", lambda _: answer)
    confirmed = []

    async def confirm(app, result):
        confirmed.append(result)
        assert result.final_inspection.fields[0].value == "ana@example.com"
        assert not result.submission_authorized
        return {"submitted": True}

    monkeypatch.setattr(cli, "confirm_submission", confirm)
    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    assert (
        cli.main(
            [
                str(path),
                "--clarify",
                "--confirm-submit",
                "--trace-directory",
                str(tmp_path / "runs"),
            ]
        )
        == expected
    )
    capsys.readouterr()
    assert bool(confirmed) == (expected == 0)
    assert closed == [True]
    data_file = next((tmp_path / "manual").glob("*/form_data.json"))
    data = json.loads(data_file.read_text())
    assert data["transcription"] == text
    assert data["initial_issues"][0]["code"] == "DATA_PENDING"
    assert data["clarifications"][0]["status"] == ("skipped" if answer == "PULAR" else "resolved")
