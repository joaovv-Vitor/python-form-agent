"""Load and validate evaluation cases from CSV files."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .schemas import JsonObject

FIELD_MAP = {
    "fullName": "Nome completo",
    "email": "E-mail",
    "phone": "Telefone",
    "birthDate": "Data de nascimento",
    "city": "Cidade",
    "state": "Estado",
    "acceptTerms": "Aceito os termos",
}
REQUIRED_COLUMNS = {"id", "instruction", "submitted", "unmatched"}


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    id: str
    instruction: str
    expected: JsonObject
    submitted: bool
    unmatched: bool


def parse_boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "sim", "1"}:
        return True
    if normalized in {"false", "não", "nao", "0"}:
        return False
    raise ValueError(f"Booleano inválido: {value}")


def load_cases(path: Path) -> list[EvaluationCase]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            columns = set(reader.fieldnames or [])
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise ValueError(f"Colunas obrigatórias ausentes: {', '.join(sorted(missing))}")
            rows = list(reader)
    except FileNotFoundError as exc:
        raise ValueError(f"Arquivo de casos não encontrado: {path}") from exc

    if not rows:
        raise ValueError("O CSV não contém casos")

    ids: set[str] = set()
    cases: list[EvaluationCase] = []
    for line, row in enumerate(rows, 2):
        case_id = (row.get("id") or "").strip()
        instruction = (row.get("instruction") or "").strip()
        if not case_id or not instruction:
            raise ValueError(f"id/instruction ausente na linha {line}")
        if case_id in ids:
            raise ValueError(f"id duplicado: {case_id}")
        ids.add(case_id)

        expected: JsonObject = {}
        for column, field_name in FIELD_MAP.items():
            raw_value = (row.get(column) or "").strip()
            if raw_value:
                expected[field_name] = (
                    parse_boolean(raw_value) if column == "acceptTerms" else raw_value
                )
        cases.append(
            EvaluationCase(
                id=case_id,
                instruction=instruction,
                expected=expected,
                submitted=parse_boolean(row["submitted"]),
                unmatched=parse_boolean(row["unmatched"]),
            )
        )
    return cases
