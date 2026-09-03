"""Evaluation result types and metric calculations."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from ..core.schemas import JsonObject


@dataclass(frozen=True, slots=True)
class EvaluationRow:
    id: str
    attempt: int
    passed: bool
    instruction: str
    expected_data: JsonObject
    returned_data: JsonObject
    expected_count: int
    returned: int
    correct: int
    submitted_correct: bool
    unmatched_correct: bool
    latency_ms: int
    error: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EvaluationRow:
        return cls(
            id=str(value.get("id", "")),
            attempt=int(value.get("attempt", 1)),
            passed=bool(value.get("passed", False)),
            instruction=str(value.get("instruction", "")),
            expected_data=dict(value.get("expected_data", {})),
            returned_data=dict(value.get("returned_data", {})),
            expected_count=int(value.get("expected_count", 0)),
            returned=int(value.get("returned", 0)),
            correct=int(value.get("correct", 0)),
            submitted_correct=bool(value.get("submitted_correct", False)),
            unmatched_correct=bool(value.get("unmatched_correct", False)),
            latency_ms=int(value.get("latency_ms", 0)),
            error=str(value["error"]) if value.get("error") else None,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    field_precision: float
    field_recall: float
    field_f1: float
    overall_pass_rate: float
    stable_case_rate: float
    average_latency_ms: float
    p95_latency_ms: int
    unique_cases: int
    total_attempts: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def calculate(rows: Sequence[EvaluationRow | Mapping[str, Any]]) -> EvaluationMetrics:
    normalized = [
        row if isinstance(row, EvaluationRow) else EvaluationRow.from_mapping(row) for row in rows
    ]
    if not normalized:
        raise ValueError("Não há resultados para calcular métricas")

    correct = sum(row.correct for row in normalized)
    returned = sum(row.returned for row in normalized)
    expected = sum(row.expected_count for row in normalized)
    precision = correct / returned if returned else 1.0
    recall = correct / expected if expected else 1.0
    latencies = sorted(row.latency_ms for row in normalized)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    case_ids = {row.id for row in normalized}
    stable = sum(all(row.passed for row in normalized if row.id == case_id) for case_id in case_ids)
    return EvaluationMetrics(
        field_precision=precision,
        field_recall=recall,
        field_f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        overall_pass_rate=sum(row.passed for row in normalized) / len(normalized),
        stable_case_rate=stable / len(case_ids),
        average_latency_ms=statistics.mean(latencies),
        p95_latency_ms=latencies[p95_index],
        unique_cases=len(case_ids),
        total_attempts=len(normalized),
    )
