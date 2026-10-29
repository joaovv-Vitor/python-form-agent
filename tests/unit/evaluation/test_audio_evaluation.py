import csv
from dataclasses import replace

import pytest

from audio_agent.models import TranscriptionSettings
from form_agent.evaluation.cases import load_audio_cases, load_dataset_audio_cases
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


def test_dataset_catalogue_resolves_recording_by_stem_and_skips_missing(tmp_path):
    dataset = tmp_path / "dataset"
    speaker = dataset / "speaker_02"
    speaker.mkdir(parents=True)
    recording = speaker / "spk02_01_common.mp4"
    recording.write_bytes(b"audio")
    metadata = dataset / "metadata.csv"
    metadata.write_text(
        "id,speaker,file,category,transcription\n"
        '1,spk02,spk02_01_common.wav,common,"Meu nome é Ana."\n'
        '2,spk01,spk01_01_common.wav,common,"Meu nome é Bia."\n',
        encoding="utf-8",
    )

    cases, missing, source = load_dataset_audio_cases(dataset)

    assert source == metadata
    assert missing == ("spk01_01_common.wav",)
    assert len(cases) == 1
    assert cases[0].id == "1"
    assert cases[0].audio_file == recording
    assert cases[0].instruction == "Meu nome é Ana."
    assert cases[0].speaker == "spk02"
    assert cases[0].scenario == "common"


def test_dataset_catalogue_rejects_pipeline_without_form_oracle(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "sample.mp4").write_bytes(b"audio")
    (dataset / "metadata.csv").write_text(
        "id,speaker,file,category,transcription\n1,spk01,sample.wav,common,Teste\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_json"):
        import asyncio

        asyncio.run(
            evaluate_audio(
                None,
                TranscriptionSettings(),
                mode="pipeline",
                dataset_path=dataset,
                output_directory=tmp_path / "reports",
            )
        )


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


async def test_stt_report_records_transcription_settings(tmp_path, monkeypatch):
    from audio_agent.models import EngineTranscription

    class Speech:
        def transcribe(self, audio, settings):
            return EngineTranscription("scripted", "1", "Meu nome é Ana", "pt", 1.0, 1.0, ())

    monkeypatch.setattr("voice_form.evaluation.FasterWhisperSpeechToTextEngine", lambda: Speech())
    path = catalogue(tmp_path)
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio/a.wav").write_bytes(b"audio")
    settings = TranscriptionSettings(
        model="base",
        language="pt",
        device="cpu",
        compute_type="int8",
        beam_size=3,
        temperature=0.2,
        vad_filter=True,
        initial_prompt="Vocabulário de cadastro",
        hotwords="arroba ponto",
    )

    _, paths = await evaluate_audio(
        path,
        settings,
        mode="stt",
        output_directory=tmp_path / "reports",
    )

    assert "stt_base_" in paths[0].name
    report = paths[1].read_text(encoding="utf-8-sig")
    assert "stt_model" in report
    assert "base" in report
    assert "int8" in report
    assert "stt_initial_prompt" in report
    assert "Vocabulário de cadastro" in report
    assert "arroba ponto" in report


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


@pytest.mark.parametrize("normalize_data", [True, False])
async def test_pending_data_is_reported_without_changing_stt_scoring(tmp_path, normalize_data):
    from types import SimpleNamespace

    from audio_agent.agent import AudioAgent
    from audio_agent.models import EngineTranscription
    from audio_agent.preprocessing import AudioPreprocessor
    from form_agent.core.schemas import AgentResult, FormInspection
    from form_agent.evaluation.cases import EvaluationCase
    from form_agent.experiments import RunTrace
    from voice_form.evaluation import run_audio_attempt

    text = "E-mail: João.pedroarrobajimeio.com. Não envie."

    class Speech:
        def transcribe(self, audio, settings):
            return EngineTranscription("scripted", "1", text, "pt", 1.0, 1.0, ())

    class Form:
        async def run(self, instruction, *, authorize_submission=False):
            self.instruction = instruction
            inspection = FormInspection("file:///form")
            return AgentResult("", inspection, (), False, True, final_inspection=inspection)

    class Client:
        async def set_submission_authorized(self, authorized):
            pass

    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    form = Form()
    with RunTrace(tmp_path / "runs", {}) as trace:
        row = await run_audio_attempt(
            EvaluationCase("pending", text, {}, False, True, audio_file=path),
            1,
            "pipeline",
            AudioAgent(AudioPreprocessor(), Speech()),
            TranscriptionSettings(),
            trace,
            SimpleNamespace(agent=form, client=Client()),
            normalize_data=normalize_data,
        )
    assert row.transcription == text
    assert row.wer == row.cer == 0
    if normalize_data:
        assert row.normalized_instruction == form.instruction
        assert row.data_normalization_version == "spoken-data-pt-BR-v4"
        assert row.normalization_seconds >= 0
        assert not row.passed
        assert not row.functional_success
        assert row.failure_stage == "normalization"
        assert "DATA_PENDING" in row.error_codes
        assert "João.pedroarrobajimeio.com" not in form.instruction
    else:
        assert row.normalized_instruction is None
        assert row.data_normalization_version is None
        assert row.passed
        assert row.error_codes == ()
        assert form.instruction == text
