from dataclasses import replace

from form_agent.core.schemas import AgentResult, FilledField, FormField, FormInspection
from form_agent.evaluation.assessment import assess
from form_agent.evaluation.cases import EvaluationCase
from form_agent.evaluation.runner import score_form


def field(label, value, *, id=None):
    return FormField(label, id, id, "text", "textbox", value=value, valid=True)


def result(before, after, **kwargs):
    return AgentResult(
        "",
        FormInspection("file:///form", tuple(before)),
        (),
        False,
        False,
        final_inspection=FormInspection("file:///form", tuple(after)),
        **kwargs,
    )


def test_preexisting_values_are_scored_and_untouched_extras_are_preserved():
    before = [field("Nome", "Ana"), field("Cidade", "Quixadá")]
    assessment = assess({"Nome": "Ana"}, result(before, before))
    assert assessment.exact
    assert assessment.actual == {"Nome": "Ana"}
    assert not assessment.unexpected_changes


def test_side_effects_and_explicit_restored_extra_writes_fail():
    before = [field("Nome", ""), field("Cidade", "Quixadá")]
    after = [field("Nome", "Ana"), field("Cidade", "Fortaleza")]
    assessment = assess({"Nome": "Ana"}, result(before, after))
    assert not assessment.exact
    assert assessment.correct == 1
    assert assessment.unexpected_changes == {"Cidade": "Fortaleza"}
    restored = replace(result(before, before), filled=(FilledField("Cidade", "Quixadá", "Cidade"),))
    assert not assess({}, restored).exact


def test_missing_expected_value_is_not_a_prediction():
    state = result([field("Nome", "")], [field("Nome", "")])
    assessment = assess({"Nome": "Ana"}, state)
    assert not assessment.exact
    assert assessment.actual == {}
    assert assessment.correct == 0


def test_repeated_labels_can_be_scored_by_unique_id():
    state = result(
        [field("Nome", "", id="a"), field("Nome", "", id="b")],
        [field("Nome", "", id="a"), field("Nome", "Ana", id="b")],
    )
    assert assess({"b": "Ana"}, state).exact
    assert not assess({"Nome": "Ana"}, state).exact


def test_failed_or_unauthorized_submission_is_not_functional_success():
    case = EvaluationCase("id", "Preencha", {}, False, True)
    state = replace(result([], []), unmatched=True, submission_attempted=True)
    assert not score_form(case, 1, state, 1).functional_success
    state = replace(state, submitted=True, submission_authorized=False)
    assert not score_form(replace(case, submitted=True), 1, state, 1).functional_success


def test_max_turns_and_unknown_state_never_pass():
    case = EvaluationCase("id", "Preencha", {}, False, True)
    for state in [
        replace(result([], []), turn_limit_reached=True),
        replace(result([], []), final_inspection=None),
    ]:
        row = score_form(case, 1, state, 1)
        assert not row.passed
        assert not row.functional_success
