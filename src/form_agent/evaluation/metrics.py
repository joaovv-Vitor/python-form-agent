"""Evaluation result types and metric calculations."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.schemas import JsonObject
from .comparison import COMPARISON_VERSION

OPERATIONAL_ERROR_CODES = frozenset(
    {
        "STT_ERROR",
        "PROVIDER_ERROR",
        "TOOL_ERROR",
        "BROWSER_ERROR",
        "TIMEOUT",
        "INTERNAL_ERROR",
        "EXTRACTION_ERROR",
    }
)


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
    functional_success: bool = False
    error_codes: tuple[str, ...] = ()
    unexpected_changes: JsonObject = field(default_factory=dict)
    run_id: str = ""
    mode: str = "text"
    trace_path: str = ""
    failure_stage: str | None = None
    reference_text: str | None = None
    transcription: str | None = None
    word_edits: int | None = None
    reference_words: int | None = None
    character_edits: int | None = None
    reference_characters: int | None = None
    wer: float | None = None
    cer: float | None = None
    stt_seconds: float | None = None
    form_seconds: float | None = None
    total_seconds: float = 0.0
    rtf: float | None = None
    speaker: str = ""
    scenario: str = ""
    stt_model: str = ""
    stt_language: str | None = None
    stt_device: str = ""
    stt_compute_type: str = ""
    stt_beam_size: int | None = None
    stt_temperature: float | None = None
    stt_vad_filter: bool = False
    stt_initial_prompt: str | None = None
    stt_hotwords: str | None = None
    submission_attempted: bool = False
    submission_authorized: bool = False
    submitted: bool = False
    normalized_instruction: str | None = None
    data_normalization_version: str | None = None
    normalization_seconds: float | None = None
    data_treatment: str = ""
    pair_id: str = ""
    condition_order: int | None = None
    extraction_seconds: float | None = None
    extraction_version: str | None = None
    extraction_prompt_tokens: int | None = None
    extraction_completion_tokens: int | None = None
    pending_fields: tuple[str, ...] = ()
    post_stt_seconds: float | None = None
    operational_failure: bool = False
    comparison_version: str = COMPARISON_VERSION
    presentation_differences: JsonObject = field(default_factory=dict)

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
            functional_success=bool(value.get("functional_success", False)),
            error_codes=tuple(value.get("error_codes", ())),
            failure_stage=value.get("failure_stage"),
            operational_failure=bool(value.get("operational_failure", False)),
            comparison_version=str(value.get("comparison_version", "exact-v1")),
            presentation_differences=dict(value.get("presentation_differences", {})),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    field_precision: float
    field_accuracy_rate: float
    field_f1: float
    overall_pass_rate: float
    stable_case_rate: float
    average_latency_ms: float
    p95_latency_ms: int
    unique_cases: int
    total_attempts: int
    complete_success_rate: float = 0.0
    operational_failure_rate: float = 0.0
    operational_failures: int = 0

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
        field_accuracy_rate=recall,
        field_f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        overall_pass_rate=sum(row.passed for row in normalized) / len(normalized),
        stable_case_rate=stable / len(case_ids),
        average_latency_ms=statistics.mean(latencies),
        p95_latency_ms=latencies[p95_index],
        unique_cases=len(case_ids),
        total_attempts=len(normalized),
        complete_success_rate=sum(row.functional_success for row in normalized) / len(normalized),
        operational_failure_rate=sum(row.operational_failure for row in normalized)
        / len(normalized),
        operational_failures=sum(row.operational_failure for row in normalized),
    )
