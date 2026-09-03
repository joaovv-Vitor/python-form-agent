from python_poc.metrics import EvaluationMetrics, EvaluationRow
from python_poc.reporting import write_reports


def test_writes_csv_and_html_reports(tmp_path):
    row = EvaluationRow(
        id="case",
        attempt=1,
        passed=True,
        instruction="Preencha",
        expected_data={"Nome": "João"},
        returned_data={"Nome": "João"},
        expected_count=1,
        returned=1,
        correct=1,
        submitted_correct=True,
        unmatched_correct=True,
        latency_ms=100,
    )
    metrics = EvaluationMetrics(1, 1, 1, 1, 1, 100, 100, 1, 1)
    html_path, csv_path = write_reports(metrics, [row], "stamp", tmp_path)
    assert html_path.exists()
    assert csv_path.exists()
    assert "Avaliação da PoC Python" in html_path.read_text(encoding="utf-8")
