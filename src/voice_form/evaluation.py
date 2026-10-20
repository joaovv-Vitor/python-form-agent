"""Three comparable modes using the same audio catalogue and form scorer."""

from __future__ import annotations

import argparse
import asyncio
import re
import time
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from audio_agent.agent import AudioAgent
from audio_agent.cli import add_transcription_arguments, settings_from_arguments
from audio_agent.engines import FasterWhisperSpeechToTextEngine
from audio_agent.exceptions import AudioAgentError
from audio_agent.models import TranscriptionResult, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.bootstrap import Application, create_application
from form_agent.config import PROJECT_ROOT, load_browser_config
from form_agent.core.errors import FormAgentError, error_code
from form_agent.evaluation.cases import (
    EvaluationCase,
    load_audio_cases,
    load_dataset_audio_cases,
)
from form_agent.evaluation.metrics import EvaluationRow, calculate
from form_agent.evaluation.reporting import write_reports
from form_agent.evaluation.runner import _run_attempt, failure_row, score_form
from form_agent.evaluation.speech_metrics import (
    NORMALIZATION_VERSION,
    real_time_factor,
    score_transcript,
)
from form_agent.experiments import RunTrace, metadata

from .extraction import DataExtractor, create_extractor
from .normalization import DATA_NORMALIZATION_VERSION
from .pipeline import AudioFormPipeline, DataTreatment, treatment_name

type Mode = Literal["stt", "reference", "pipeline"]


async def run_audio_attempt(
    case: EvaluationCase,
    attempt: int,
    mode: Mode,
    audio: AudioAgent,
    settings: TranscriptionSettings,
    trace: RunTrace,
    application: Application | None,
    *,
    allow_submission: bool = False,
    normalize_data: bool = True,
    data_treatment: DataTreatment | None = None,
    extractor: DataExtractor | None = None,
    prepared_transcription: TranscriptionResult | None = None,
    pair_id: str = "",
    condition_order: int | None = None,
) -> EvaluationRow:
    started = time.perf_counter()
    transcription: TranscriptionResult | None = prepared_transcription
    form_seconds: float | None = None
    stage = "stt" if mode == "stt" else "form" if mode == "reference" else "pipeline"
    try:
        if mode == "reference":
            if application is None:
                raise ValueError("Application necessária no modo reference")
            authorized = allow_submission and case.submission_authorized
            await application.client.set_submission_authorized(authorized)
            row = await _run_attempt(
                application.agent, case, attempt, authorize_submission=authorized
            )
            form_seconds = row.form_seconds
        elif mode == "pipeline":
            if application is None or case.audio_file is None:
                raise ValueError("Application e áudio necessários no modo pipeline")
            authorized = allow_submission and case.submission_authorized
            # Batch evaluation keeps explicitly configured STT hints for reproducibility.
            await application.client.set_submission_authorized(authorized)
            pipeline = AudioFormPipeline(
                audio, application.agent, events=trace.emit, extractor=extractor
            )
            if prepared_transcription:
                result = await pipeline.run_transcription(
                    prepared_transcription,
                    authorize_submission=authorized,
                    normalize_data=normalize_data,
                    data_treatment=data_treatment,
                )
            else:
                result = await pipeline.run(
                    case.audio_file,
                    settings,
                    authorize_submission=authorized,
                    normalize_data=normalize_data,
                    data_treatment=data_treatment,
                    auto_context=False,
                )
            transcription, form_seconds = result.transcription, result.form_seconds
            normalized_instruction = (
                result.normalization.instruction if result.normalization else None
            )
            data_normalization_version = (
                result.normalization.version if result.normalization else None
            )
            if result.extraction:
                normalized_instruction = result.extraction.instruction
            if result.form:
                row = score_form(
                    case, attempt, replace(result.form, issues=result.issues), result.form_seconds
                )
                if any(issue.code == "DATA_PENDING" for issue in result.issues):
                    row = replace(
                        row,
                        passed=False,
                        functional_success=False,
                        failure_stage="extraction" if result.extraction else "normalization",
                    )
            else:
                issue = next(
                    (issue for issue in result.issues if issue.stage != "normalization"),
                    result.issues[0],
                )
                row = failure_row(
                    case,
                    attempt,
                    issue.code,
                    issue.message,
                    result.total_seconds,
                    stage=issue.stage,
                )
            row = replace(
                row,
                normalized_instruction=normalized_instruction,
                data_normalization_version=data_normalization_version,
                normalization_seconds=result.normalization_seconds
                if result.normalization
                else None,
                data_treatment=result.data_treatment,
                extraction_seconds=result.extraction_seconds
                if result.data_treatment == "deepseek"
                else None,
                extraction_version=result.extraction.version if result.extraction else None,
                extraction_prompt_tokens=result.extraction.prompt_tokens
                if result.extraction
                else None,
                extraction_completion_tokens=result.extraction.completion_tokens
                if result.extraction
                else None,
                pending_fields=tuple(
                    f.field for f in result.extraction.fields if f.status == "pending"
                )
                if result.extraction
                else tuple(f.kind for f in result.normalization.fields if f.status == "pending")
                if result.normalization
                else (),
                post_stt_seconds=result.post_stt_seconds,
            )
        else:
            if case.audio_file is None:
                raise ValueError("Áudio ausente")
            trace.emit(
                "audio_started", {"path": str(case.audio_file), "settings": settings.to_dict()}
            )
            transcription = await asyncio.to_thread(audio.transcribe, case.audio_file, settings)
            trace.emit("audio_transcribed", transcription.to_dict())
            # STT mode reports execution success. WER is a separate continuous outcome.
            row = failure_row(case, attempt, "STT_ERROR", "", 0, stage="stt")
            row = replace(
                row, passed=True, error=None, error_codes=(), failure_stage=None, expected_count=0
            )
    except Exception as exc:
        code = (
            "STT_ERROR"
            if isinstance(exc, AudioAgentError)
            else error_code(exc)
            if isinstance(exc, FormAgentError)
            else "INTERNAL_ERROR"
        )
        row = failure_row(case, attempt, code, str(exc), time.perf_counter() - started, stage=stage)
        trace.emit("stage_failed", {"code": code, "stage": stage, "error": str(exc)})
    elapsed = time.perf_counter() - started
    if prepared_transcription:
        elapsed += prepared_transcription.processing_time_seconds
    row = replace(
        row,
        mode=mode,
        run_id=trace.run_id,
        trace_path=str(trace.path),
        reference_text=case.instruction,
        speaker=case.speaker,
        scenario=case.scenario,
        total_seconds=elapsed,
        latency_ms=round(elapsed * 1000),
        form_seconds=form_seconds,
        pair_id=pair_id,
        data_treatment=treatment_name(normalize_data, data_treatment) if mode == "pipeline" else "",
        condition_order=condition_order,
        stt_model=settings.model if mode != "reference" else "",
        stt_language=settings.language if mode != "reference" else None,
        stt_device=settings.device if mode != "reference" else "",
        stt_compute_type=settings.compute_type if mode != "reference" else "",
        stt_beam_size=settings.beam_size if mode != "reference" else None,
        stt_temperature=settings.temperature if mode != "reference" else None,
        stt_vad_filter=settings.vad_filter if mode != "reference" else False,
        stt_initial_prompt=settings.initial_prompt if mode != "reference" else None,
        stt_hotwords=settings.hotwords if mode != "reference" else None,
    )
    if transcription is not None:
        speech = score_transcript(case.instruction, transcription.text)
        row = replace(
            row,
            transcription=transcription.text,
            **asdict(speech),
            stt_seconds=transcription.processing_time_seconds,
            rtf=real_time_factor(
                transcription.processing_time_seconds, transcription.duration_seconds
            ),
        )
    trace.emit("run_completed", row.to_dict())
    return row


def summarize(rows: Sequence[EvaluationRow]) -> dict[str, float | int]:
    if not rows:
        raise ValueError("Não há resultados")
    forms = [row for row in rows if row.mode != "stt"]
    summary = (
        calculate(forms).to_dict()
        if forms
        else {
            "total_attempts": len(rows),
            "unique_cases": len({row.id for row in rows}),
            "execution_success_rate": sum(row.passed for row in rows) / len(rows),
            "average_latency_ms": sum(row.latency_ms for row in rows) / len(rows),
            "p95_latency_ms": sorted(row.latency_ms for row in rows)[
                max(0, (95 * len(rows) + 99) // 100 - 1)
            ],
        }
    )
    speech_rows = [row for row in rows if row.transcription is not None]
    word_rows = [row for row in speech_rows if row.reference_words]
    char_rows = [row for row in speech_rows if row.reference_characters]
    summary["transcribed_attempts"] = len(speech_rows)
    summary["wer_scored_attempts"] = len(word_rows)
    summary["empty_reference_attempts"] = sum(row.reference_words == 0 for row in speech_rows)
    if word_rows:
        summary["micro_wer"] = sum(row.word_edits or 0 for row in word_rows) / sum(
            row.reference_words or 0 for row in word_rows
        )
    if char_rows:
        summary["micro_cer"] = sum(row.character_edits or 0 for row in char_rows) / sum(
            row.reference_characters or 0 for row in char_rows
        )
    if speech_rows:
        summary["average_stt_seconds"] = sum(row.stt_seconds or 0 for row in speech_rows) / len(
            speech_rows
        )
    rtfs = [row.rtf for row in speech_rows if row.rtf is not None]
    if rtfs:
        summary["average_rtf"] = sum(rtfs) / len(rtfs)
    pipelines = [row for row in rows if row.mode == "pipeline"]
    for differs in (False, True):
        for success in (False, True):
            summary[
                f"pipeline_wer_{'positive' if differs else 'zero'}_form_{'success' if success else 'failure'}"
            ] = sum(
                row.wer is not None
                and (row.wer > 0) == differs
                and row.functional_success == success
                for row in pipelines
            )
    summary["pipeline_unscored_wer"] = sum(row.wer is None for row in pipelines)
    return summary


async def evaluate_audio(
    cases_path: Path | None,
    settings: TranscriptionSettings,
    *,
    mode: Mode = "pipeline",
    attempts: int = 1,
    output_directory: Path = PROJECT_ROOT / "reports",
    allow_submission: bool = False,
    dataset_path: Path | None = None,
    normalize_data: bool = True,
    data_treatment: DataTreatment | None = None,
) -> tuple[dict[str, float | int], tuple[Path, Path]]:
    if attempts <= 0:
        raise ValueError("attempts deve ser maior que zero")
    if dataset_path is not None:
        if mode != "stt":
            raise ValueError(
                "O metadata.csv do dataset permite avaliar STT, mas não contém o oráculo "
                "expected_json necessário para os modos reference/pipeline."
            )
        cases, missing_recordings, source_path = load_dataset_audio_cases(dataset_path)
        print(
            f"Dataset: {len(cases)} áudio(s) encontrado(s); "
            f"{len(missing_recordings)} entrada(s) sem gravação ignorada(s)."
        )
    else:
        if cases_path is None:
            raise ValueError("Informe --cases ou --dataset")
        cases = load_audio_cases(cases_path)
        source_path = cases_path
    condition = treatment_name(normalize_data, data_treatment)
    extractor = create_extractor() if mode == "pipeline" and condition == "deepseek" else None
    try:
        return await _evaluate_loaded_cases(
            cases,
            source_path,
            settings,
            mode,
            attempts,
            output_directory,
            allow_submission,
            condition,
            extractor,
        )
    finally:
        if extractor:
            await extractor.close()


async def _evaluate_loaded_cases(
    cases: Sequence[EvaluationCase],
    source_path: Path,
    settings: TranscriptionSettings,
    mode: Mode,
    attempts: int,
    output_directory: Path,
    allow_submission: bool,
    condition: DataTreatment,
    extractor: DataExtractor | None,
) -> tuple[dict[str, float | int], tuple[Path, Path]]:
    audio = AudioAgent(AudioPreprocessor(), FasterWhisperSpeechToTextEngine())
    rows: list[EvaluationRow] = []
    for case in cases:
        for attempt in range(1, attempts + 1):
            browser = load_browser_config() if mode != "stt" else None
            if browser and case.form_url:
                browser = replace(browser, url=case.form_url)
            application = create_application(browser_config=browser) if mode != "stt" else None
            try:
                manifest = metadata(
                    model=application.config if application else None,
                    browser=browser,
                    case_file=source_path,
                    audio_file=case.audio_file,
                    stt_settings=settings.to_dict() if mode != "reference" else None,
                    max_turns=application.agent.max_turns if application else None,
                )
                manifest.update(
                    {
                        "mode": mode,
                        "case_id": case.id,
                        "attempt": attempt,
                        "allow_submission": allow_submission,
                        "normalization_version": NORMALIZATION_VERSION,
                        "data_normalization_version": (
                            DATA_NORMALIZATION_VERSION
                            if mode == "pipeline" and condition == "rules"
                            else None
                        ),
                        "data_treatment": condition if mode == "pipeline" else None,
                        "extraction": extractor.manifest() if extractor else None,
                        "stt_model_cache": "shared_per_invocation",
                    }
                )
                with RunTrace(
                    output_directory / "runs",
                    manifest,
                    data_directory=output_directory / "tests",
                ) as trace:
                    if application:
                        application.agent.events = trace.emit
                    row = await run_audio_attempt(
                        case,
                        attempt,
                        mode,
                        audio,
                        settings,
                        trace,
                        application,
                        allow_submission=allow_submission,
                        data_treatment=condition,
                        extractor=extractor,
                    )
                    rows.append(row)
                    print(
                        f"{case.id} {mode} tentativa {attempt}/{attempts}: {'PASS' if row.passed else 'FAIL'}; WER={row.wer}"
                    )
            finally:
                if application:
                    await application.close()
    summary = summarize(rows)
    model_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", settings.model).strip("-") or "model"
    stamp = f"{mode}_{model_slug}_{datetime.now(UTC).strftime('%Y-%m-%d_%H-%M-%S-%f')}"
    paths = write_reports(summary, rows, stamp, output_directory)
    print(f"Relatório HTML: {paths[0]}\nPlanilha CSV: {paths[1]}")
    return summary, paths


def main(argv: Sequence[str] | None = None, *, default_mode: Mode = "pipeline") -> int:
    parser = argparse.ArgumentParser(
        description="Avalia STT, texto de referência ou pipeline pelo mesmo catálogo."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--cases", type=Path)
    source.add_argument(
        "--dataset",
        type=Path,
        help="Diretório com metadata.csv e gravações, ou caminho para o metadata.csv.",
    )
    parser.add_argument("--mode", choices=("stt", "reference", "pipeline"), default=default_mode)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports")
    treatment = parser.add_mutually_exclusive_group()
    treatment.add_argument(
        "--no-normalize-data",
        dest="data_treatment",
        action="store_const",
        const="raw",
        help="Desativa o tratamento no modo pipeline; STT e referência permanecem brutos.",
    )
    treatment.add_argument("--data-treatment", choices=("raw", "rules", "deepseek"), default=None)
    treatment.add_argument(
        "--compare-treatments",
        action="store_true",
        help="Compara raw, rules e deepseek com a mesma transcrição e sessões isoladas.",
    )
    parser.add_argument(
        "--allow-submission",
        action="store_true",
        help="Requer também submission_authorized=true no catálogo.",
    )
    add_transcription_arguments(parser)
    args = parser.parse_args(argv)
    if (args.compare_treatments or args.data_treatment is not None) and args.mode != "pipeline":
        parser.error("Seleção ou comparação de tratamentos requer --mode pipeline")
    if args.compare_treatments and args.dataset:
        parser.error("Comparação requer --cases com expected_json")
    cases_path = args.cases
    if cases_path is None and args.dataset is None:
        cases_path = PROJECT_ROOT / "evaluation/audio/cases.example.csv"
    try:
        if args.compare_treatments:
            from .comparison import compare_treatments

            asyncio.run(
                compare_treatments(
                    cases_path,
                    settings_from_arguments(args),
                    attempts=args.attempts,
                    output_directory=args.output,
                    allow_submission=args.allow_submission,
                )
            )
            return 0
        asyncio.run(
            evaluate_audio(
                cases_path,
                settings_from_arguments(args),
                mode=args.mode,
                attempts=args.attempts,
                output_directory=args.output,
                allow_submission=args.allow_submission,
                dataset_path=args.dataset,
                data_treatment=args.data_treatment,
            )
        )
        return 0
    except (FormAgentError, ValueError, OSError) as exc:
        print(f"Erro da avaliação: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130


def audio_main() -> int:
    return main(default_mode="stt")


if __name__ == "__main__":
    raise SystemExit(main())
