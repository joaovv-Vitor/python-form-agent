"""Load and validate evaluation cases from CSV files."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from ..core.schemas import JsonObject

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
    submission_authorized: bool = False
    form_url: str | None = None
    audio_file: Path | None = None
    speaker: str = ""
    scenario: str = ""
    difficulty: str = ""


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
                submission_authorized=parse_boolean(row.get("submission_authorized") or "false"),
                form_url=resolve_form(row.get("form") or "", path.parent),
            )
        )
    return cases


def resolve_form(value: str, directory: Path) -> str | None:
    if not value.strip():
        return None
    if value.startswith(("https://", "http://", "file://")):
        return value
    return (directory / value).resolve().as_uri()


def load_audio_cases(path: Path) -> list[EvaluationCase]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "case_id",
            "audio_file",
            "reference_text",
            "expected_json",
            "submitted",
            "unmatched",
        }
        if missing := required - set(reader.fieldnames or []):
            raise ValueError(f"Colunas de áudio ausentes: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError("O CSV de áudio não contém casos")
    cases: list[EvaluationCase] = []
    ids: set[str] = set()
    for line, row in enumerate(rows, 2):
        case_id = (row.get("case_id") or "").strip()
        audio = (row.get("audio_file") or "").strip()
        if not case_id or case_id in ids or not audio:
            raise ValueError(f"ID/áudio ausente ou ID duplicado na linha {line}")
        ids.add(case_id)
        expected = json.loads(row["expected_json"])
        if not isinstance(expected, dict) or any(
            not isinstance(key, str) or not isinstance(value, str | bool)
            for key, value in expected.items()
        ):
            raise ValueError(
                f"expected_json deve mapear campos para strings/booleanos na linha {line}"
            )
        # An empty reference is allowed for dedicated silence tests; WER/CER are undefined.
        cases.append(
            EvaluationCase(
                id=case_id,
                instruction=row.get("reference_text") or "",
                expected=expected,
                submitted=parse_boolean(row["submitted"]),
                unmatched=parse_boolean(row["unmatched"]),
                submission_authorized=parse_boolean(row.get("submission_authorized") or "false"),
                form_url=resolve_form(row.get("form") or "", path.parent),
                audio_file=(path.parent / audio).resolve(),
                speaker=row.get("speaker") or "",
                scenario=row.get("scenario") or "",
                difficulty=row.get("difficulty") or "",
            )
        )
    return cases
