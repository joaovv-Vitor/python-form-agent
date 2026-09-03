"""Run repeatable form-agent evaluations."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path

from .agent import FormAgent
from .config import PROJECT_ROOT, load_agent_max_turns, load_model_config
from .errors import ConfigurationError, FormAgentError
from .evaluation_cases import EvaluationCase, load_cases
from .mcp_client import BrowserToolsClient
from .metrics import EvaluationMetrics, EvaluationRow, calculate
from .model import OpenAICompatibleModel
from .reporting import write_reports
from .schemas import JsonObject

# Backwards-compatible imports for users of the original single-file module.
__all__ = ["calculate", "evaluate", "load_cases", "main", "write_reports"]


def _attempts_from_environment() -> int:
    raw_value = os.getenv("EVALUATION_ATTEMPTS", "3")
    try:
        attempts = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError("EVALUATION_ATTEMPTS deve ser um número inteiro.") from exc
    if attempts <= 0:
        raise ConfigurationError("EVALUATION_ATTEMPTS deve ser maior que zero.")
    return attempts


def _compare(case: EvaluationCase, actual: JsonObject) -> tuple[int, bool]:
    correct = sum(
        str(actual.get(field_name)).casefold() == str(expected).casefold()
        for field_name, expected in case.expected.items()
    )
    exact_fields = correct == len(case.expected) == len(actual)
    return correct, exact_fields


async def _close_resources(client: BrowserToolsClient, model: OpenAICompatibleModel) -> None:
    """Close evaluation resources without letting MCP shutdown mask the result."""
    # The MCP stdio transport uses AnyIO cancel scopes while it shuts down.  Close
    # it after the model and independently: a cancellation raised by one resource
    # must not prevent the other one from being released.
    for resource in (model, client):
        try:
            await resource.close()
        except asyncio.CancelledError:
            continue
        except Exception:
            continue


async def _run_attempt(
    agent: FormAgent,
    case: EvaluationCase,
    attempt: int,
) -> EvaluationRow:
    started = time.perf_counter()
    try:
        result = await agent.run(case.instruction)
    except FormAgentError as exc:
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
            latency_ms=round((time.perf_counter() - started) * 1000),
            error=str(exc),
        )

    actual: JsonObject = {item.field: item.value for item in result.filled}
    correct, exact_fields = _compare(case, actual)
    submitted_correct = result.submitted == case.submitted
    unmatched_correct = result.unmatched == case.unmatched
    return EvaluationRow(
        id=case.id,
        attempt=attempt,
        passed=exact_fields and submitted_correct and unmatched_correct,
        instruction=case.instruction,
        expected_data=case.expected,
        returned_data=actual,
        expected_count=len(case.expected),
        returned=len(actual),
        correct=correct,
        submitted_correct=submitted_correct,
        unmatched_correct=unmatched_correct,
        latency_ms=round((time.perf_counter() - started) * 1000),
    )


async def evaluate() -> tuple[EvaluationMetrics, tuple[Path, Path]]:
    attempts = _attempts_from_environment()
    cases_path = Path(
        os.getenv("EVALUATION_CASES_FILE", str(PROJECT_ROOT / "evaluation/cases.csv"))
    )
    cases = load_cases(cases_path)
    config = load_model_config()
    client = BrowserToolsClient()
    model = OpenAICompatibleModel(config)
    agent = FormAgent(client, model, max_turns=load_agent_max_turns())
    rows: list[EvaluationRow] = []
    try:
        for case in cases:
            for attempt in range(1, attempts + 1):
                row = await _run_attempt(agent, case, attempt)
                rows.append(row)
                status = "PASS" if row.passed else "FAIL"
                suffix = f" — {row.error}" if row.error else ""
                print(f"{case.id} tentativa {attempt}/{attempts}: {status}{suffix}")
    finally:
        await _close_resources(client, model)

    metrics = calculate(rows)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]
    paths = write_reports(metrics, rows, stamp, PROJECT_ROOT / "reports")
    print(f"Relatório HTML: {paths[0]}\nPlanilha CSV: {paths[1]}")
    return metrics, paths


def main() -> None:
    try:
        asyncio.run(evaluate())
    except (ConfigurationError, ValueError) as exc:
        print(f"Erro de configuração da avaliação: {exc}")
    except KeyboardInterrupt:
        print("\nAvaliação encerrada.")


if __name__ == "__main__":
    main()
