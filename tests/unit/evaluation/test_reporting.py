import csv

from form_agent.evaluation.metrics import EvaluationMetrics, EvaluationRow
from form_agent.evaluation.reporting import write_reports


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
    metrics = EvaluationMetrics(
        1,
        0.5,
        0.5,
        0.25,
        0,
        100,
        100,
        1,
        4,
        complete_success_rate=0.25,
        operational_failure_rate=0.5,
        operational_failures=2,
    )
    html_path, csv_path = write_reports({**metrics.to_dict(), "wer": 2.0}, [row], "stamp", tmp_path)
    assert html_path.exists()
    assert csv_path.exists()
    assert "Avaliação da PoC Python" in html_path.read_text(encoding="utf-8")
    report = html_path.read_text(encoding="utf-8")
    for label in (
        "Taxa de acerto por campo",
        "Taxa de sucesso completo",
        "WER",
        "Taxa de falhas operacionais",
    ):
        assert label in report
    assert "50.00%" in report
    assert "25.00%" in report
    assert "200.00%" in report  # WER can exceed 100%.
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        summary = list(csv.reader(stream, delimiter=";"))[:5]
    assert summary == [
        ["Métrica", "Valor", "Identificador"],
        ["Taxa de acerto por campo", "0.5", "field_accuracy_rate"],
        ["Taxa de sucesso completo", "0.25", "complete_success_rate"],
        ["WER", "2.0", "wer"],
        ["Taxa de falhas operacionais", "0.5", "operational_failure_rate"],
    ]
    _, comparison_path = write_reports(
        {"rules.complete_success_rate": 0.25}, [row], "paired", tmp_path
    )
    assert (
        "rules: Taxa de sucesso completo;0.25;rules.complete_success_rate"
        in comparison_path.read_text(encoding="utf-8-sig")
    )
