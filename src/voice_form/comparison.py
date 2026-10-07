"""Paired comparison: one STT result, three independent form sessions per attempt."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from audio_agent.agent import AudioAgent
from audio_agent.engines import FasterWhisperSpeechToTextEngine
from audio_agent.exceptions import AudioAgentError
from audio_agent.models import TranscriptionResult, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.bootstrap import create_application
from form_agent.config import PROJECT_ROOT, load_browser_config
from form_agent.core.errors import FormAgentError, error_code
from form_agent.evaluation.cases import load_audio_cases
from form_agent.evaluation.metrics import EvaluationRow
from form_agent.evaluation.reporting import write_reports
from form_agent.evaluation.runner import failure_row
from form_agent.evaluation.speech_metrics import (
    NORMALIZATION_VERSION,
    real_time_factor,
    score_transcript,
)
from form_agent.experiments import RunTrace, metadata

from .evaluation import run_audio_attempt, summarize
from .extraction import create_extractor
from .normalization import DATA_NORMALIZATION_VERSION
from .pipeline import DataTreatment

CONDITIONS: tuple[DataTreatment, ...] = ("raw", "rules", "deepseek")


def summarize_comparison(rows: Sequence[EvaluationRow]) -> dict[str, float | int]:
    summary: dict[str, float | int] = {
        "pairs": len({row.pair_id for row in rows}),
        "total_condition_attempts": len(rows),
    }
    for condition in CONDITIONS:
        group = [row for row in rows if row.data_treatment == condition]
        if not group:
            continue
        metrics = summarize(group)
        metrics.update(
            {
                "wrong_filled_values": sum(
                    sum(
                        key in row.returned_data and row.returned_data[key] != value
                        for key, value in row.expected_data.items()
                    )
                    for row in group
                ),
                "omitted_values": sum(
                    sum(key not in row.returned_data for key in row.expected_data) for row in group
                ),
                "pending_fields": sum(len(row.pending_fields) for row in group),
                "unexpected_changed_fields": sum(len(row.unexpected_changes) for row in group),
                "extraction_prompt_tokens_reported": sum(
                    row.extraction_prompt_tokens or 0 for row in group
                ),
                "extraction_completion_tokens_reported": sum(
                    row.extraction_completion_tokens or 0 for row in group
                ),
            }
        )
        post = [row.post_stt_seconds for row in group if row.post_stt_seconds is not None]
        if post:
            metrics["average_post_stt_seconds"] = sum(post) / len(post)
        summary.update({f"{condition}.{key}": value for key, value in metrics.items()})
    return summary


async def compare_treatments(
    cases_path: Path,
    settings: TranscriptionSettings,
    *,
    attempts: int = 1,
    output_directory: Path = PROJECT_ROOT / "reports/comparison",
    allow_submission: bool = False,
) -> tuple[dict[str, float | int], tuple[Path, Path]]:
    if attempts <= 0:
        raise ValueError("attempts deve ser maior que zero")
    cases = load_audio_cases(cases_path)
    if any(not case.instruction.strip() for case in cases):
        print("Aviso: há referências vazias; WER/CER serão indefinidos nesses casos.")
    extractor = create_extractor()
    rows: list[EvaluationRow] = []
    try:
        audio = AudioAgent(AudioPreprocessor(), FasterWhisperSpeechToTextEngine())
        for case_index, case in enumerate(cases):
            for attempt in range(1, attempts + 1):
                pair_id = uuid4().hex
                offset = (case_index * attempts + attempt - 1) % len(CONDITIONS)
                order = CONDITIONS[offset:] + CONDITIONS[:offset]
                transcription: TranscriptionResult | None = None
                stt_error: str | None = None
                stt_manifest = metadata(
                    case_file=cases_path,
                    audio_file=case.audio_file,
                    stt_settings=settings.to_dict(),
                )
                stt_manifest.update(
                    {
                        "mode": "paired_stt",
                        "pair_id": pair_id,
                        "case_id": case.id,
                        "attempt": attempt,
                        "condition_order": order,
                    }
                )
                with RunTrace(output_directory / "stt-runs", stt_manifest) as stt_trace:
                    stt_started = time.perf_counter()
                    try:
                        if case.audio_file is None:
                            raise ValueError("Áudio ausente")
                        stt_trace.emit(
                            "audio_started",
                            {"path": str(case.audio_file), "settings": settings.to_dict()},
                        )
                        transcription = await asyncio.to_thread(
                            audio.transcribe, case.audio_file, settings
                        )
                        stt_trace.emit("audio_transcribed", transcription.to_dict())
                    except (AudioAgentError, OSError, ValueError) as exc:
                        stt_error = str(exc)
                        stt_trace.emit("audio_failed", {"code": "STT_ERROR", "error": stt_error})
                    stt_elapsed = time.perf_counter() - stt_started
                    stt_trace.emit(
                        "run_completed",
                        {
                            "pair_id": pair_id,
                            "success": transcription is not None,
                            "stt_seconds": stt_elapsed,
                        },
                    )
                for execution_index, condition in enumerate(order, 1):
                    application = None
                    setup_error: Exception | None = None
                    browser = load_browser_config()
                    if case.form_url:
                        browser = replace(browser, url=case.form_url)
                    try:
                        if transcription is not None:
                            try:
                                application = create_application(browser_config=browser)
                            except Exception as exc:
                                setup_error = exc
                        manifest = metadata(
                            model=application.config if application else None,
                            browser=browser,
                            case_file=cases_path,
                            audio_file=case.audio_file,
                            stt_settings=settings.to_dict(),
                            max_turns=application.agent.max_turns if application else None,
                        )
                        manifest.update(
                            {
                                "mode": "pipeline",
                                "pair_id": pair_id,
                                "case_id": case.id,
                                "attempt": attempt,
                                "data_treatment": condition,
                                "condition_order": order,
                                "execution_index": execution_index,
                                "shared_stt_trace": str(stt_trace.path),
                                "allow_submission": allow_submission,
                                "normalization_version": NORMALIZATION_VERSION,
                                "data_normalization_version": DATA_NORMALIZATION_VERSION
                                if condition == "rules"
                                else None,
                                "extraction": extractor.manifest()
                                if condition == "deepseek"
                                else None,
                            }
                        )
                        with RunTrace(
                            output_directory / "runs",
                            manifest,
                            data_directory=output_directory / "tests",
                        ) as trace:
                            if transcription is None or setup_error is not None:
                                code = (
                                    "STT_ERROR"
                                    if transcription is None
                                    else error_code(setup_error)
                                    if isinstance(setup_error, FormAgentError)
                                    else "INTERNAL_ERROR"
                                )
                                row = failure_row(
                                    case,
                                    attempt,
                                    code,
                                    stt_error or str(setup_error),
                                    stt_elapsed,
                                    stage="stt" if transcription is None else "setup",
                                )
                                row = replace(
                                    row,
                                    mode="pipeline",
                                    run_id=trace.run_id,
                                    trace_path=str(trace.path),
                                    data_treatment=condition,
                                    pair_id=pair_id,
                                    condition_order=execution_index,
                                    stt_model=settings.model,
                                    stt_language=settings.language,
                                    stt_device=settings.device,
                                    stt_compute_type=settings.compute_type,
                                    stt_beam_size=settings.beam_size,
                                    stt_temperature=settings.temperature,
                                    stt_vad_filter=settings.vad_filter,
                                    stt_initial_prompt=settings.initial_prompt,
                                    stt_hotwords=settings.hotwords,
                                    reference_text=case.instruction,
                                    speaker=case.speaker,
                                    scenario=case.scenario,
                                )
                                if transcription:
                                    row = replace(
                                        row,
                                        transcription=transcription.text,
                                        **asdict(
                                            score_transcript(case.instruction, transcription.text)
                                        ),
                                        stt_seconds=transcription.processing_time_seconds,
                                        rtf=real_time_factor(
                                            transcription.processing_time_seconds,
                                            transcription.duration_seconds,
                                        ),
                                    )
                                    trace.emit("audio_transcribed", transcription.to_dict())
                                trace.emit("run_completed", row.to_dict())
                            else:
                                assert application is not None
                                application.agent.events = trace.emit
                                row = await run_audio_attempt(
                                    case,
                                    attempt,
                                    "pipeline",
                                    audio,
                                    settings,
                                    trace,
                                    application,
                                    allow_submission=allow_submission,
                                    data_treatment=condition,
                                    extractor=extractor if condition == "deepseek" else None,
                                    prepared_transcription=transcription,
                                    pair_id=pair_id,
                                    condition_order=execution_index,
                                )
                            rows.append(row)
                            print(
                                f"{case.id} tentativa {attempt}/{attempts} {condition}: {'PASS' if row.passed else 'FAIL'}; WER={row.wer}"
                            )
                    finally:
                        if application:
                            await application.close()
    finally:
        await extractor.close()
    summary = summarize_comparison(rows)
    stamp = f"comparison_{datetime.now(UTC).strftime('%Y-%m-%d_%H-%M-%S-%f')}"
    paths = write_reports(summary, rows, stamp, output_directory)
    print(f"Relatório HTML: {paths[0]}\nPlanilha CSV: {paths[1]}")
    return summary, paths
