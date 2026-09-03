import asyncio
from types import SimpleNamespace

import pytest

from form_agent.bootstrap import Application
from form_agent.config import PROJECT_ROOT
from form_agent.evaluation.cases import load_cases
from form_agent.evaluation.metrics import EvaluationMetrics, calculate


def test_csv_catalog():
    cases = load_cases(PROJECT_ROOT / "evaluation/cases.csv")
    assert len(cases) >= 3
    assert {case.id for case in cases} >= {"joao_completo", "maria_envio", "vinicios_parcial"}


def test_metrics_multiple_attempts():
    base = {
        "id": "a",
        "latency_ms": 100,
        "expected_count": 1,
        "returned": 1,
        "correct": 1,
        "passed": True,
    }
    failed = {**base, "latency_ms": 200, "correct": 0, "passed": False}
    metrics = calculate([base, failed])
    assert isinstance(metrics, EvaluationMetrics)
    assert metrics.overall_pass_rate == 0.5
    assert metrics.stable_case_rate == 0
    assert metrics.total_attempts == 2


@pytest.mark.asyncio
async def test_cleanup_continues_after_mcp_cancellation():
    closed: list[str] = []

    class CancelledClient:
        async def close(self) -> None:
            closed.append("client")
            raise asyncio.CancelledError

    class Model:
        async def close(self) -> None:
            closed.append("model")

    application = Application(
        config=SimpleNamespace(),
        agent=SimpleNamespace(),
        client=CancelledClient(),
        model=Model(),
    )
    await application.close()

    assert closed == ["model", "client"]
