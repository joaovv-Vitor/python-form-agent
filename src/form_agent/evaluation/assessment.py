"""Compare observed native controls, including changes outside the expected fields."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.schemas import AgentResult, FormField, JsonObject


@dataclass(frozen=True, slots=True)
class FormAssessment:
    actual: JsonObject
    correct: int
    exact: bool
    unexpected_changes: JsonObject
    state_complete: bool
    validation_correct: bool


def assess(expected: JsonObject, result: AgentResult) -> FormAssessment:
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
    # Keep exact values for identity-bearing fields; no accent/case folding of names or emails.
    correct = sum(key in actual and actual[key] == value for key, value in expected.items())
    return FormAssessment(
        actual,
        correct,
        complete and valid and correct == len(expected) and not extras,
        extras,
        complete,
        valid,
    )
