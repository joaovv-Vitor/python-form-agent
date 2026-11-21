import csv
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from audio_agent.models import EngineTranscription, TranscriptionSettings
from form_agent.config import BrowserConfig, ModelConfig
from form_agent.core.errors import ModelCommunicationError
from form_agent.core.schemas import AgentResult, FormField, FormInspection
from voice_form import comparison
from voice_form.extraction import validate_extraction

TEXT = "E-mail: ana ponto silva arroba example ponto com. Não envie."
VALUE = "ana.silva@example.com"


def catalogue(tmp_path, *, missing=False):
    if not missing:
        (tmp_path / "audio.wav").write_bytes(b"scripted audio")
    path = tmp_path / "cases.csv"
    row = {
        "case_id": "email",
        "audio_file": "audio.wav",
        "reference_text": TEXT,
        "expected_json": json.dumps({"email": VALUE}),
        "submitted": "false",
        "unmatched": "false",
        "form": "form.html",
    }
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    return path


def infrastructure(monkeypatch, *, broken=False):
    calls = {"stt": 0, "apps": [], "extractions": [], "closed": []}
    inventory = FormInspection(
        "file:///form", (FormField("E-mail", "email", "email", "email", "textbox", value=""),)
    )

    class Speech:
        def transcribe(self, audio, settings):
            calls["stt"] += 1
            return EngineTranscription("scripted", "1", TEXT, "pt", 1.0, 1.0, ())

    class Extractor:
        def manifest(self):
            return {"version": "test-extractor"}

        async def extract(self, text, observed):
            calls["extractions"].append((text, observed))
            if broken:
                raise ModelCommunicationError("offline")
            payload = {
                "fields": [
                    {
                        "field": "email",
                        "value": VALUE,
                        "source_text": "ana ponto silva arroba example ponto com",
                        "status": "ready",
                        "reason": None,
                    }
                ]
            }
            return replace(
                validate_extraction(json.dumps(payload), text, observed),
                prompt_tokens=10,
                completion_tokens=5,
            )

        async def close(self):
            calls["closed"].append("extractor")

    def application(**kwargs):
        index = len(calls["apps"])
        calls["apps"].append(index)

        class Agent:
            max_turns = 8

            async def run(self, instruction, *, authorize_submission=False, field_values=None):
                assert not authorize_submission
                good = VALUE in instruction
                if field_values is not None:
                    assert field_values == {"email": VALUE}
                final = replace(
                    inventory,
                    fields=(
                        replace(inventory.fields[0], value=VALUE if good else "ana@example.com"),
                    ),
                )
                return AgentResult("done", inventory, (), False, False, final_inspection=final)

        async def inspect():
            return inventory

        async def close():
            calls["closed"].append(index)

        async def set_submission_authorized(authorized):
            assert not authorized

        agent = Agent()
        agent.tools = SimpleNamespace(inspect_form=inspect)
        return SimpleNamespace(
            config=ModelConfig("test", "test", "test", "unused"),
            agent=agent,
            close=close,
            client=SimpleNamespace(set_submission_authorized=set_submission_authorized),
        )

    monkeypatch.setattr(comparison, "create_extractor", Extractor)
    monkeypatch.setattr(comparison, "FasterWhisperSpeechToTextEngine", Speech)
    monkeypatch.setattr(comparison, "create_application", application)
    monkeypatch.setattr(comparison, "load_browser_config", lambda: BrowserConfig("file:///form"))
    return calls


async def test_comparison_transcribes_once_per_pair_rotates_order_and_isolates_forms(
    tmp_path, monkeypatch
):
    calls = infrastructure(monkeypatch)
    summary, paths = await comparison.compare_treatments(
        catalogue(tmp_path),
        TranscriptionSettings(),
        attempts=3,
        output_directory=tmp_path / "report",
    )
    assert calls["stt"] == 3
    assert len(calls["apps"]) == 9
    assert len(calls["extractions"]) == 3
    assert all(text == TEXT for text, _ in calls["extractions"])
    assert len(calls["closed"]) == 10
    assert summary["pairs"] == 3
    assert summary["raw.wrong_filled_values"] == 3
    assert summary["rules.wrong_filled_values"] == summary["deepseek.wrong_filled_values"] == 0
    assert summary["deepseek.extraction_prompt_tokens_reported"] == 30
    manifests = [
        json.loads(p.read_text().splitlines()[0])["data"]["metadata"]
        for p in (tmp_path / "report/runs").glob("*.jsonl")
    ]
    assert len(manifests) == 9
    for attempt, first in [(1, "raw"), (2, "rules"), (3, "deepseek")]:
        group = [m for m in manifests if m["attempt"] == attempt]
        assert len({m["pair_id"] for m in group}) == 1
        assert len({m["shared_stt_trace"] for m in group}) == 1
        assert [m for m in group if m["execution_index"] == 1][0]["data_treatment"] == first
    assert "data_treatment" in paths[1].read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("missing", [False, True])
async def test_failures_do_not_fall_back_or_contaminate_other_conditions(
    tmp_path, monkeypatch, missing
):
    calls = infrastructure(monkeypatch, broken=True)
    summary, _ = await comparison.compare_treatments(
        catalogue(tmp_path, missing=missing),
        TranscriptionSettings(),
        output_directory=tmp_path / "report",
    )
    assert calls["closed"][-1] == "extractor"
    if missing:
        assert calls["stt"] == 0
        assert calls["apps"] == calls["extractions"] == []
        assert summary["rules.overall_pass_rate"] == 0
    else:
        assert calls["stt"] == 1
        assert len(calls["apps"]) == 3
        assert summary["rules.complete_success_rate"] == 1
    assert summary["deepseek.overall_pass_rate"] == 0
