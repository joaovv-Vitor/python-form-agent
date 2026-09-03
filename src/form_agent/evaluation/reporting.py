"""Generate CSV and HTML evaluation reports."""

from __future__ import annotations

import csv
import html
from collections.abc import Sequence
from pathlib import Path

from .metrics import EvaluationMetrics, EvaluationRow


def write_reports(
    metrics: EvaluationMetrics,
    rows: Sequence[EvaluationRow],
    stamp: str,
    output_directory: Path,
) -> tuple[Path, Path]:
    if not rows:
        raise ValueError("Não há resultados para gerar relatórios")
    output_directory.mkdir(parents=True, exist_ok=True)
    csv_path = output_directory / f"python-evaluation-report_{stamp}.csv"
    html_path = output_directory / f"python-evaluation-report_{stamp}.html"
    metric_values = metrics.to_dict()
    row_values = [row.to_dict() for row in rows]

    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["Métrica", "Valor"])
        writer.writerows(metric_values.items())
        writer.writerow([])
        writer.writerow(row_values[0].keys())
        writer.writerows(row.values() for row in row_values)

    cards = "".join(_metric_card(name, value) for name, value in metric_values.items())
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
        "table{margin-top:20px;border-collapse:collapse;width:100%}"
        "td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}"
        "</style></head><body><main><h1>Avaliação da PoC Python</h1>"
        f"<section>{cards}</section><table><thead><tr>{headers}</tr></thead>"
        f"<tbody>{table_rows}</tbody></table></main></body></html>",
        encoding="utf-8",
    )
    return html_path, csv_path


def _metric_card(name: str, value: float | int) -> str:
    rendered = f"{value:.4f}" if isinstance(value, float) else str(value)
    return f"<article><b>{html.escape(name)}</b><strong>{rendered}</strong></article>"
