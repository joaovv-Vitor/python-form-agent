from dataclasses import replace
from types import SimpleNamespace

from form_agent.config import BrowserConfig
from form_agent.evaluation.cases import EvaluationCase
from form_agent.evaluation.runner import failure_row
from form_agent.experiments import sha256_file
from voice_form import whisper_comparison as experiment


def test_selection_prioritizes_functional_outcomes_before_wer_and_speed():
    base = dict(complete_success_rate=0.5, field_accuracy_rate=0.8, wer=0.1, average_stt_seconds=3)
    better_success = {**base, "complete_success_rate": 0.6, "wer": 0.5}
    better_fields = {**base, "field_accuracy_rate": 0.9, "wer": 0.5}
    assert experiment.selection_key(better_success) < experiment.selection_key(base)
    assert experiment.selection_key(better_fields) < experiment.selection_key(base)
    assert experiment.selection_key({**base, "wer": 0.05}) < experiment.selection_key(base)
    assert experiment.selection_key({**base, "average_stt_seconds": 2}) < experiment.selection_key(
        base
    )


async def test_models_share_fixed_settings_rotate_order_and_resume_without_new_attempts(
    tmp_path, monkeypatch
):
    catalogue = tmp_path / "cases.csv"
    catalogue.write_text("fixed catalogue")
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"fixed audio")
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
    fixed_model = SimpleNamespace(model="deepseek-v4-flash")
    calls = []
    closed = []

    class Engine:
        def _get_model(self, settings):
            return None

    class App:
        agent = None

        def __init__(self):
            self.agent = SimpleNamespace(max_turns=0)

        async def close(self):
            closed.append(self)

    def application(**kwargs):
        assert kwargs["model_config"] is fixed_model
        return App()

    async def run(case, attempt, mode, audio, settings, trace, app, **kwargs):
        calls.append((case.id, attempt, settings.model))
        assert mode == "pipeline"
        assert kwargs == {"allow_submission": False, "data_treatment": "rules"}
        assert settings.language == "pt" and settings.device == "cpu"
        assert settings.compute_type == "int8" and settings.beam_size == 5
        assert (
            settings.temperature == 0
            and settings.initial_prompt is None
            and settings.hotwords is None
        )
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
            transcription="Ana",
            word_edits=0,
            reference_words=1,
            wer=0.0,
            stt_seconds=1,
        )
        trace.emit("run_completed", row.to_dict())
        return row

    monkeypatch.setattr(experiment, "load_audio_cases", lambda path: cases)
    monkeypatch.setattr(experiment, "load_model_config", lambda: fixed_model)
    monkeypatch.setattr(
        experiment, "load_browser_config", lambda: BrowserConfig("https://example.com/form")
    )
    monkeypatch.setattr(experiment, "load_agent_max_turns", lambda: 8)
    monkeypatch.setattr(
        experiment,
        "metadata",
        lambda **kwargs: dict(
            source_sha256="fixed source",
            case_file_sha256=sha256_file(catalogue),
            llm={"model": "deepseek-v4-flash"},
        ),
    )
    monkeypatch.setattr(experiment, "FasterWhisperSpeechToTextEngine", Engine)
    monkeypatch.setattr(experiment, "create_application", application)
    monkeypatch.setattr(experiment, "run_audio_attempt", run)
    output = tmp_path / "results"
    result = await experiment.compare(catalogue, output, attempts=3)
    assert result["total_attempts"] == 24
    assert len(calls) == len(closed) == 24
    assert [entry[2] for entry in calls[:4]] == list(experiment.MODELS)
    assert [entry[2] for entry in calls[4:8]] == ["small", "medium", "large-v3", "base"]
    await experiment.compare(catalogue, output, attempts=3)
    assert len(calls) == 24
