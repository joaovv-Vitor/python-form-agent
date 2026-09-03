from __future__ import annotations

import asyncio
import csv
import html
import os
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .agent import FormAgent
from .config import load_model_config
from .mcp_client import BrowserToolsClient
from .model import OpenAICompatibleModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FIELD_MAP = {"fullName": "Nome completo", "email": "E-mail", "phone": "Telefone", "birthDate": "Data de nascimento", "city": "Cidade", "state": "Estado", "acceptTerms": "Aceito os termos"}


def boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "sim", "1"}: return True
    if normalized in {"false", "não", "nao", "0"}: return False
    raise ValueError(f"Booleano inválido: {value}")


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows: raise ValueError("O CSV não contém casos")
    ids, cases = set(), []
    for line, row in enumerate(rows, 2):
        if not row.get("id") or not row.get("instruction"): raise ValueError(f"id/instruction ausente na linha {line}")
        if row["id"] in ids: raise ValueError(f"id duplicado: {row['id']}")
        ids.add(row["id"])
        expected = {}
        for column, field in FIELD_MAP.items():
            if row.get(column, "").strip(): expected[field] = boolean(row[column]) if column == "acceptTerms" else row[column].strip()
        cases.append({"id": row["id"], "instruction": row["instruction"], "expected": expected, "submitted": boolean(row["submitted"]), "unmatched": boolean(row["unmatched"])})
    return cases


def calculate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    correct = sum(row["correct"] for row in rows); returned = sum(row["returned"] for row in rows); expected = sum(row["expected_count"] for row in rows)
    precision = correct / returned if returned else 1.0; recall = correct / expected if expected else 1.0
    latencies = sorted(row["latency_ms"] for row in rows); p95 = latencies[max(0, int(len(latencies) * .95 + .999) - 1)]
    passed = lambda row: row["passed"]
    groups = {row["id"] for row in rows}
    stable = sum(all(passed(row) for row in rows if row["id"] == case_id) for case_id in groups)
    return {"field_precision": precision, "field_recall": recall, "field_f1": 2*precision*recall/(precision+recall) if precision+recall else 0, "overall_pass_rate": sum(map(passed, rows))/len(rows), "stable_case_rate": stable/len(groups), "average_latency_ms": statistics.mean(latencies), "p95_latency_ms": p95, "unique_cases": len(groups), "total_attempts": len(rows)}


def write_reports(metrics: dict[str, Any], rows: list[dict[str, Any]], stamp: str) -> tuple[Path, Path]:
    directory = PROJECT_ROOT / "reports"; directory.mkdir(exist_ok=True)
    csv_path = directory / f"python-evaluation-report_{stamp}.csv"
    html_path = directory / f"python-evaluation-report_{stamp}.html"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";"); writer.writerow(["Métrica", "Valor"])
        writer.writerows(metrics.items()); writer.writerow([]); writer.writerow(rows[0].keys()); writer.writerows(row.values() for row in rows)
    cards = "".join(f'<article><b>{html.escape(key)}</b><strong>{value:.4f}</strong></article>' if isinstance(value, float) else f'<article><b>{html.escape(key)}</b><strong>{value}</strong></article>' for key, value in metrics.items())
    table_rows = "".join("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row.values()) + "</tr>" for row in rows)
    html_path.write_text(f'''<!doctype html><meta charset="utf-8"><title>Métricas Python</title><style>body{{font:15px system-ui;background:#f3f6fb;padding:30px}}main{{max-width:1200px;margin:auto}}section{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}article,table{{background:white;padding:16px;border-radius:10px}}strong{{display:block;font-size:24px;color:#155e75;margin-top:8px}}table{{margin-top:20px;border-collapse:collapse;width:100%}}td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}</style><main><h1>Avaliação da PoC Python</h1><section>{cards}</section><table><thead><tr>{''.join(f'<th>{html.escape(k)}</th>' for k in rows[0])}</tr></thead><tbody>{table_rows}</tbody></table></main>''', encoding="utf-8")
    return html_path, csv_path


async def evaluate() -> None:
    attempts = int(os.getenv("EVALUATION_ATTEMPTS", "3")); cases = load_cases(Path(os.getenv("EVALUATION_CASES_FILE", str(PROJECT_ROOT / "evaluation/cases.csv"))))
    config = load_model_config(); client = BrowserToolsClient(); agent = FormAgent(client, OpenAICompatibleModel(config)); rows = []
    try:
        for case in cases:
            for attempt in range(1, attempts + 1):
                started = time.perf_counter(); result = await agent.run(case["instruction"]); actual = {item["field"]: item["value"] for item in result.filled}
                correct = sum(str(actual.get(k)).lower() == str(v).lower() for k, v in case["expected"].items())
                passed = correct == len(case["expected"]) == len(actual) and result.submitted == case["submitted"] and result.unmatched == case["unmatched"]
                rows.append({"id": case["id"], "attempt": attempt, "passed": passed, "instruction": case["instruction"], "expected_data": case["expected"], "returned_data": actual, "expected_count": len(case["expected"]), "returned": len(actual), "correct": correct, "submitted_correct": result.submitted == case["submitted"], "unmatched_correct": result.unmatched == case["unmatched"], "latency_ms": round((time.perf_counter()-started)*1000)})
                print(f"{case['id']} tentativa {attempt}/{attempts}: {'PASS' if passed else 'FAIL'}")
    finally: await client.close()
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]; paths = write_reports(calculate(rows), rows, stamp)
    print(f"Relatório HTML: {paths[0]}\nPlanilha CSV: {paths[1]}")


def main() -> None: asyncio.run(evaluate())
if __name__ == "__main__": main()
