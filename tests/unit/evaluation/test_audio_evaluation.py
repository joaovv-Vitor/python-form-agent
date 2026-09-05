import csv
from dataclasses import replace

import pytest

from audio_agent.models import TranscriptionSettings
from form_agent.evaluation.cases import load_audio_cases
from form_agent.evaluation.metrics import EvaluationRow
from voice_form.evaluation import evaluate_audio, summarize


def catalogue(tmp_path, **overrides):
    path = tmp_path / "cases.csv"
    row = {
        "case_id": "case",
        "audio_file": "audio/a.wav",
        "reference_text": "Meu nome é Ana",
        "expected_json": '{"Nome": "Ana"}',
        "submitted": "false",
        "unmatched": "false",
        "form": "form.html",
        **overrides,
    }
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    return path


def test_catalogue_paths_and_authority_are_independent(tmp_path):
    path = catalogue(tmp_path, submitted="true")
    case = load_audio_cases(path)[0]
    assert case.audio_file == tmp_path / "audio/a.wav"
    assert case.form_url == (tmp_path / "form.html").as_uri()
    assert case.expected == {"Nome": "Ana"}
    assert case.submitted
    assert not case.submission_authorized


@pytest.mark.parametrize("payload", ["[]", '{"Nome": ["Ana"]}', '{"Nome": null}'])
def test_catalogue_rejects_unusable_expected_values(tmp_path, payload):
    with pytest.raises(ValueError):
        load_audio_cases(catalogue(tmp_path, expected_json=payload))


async def test_stt_mode_does_not_construct_llm_or_browser_and_reports_missing_audio(
    tmp_path, monkeypatch
):
    def forbidden(**kwargs):
        raise AssertionError("STT mode must not construct Form Agent infrastructure")

    monkeypatch.setattr("voice_form.evaluation.create_application", forbidden)
    summary, paths = await evaluate_audio(
        catalogue(tmp_path),
        TranscriptionSettings(),
        mode="stt",
        output_directory=tmp_path / "reports",
    )
    assert summary["execution_success_rate"] == 0
    assert summary["transcribed_attempts"] == 0
    assert "micro_wer" not in summary
    assert "STT_ERROR" in paths[0].read_text()


def test_positive_wer_and_functional_success_are_separate():
    row = EvaluationRow(
        "id",
        1,
        True,
        "estado",
        {"Estado": "CE"},
        {"Estado": "CE"},
        1,
        1,
        1,
        True,
        True,
        100,
        functional_success=True,
        mode="pipeline",
        transcription="Ceara",
        wer=1.0,
        cer=0.2,
        reference_words=1,
        word_edits=1,
        reference_characters=5,
        character_edits=1,
    )
    summary = summarize([row, replace(row, id="other", word_edits=0, reference_words=9, wer=0.0)])
    assert summary["functional_success_rate"] == 1
    assert summary["micro_wer"] == 0.1
    assert summary["pipeline_wer_positive_form_success"] == 1
    assert summary["pipeline_wer_zero_form_success"] == 1


async def test_empty_reference_is_input_error_not_provider_failure():
    from types import SimpleNamespace

    from form_agent.evaluation.cases import EvaluationCase
    from form_agent.evaluation.runner import _run_attempt

    async def forbidden(*args, **kwargs):
        raise AssertionError("Empty reference must not reach Form Agent")

    row = await _run_attempt(
        SimpleNamespace(run=forbidden), EvaluationCase("silence", "", {}, False, True), 1
    )
    assert row.error_codes == ("INPUT_ERROR",)
    assert row.failure_stage == "input"
    assert not row.passed
