"""Generate CSV and HTML evaluation reports."""

from __future__ import annotations

import csv
import html
from collections.abc import Mapping, Sequence
from pathlib import Path

from .metrics import EvaluationMetrics, EvaluationRow

PRIMARY_METRIC_LABELS = {
    "field_accuracy_rate": "Taxa de acerto por campo",
    "complete_success_rate": "Taxa de sucesso completo",
    "wer": "WER",
    "operational_failure_rate": "Taxa de falhas operacionais",
}


def _metric_label(name: str) -> str:
    condition, separator, key = name.rpartition(".")
    label = PRIMARY_METRIC_LABELS.get(key, key)
    return f"{condition}: {label}" if separator else label


def write_reports(
    metrics: EvaluationMetrics | Mapping[str, float | int],
    rows: Sequence[EvaluationRow],
    stamp: str,
    output_directory: Path,
) -> tuple[Path, Path]:
    if not rows:
        raise ValueError("Não há resultados para gerar relatórios")
    output_directory.mkdir(parents=True, exist_ok=True)
    csv_path = output_directory / f"python-evaluation-report_{stamp}.csv"
    html_path = output_directory / f"python-evaluation-report_{stamp}.html"
    metric_values = metrics.to_dict() if isinstance(metrics, EvaluationMetrics) else dict(metrics)
    primary = {
        name: value
        for key in PRIMARY_METRIC_LABELS
        for name, value in metric_values.items()
        if name.rsplit(".", 1)[-1] == key
    }
    additional = {name: value for name, value in metric_values.items() if name not in primary}
    row_values = [row.to_dict() for row in rows]

    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["Métrica", "Valor", "Identificador"])
        writer.writerows(
            (_metric_label(name), value, name)
            for name, value in (*primary.items(), *additional.items())
        )
        writer.writerow([])
        writer.writerow(row_values[0].keys())
        writer.writerows(row.values() for row in row_values)

    cards = "".join(_metric_card(name, value) for name, value in primary.items())
    extra_cards = "".join(_metric_card(name, value) for name, value in additional.items())
    headers = "".join(f"<th>{html.escape(name)}</th>" for name in row_values[0])
    table_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row.values()) + "</tr>"
        for row in row_values
    )
    html_path.write_text(
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Métricas Python</title><style>"
        "body{font:15px system-ui;background:#f3f6fb;padding:30px}"
        "main{max-width:1200px;margin:auto}section{display:grid;"
        "grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}"
        "article,table{background:white;padding:16px;border-radius:10px}"
        "strong{display:block;font-size:24px;color:#155e75;margin-top:8px}"
        "table{margin-top:20px;border-collapse:collapse;width:100%}.results{overflow-x:auto}"
        "td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}"
        "</style></head><body><main><h1>Avaliação da PoC Python</h1>"
        f"<h2>Métricas principais</h2><section>{cards}</section>"
        "<p>As métricas principais são exibidas em porcentagem; o CSV preserva as razões numéricas. "
        "WER exige transcrição e referência não vazia.</p>"
        f"<h2>Métricas complementares</h2><section>{extra_cards}</section>"
        f'<div class="results"><table><thead><tr>{headers}</tr></thead>'
        f"<tbody>{table_rows}</tbody></table></div></main></body></html>",
        encoding="utf-8",
    )
    return html_path, csv_path


def _metric_card(name: str, value: float | int) -> str:
    key = name.rsplit(".", 1)[-1]
    rendered = (
        f"{value:.2%}"
        if key in PRIMARY_METRIC_LABELS
        else f"{value:.4f}"
        if isinstance(value, float)
        else str(value)
    )
    return (
        f"<article><b>{html.escape(_metric_label(name))}</b><strong>{rendered}</strong></article>"
    )
