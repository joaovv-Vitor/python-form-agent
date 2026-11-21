import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from audio_agent.models import TranscriptionResult, TranscriptionSegment, TranscriptionSettings
from form_agent.config import BrowserConfig
from form_agent.evaluation.cases import EvaluationCase
from form_agent.evaluation.runner import failure_row
from form_agent.experiments import sha256_file
from voice_form import treatment_comparison as experiment


def saved_result(audio_file):
    return TranscriptionResult(
        audio_file,
        "m4a",
        5,
        "faster-whisper",
        "1.2.1",
        "large-v3",
        "pt",
        "pt",
        1.0,
        2.0,
        1.0,
        datetime(2026, 11, 17, tzinfo=UTC),
        TranscriptionSettings(model="large-v3", language="pt"),
        "Preencha Ana",
        (TranscriptionSegment(0, 2, "Preencha Ana"),),
    )


def test_restore_keeps_the_entire_original_transcription(tmp_path):
    original = saved_result(tmp_path / "audio.m4a")
    restored = experiment.restore_transcription(original.to_dict())
    assert restored == original
    assert restored.to_dict() == original.to_dict()


def test_saved_index_rejects_modified_transcription(tmp_path):
    path = tmp_path / "saved.json"
    path.write_text(
        json.dumps(
            {
                "case_id": "a",
                "attempt": 1,
                "transcription": saved_result(tmp_path / "audio.m4a").to_dict(),
            }
        )
    )
    index = {
        "selected_model": "large-v3",
        "transcriptions": [
            {"case_id": "a", "attempt": 1, "file": path.name, "sha256": sha256_file(path)}
        ],
    }
    (tmp_path / "index.json").write_text(json.dumps(index))
    path.write_text(path.read_text().replace("Preencha Ana", "Preencha Carlos"))
    with pytest.raises(ValueError, match="hash"):
        experiment.load_shared(tmp_path)


async def test_three_conditions_reuse_objects_rotate_and_resume_without_stt(tmp_path, monkeypatch):
    catalogue = tmp_path / "cases.csv"
    catalogue.write_text("fixed catalogue")
    audio_file = tmp_path / "audio.m4a"
    audio_file.write_bytes(b"audio")
    cases = [
        EvaluationCase(
            name,
            "Preencha Ana",
            {"Nome": "Ana"},
            False,
            False,
            form_url="https://example.com/form",
            audio_file=audio_file,
        )
        for name in ("a", "b")
    ]
    shared = tmp_path / "shared"
    shared.mkdir()
    entries = []
    for case in cases:
        for attempt in range(1, 4):
            path = shared / f"{case.id}_{attempt}.json"
            path.write_text(
                json.dumps(
                    {
                        "case_id": case.id,
                        "attempt": attempt,
                        "transcription": saved_result(audio_file).to_dict(),
                    }
                )
            )
            entries.append(
                {
                    "case_id": case.id,
                    "attempt": attempt,
                    "file": path.name,
                    "sha256": sha256_file(path),
                }
            )
    (shared / "index.json").write_text(
        json.dumps({"selected_model": "large-v3", "transcriptions": entries})
    )
    fixed_model = SimpleNamespace(model="deepseek-v4-flash")
    calls = []
    shared_objects = {}

    class Extractor:
        def manifest(self):
            return {"model": "deepseek-v4-flash", "version": "fixed"}

        async def close(self):
            pass

    extractor = Extractor()

    class App:
        def __init__(self):
            self.agent = SimpleNamespace(max_turns=0)

        async def close(self):
            pass

    def application(**kwargs):
        assert kwargs["model_config"] is fixed_model
        return App()

    async def run(case, attempt, mode, audio, settings, trace, app, **kwargs):
        condition = kwargs["data_treatment"]
        transcription = kwargs["prepared_transcription"]
        key = (case.id, attempt)
        if key in shared_objects:
            assert shared_objects[key] is transcription
        shared_objects[key] = transcription
        assert kwargs["allow_submission"] is False
        assert kwargs["extractor"] is (extractor if condition == "deepseek" else None)
        assert settings == transcription.settings
        calls.append((case.id, attempt, condition))
        row = replace(
            failure_row(case, attempt, "", "", 0.1),
            passed=True,
            functional_success=True,
            returned_data=case.expected,
            returned=1,
            correct=1,
            mode="pipeline",
            operational_failure=False,
            stt_model=settings.model,
            error_codes=(),
            error=None,
            transcription=transcription.text,
            word_edits=0,
            reference_words=2,
            wer=0.0,
            stt_seconds=1,
            post_stt_seconds=2,
            data_treatment=condition,
            pair_id=kwargs["pair_id"],
            condition_order=kwargs["condition_order"],
        )
        trace.emit("run_completed", row.to_dict())
        return row

    monkeypatch.setattr(experiment, "load_audio_cases", lambda path: cases)
    monkeypatch.setattr(experiment, "load_model_config", lambda: fixed_model)
    monkeypatch.setattr(
        experiment, "load_browser_config", lambda: BrowserConfig("https://example.com/form")
    )
    monkeypatch.setattr(experiment, "load_agent_max_turns", lambda: 8)
    monkeypatch.setattr(experiment, "create_extractor", lambda: extractor)
    monkeypatch.setattr(experiment, "create_application", application)
    monkeypatch.setattr(experiment, "run_audio_attempt", run)
    monkeypatch.setattr(
        experiment,
        "metadata",
        lambda **kwargs: dict(
            source_sha256="fixed source",
            llm={"model": "deepseek-v4-flash"},
            case_file_sha256=sha256_file(catalogue),
            audio_sha256=sha256_file(audio_file),
        ),
    )
    result = await experiment.compare(catalogue, shared, tmp_path / "results", attempts=3)
    assert result["total_attempts"] == 18
    assert result["stt_executions"] == 0
    assert len(calls) == 18
    assert [item[2] for item in calls[:3]] == ["raw", "rules", "deepseek"]
    assert [item[2] for item in calls[3:6]] == ["rules", "deepseek", "raw"]
    await experiment.compare(catalogue, shared, tmp_path / "results", attempts=3)
    assert len(calls) == 18
