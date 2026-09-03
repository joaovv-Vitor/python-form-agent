from pathlib import Path

from python_poc.agent import submission_requested
from python_poc.evaluation import calculate, load_cases
from python_poc.metrics import EvaluationMetrics


def test_submission_guard():
    assert submission_requested("Envie o formulário")
    assert not submission_requested("Não envie o formulário")
    assert not submission_requested("Não quero que você envie o formulário")


def test_csv_catalog():
    cases = load_cases(Path(__file__).resolve().parents[1] / "evaluation/cases.csv")
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
