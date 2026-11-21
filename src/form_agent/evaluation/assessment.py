"""Compare observed native controls, including changes outside the expected fields."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from ..core.schemas import AgentResult, FormField, JsonObject
from .comparison import COMPARISON_VERSION, ComparisonPolicy, compare_field


@dataclass(frozen=True, slots=True)
class FormAssessment:
    actual: JsonObject
    correct: int
    matches: bool
    unexpected_changes: JsonObject
    state_complete: bool
    validation_correct: bool
    presentation_differences: JsonObject = dataclass_field(default_factory=dict)


def assess(
    expected: JsonObject, result: AgentResult, *, policy: ComparisonPolicy = COMPARISON_VERSION
) -> FormAssessment:
    if result.final_inspection is None:
        return FormAssessment({}, 0, False, {}, False, False)
    before = {field.reference: field for field in result.inspection.fields}
    after = {field.reference: field for field in result.final_inspection.fields}
    complete = (
        result.verification_complete
        and len(before) == len(result.inspection.fields)
        and len(after) == len(result.final_inspection.fields)
    )
    actual: JsonObject = {}
    matched_fields: dict[str, FormField] = {}
    expected_refs: set[str] = set()
    valid = True
    for key in expected:
        prior_matches = [
            field for field in before.values() if key in {field.reference, field.label}
        ]
        if len(prior_matches) == 1:
            expected_refs.add(prior_matches[0].reference)
        matches = [field for field in after.values() if key in {field.reference, field.label}]
        if len(matches) == 1:
            field = matches[0]
            matched_fields[key] = field
            if field.value not in (None, "", False) or field.value == expected[key]:
                actual[key] = field.value
            expected_refs.add(field.reference)
            valid = valid and field.valid is not False
    extras: JsonObject = {}
    for reference in before.keys() | after.keys():
        if reference in expected_refs:
            continue
        old: FormField | None = before.get(reference)
        new: FormField | None = after.get(reference)
        changed = (old is not None and (new is None or old.value != new.value)) or (
            old is None and new is not None and new.value not in (None, "", False)
        )
        if changed:
            extras[reference] = new.value if new else None
    for written in result.filled:
        reference = written.reference or written.field
        if reference not in expected_refs:
            # Conservatively count explicit extra writes even when later restored.
            extras[reference] = written.value
    correct = 0
    presentation: JsonObject = {}
    for key, value in expected.items():
        if key not in actual:
            continue
        comparison = compare_field(key, value, actual[key], matched_fields.get(key), policy=policy)
        correct += comparison.matches
        if comparison.matches and value != actual[key]:
            presentation[key] = {"expected": value, "actual": actual[key], "rule": comparison.rule}
    return FormAssessment(
        actual,
        correct,
        complete and valid and correct == len(expected) and not extras,
        extras,
        complete,
        valid,
        presentation,
    )
