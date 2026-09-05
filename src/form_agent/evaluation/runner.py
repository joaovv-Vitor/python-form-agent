"""Run isolated form-agent evaluations and retain evidence for every attempt."""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from ..bootstrap import create_application
from ..config import PROJECT_ROOT, load_browser_config
from ..core.agent import FormAgent
from ..core.errors import ConfigurationError, FormAgentError, error_code
from ..core.schemas import AgentResult
from ..experiments import RunTrace, metadata
from .assessment import assess
from .cases import EvaluationCase, load_cases
from .metrics import EvaluationMetrics, EvaluationRow, calculate
from .reporting import write_reports

__all__ = ["calculate", "evaluate", "load_cases", "main", "write_reports"]


def _attempts_from_environment() -> int:
    try:
        attempts = int(os.getenv("EVALUATION_ATTEMPTS", "3"))
    except ValueError as exc:
        raise ConfigurationError("EVALUATION_ATTEMPTS deve ser um número inteiro.") from exc
    if attempts <= 0:
        raise ConfigurationError("EVALUATION_ATTEMPTS deve ser maior que zero.")
    return attempts


def failure_row(
    case: EvaluationCase,
    attempt: int,
    code: str,
    message: str,
    elapsed: float,
    *,
    stage: str = "form",
) -> EvaluationRow:
    return EvaluationRow(
        id=case.id,
        attempt=attempt,
        passed=False,
        instruction=case.instruction,
        expected_data=case.expected,
        returned_data={},
        expected_count=len(case.expected),
        returned=0,
        correct=0,
        submitted_correct=False,
        unmatched_correct=False,
        latency_ms=round(elapsed * 1000),
        error=message,
        error_codes=(code,),
        failure_stage=stage,
        total_seconds=elapsed,
    )


def score_form(
    case: EvaluationCase, attempt: int, result: AgentResult, elapsed: float
) -> EvaluationRow:
    assessment = assess(case.expected, result)
    submitted_correct = (
        result.submitted and result.submission_authorized
        if case.submitted
        else not result.submitted and not result.submission_attempted
    )
    unmatched_correct = result.unmatched == case.unmatched
    functional_success = assessment.exact and submitted_correct and not result.turn_limit_reached
    codes = list(dict.fromkeys(issue.code for issue in result.issues))
    if not assessment.state_complete and "VERIFICATION_ERROR" not in codes:
        codes.append("VERIFICATION_ERROR")
    if not assessment.validation_correct and "VALIDATION_ERROR" not in codes:
        codes.append("VALIDATION_ERROR")
    if not submitted_correct and not any(code.startswith("SUBMISSION_") for code in codes):
        codes.append("SUBMISSION_ERROR")
    if not assessment.exact and not codes:
        # This is observed disagreement, not evidence of a semantic or STT root cause.
        codes.append("OUTCOME_MISMATCH")
    return EvaluationRow(
        id=case.id,
        attempt=attempt,
        passed=functional_success and unmatched_correct,
        instruction=case.instruction,
        expected_data=case.expected,
        returned_data=assessment.actual,
        expected_count=len(case.expected),
        returned=len(assessment.actual) + len(assessment.unexpected_changes),
        correct=assessment.correct,
        submitted_correct=submitted_correct,
        unmatched_correct=unmatched_correct,
        latency_ms=round(elapsed * 1000),
        functional_success=functional_success,
        error_codes=tuple(codes),
        unexpected_changes=assessment.unexpected_changes,
        failure_stage=None if functional_success and unmatched_correct else "outcome",
        form_seconds=elapsed,
        total_seconds=elapsed,
        submission_attempted=result.submission_attempted,
        submission_authorized=result.submission_authorized,
        submitted=result.submitted,
    )


async def _run_attempt(
    agent: FormAgent,
    case: EvaluationCase,
    attempt: int,
    *,
    authorize_submission: bool = False,
) -> EvaluationRow:
    started = time.perf_counter()
    if not case.instruction.strip():
        return failure_row(
            case, attempt, "INPUT_ERROR", "Referência vazia para o Form Agent", 0, stage="input"
        )
    try:
        result = await agent.run(case.instruction, authorize_submission=authorize_submission)
    except FormAgentError as exc:
        return failure_row(case, attempt, error_code(exc), str(exc), time.perf_counter() - started)
    return score_form(case, attempt, result, time.perf_counter() - started)


async def evaluate(
    *,
    cases_path: Path | None = None,
    attempts: int | None = None,
    output_directory: Path | None = None,
    allow_submission: bool = False,
) -> tuple[EvaluationMetrics, tuple[Path, Path]]:
    attempts = _attempts_from_environment() if attempts is None else attempts
    if attempts <= 0:
        raise ValueError("attempts deve ser maior que zero")
    cases_path = cases_path or Path(
        os.getenv("EVALUATION_CASES_FILE", str(PROJECT_ROOT / "evaluation/cases.csv"))
    )
    output_directory = output_directory or PROJECT_ROOT / "reports"
    cases = load_cases(cases_path)
    rows: list[EvaluationRow] = []
    for case in cases:
        for attempt in range(1, attempts + 1):
            browser = load_browser_config()
            if case.form_url:
                browser = replace(browser, url=case.form_url)
            application = create_application(browser_config=browser)
            try:
                manifest = metadata(
                    model=application.config,
                    browser=browser,
                    case_file=cases_path,
                    max_turns=application.agent.max_turns,
                )
                manifest.update(
                    {
                        "mode": "text",
                        "case_id": case.id,
                        "attempt": attempt,
                        "allow_submission": allow_submission,
                    }
                )
                with RunTrace(output_directory / "runs", manifest) as trace:
                    application.agent.events = trace.emit
                    authorized = allow_submission and case.submission_authorized
                    started = time.perf_counter()
                    try:
                        await application.client.set_submission_authorized(authorized)
                        row = await _run_attempt(
                            application.agent, case, attempt, authorize_submission=authorized
                        )
                    except Exception as exc:
                        row = failure_row(
                            case,
                            attempt,
                            error_code(exc)
                            if isinstance(exc, FormAgentError)
                            else "INTERNAL_ERROR",
                            str(exc),
                            time.perf_counter() - started,
                        )
                    row = replace(
                        row,
                        run_id=trace.run_id,
                        trace_path=str(trace.path),
                        total_seconds=time.perf_counter() - started,
                        latency_ms=round((time.perf_counter() - started) * 1000),
                    )
                    trace.emit("run_completed", row.to_dict())
                    rows.append(row)
                    print(
                        f"{case.id} tentativa {attempt}/{attempts}: {'PASS' if row.passed else 'FAIL'}"
                    )
            finally:
                await application.close()
    metrics = calculate(rows)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S-%f")
    paths = write_reports(metrics, rows, stamp, output_directory)
    print(f"Relatório HTML: {paths[0]}\nPlanilha CSV: {paths[1]}")
    return metrics, paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Avalia o Form Agent com uma sessão isolada por tentativa."
    )
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--attempts", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-submission",
        action="store_true",
        help="Habilita apenas os casos com submission_authorized=true.",
    )
    arguments = parser.parse_args()
    try:
        asyncio.run(
            evaluate(
                cases_path=arguments.cases,
                attempts=arguments.attempts,
                output_directory=arguments.output,
                allow_submission=arguments.allow_submission,
            )
        )
        return 0
    except (FormAgentError, ValueError, OSError) as exc:
        print(f"Erro da avaliação: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
