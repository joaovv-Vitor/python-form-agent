from dataclasses import replace

from form_agent.core.schemas import AgentResult, FilledField, FormField, FormInspection, RunIssue
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
    assert assessment.matches
    assert assessment.actual == {"Nome": "Ana"}
    assert not assessment.unexpected_changes


def test_side_effects_and_explicit_restored_extra_writes_fail():
    before = [field("Nome", ""), field("Cidade", "Quixadá")]
    after = [field("Nome", "Ana"), field("Cidade", "Fortaleza")]
    assessment = assess({"Nome": "Ana"}, result(before, after))
    assert not assessment.matches
    assert assessment.correct == 1
    assert assessment.unexpected_changes == {"Cidade": "Fortaleza"}
    restored = replace(result(before, before), filled=(FilledField("Cidade", "Quixadá", "Cidade"),))
    assert not assess({}, restored).matches


def test_missing_expected_value_is_not_a_prediction():
    state = result([field("Nome", "")], [field("Nome", "")])
    assessment = assess({"Nome": "Ana"}, state)
    assert not assessment.matches
    assert assessment.actual == {}
    assert assessment.correct == 0


def test_repeated_labels_can_be_scored_by_unique_id():
    state = result(
        [field("Nome", "", id="a"), field("Nome", "", id="b")],
        [field("Nome", "", id="a"), field("Nome", "Ana", id="b")],
    )
    assert assess({"b": "Ana"}, state).matches
    assert not assess({"Nome": "Ana"}, state).matches


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


def test_recovered_tool_error_and_wrong_values_are_not_operational_interruptions():
    case = EvaluationCase("id", "Preencha", {"Nome": "Ana"}, False, False)
    before = [field("Nome", "")]
    recovered = RunIssue("TOOL_ERROR", "tool", "Erro temporário", "fill_field")
    state = result(before, [field("Nome", "Ana")], issues=(recovered,))
    row = score_form(case, 1, state, 1)
    assert row.functional_success
    assert not row.operational_failure
    wrong = score_form(
        case,
        1,
        replace(state, final_inspection=FormInspection("file:///form", (field("Nome", "Bia"),))),
        1,
    )
    assert not wrong.functional_success
    assert not wrong.operational_failure


def test_technical_failure_preventing_final_verification_is_operational():
    case = EvaluationCase("id", "Preencha", {"Nome": "Ana"}, False, False)
    state = result(
        [field("Nome", "")],
        [field("Nome", "Ana")],
        verification_complete=False,
        issues=(RunIssue("TIMEOUT", "verification", "Falha ao reler", "read_field"),),
    )
    row = score_form(case, 1, state, 1)
    assert not row.functional_success
    assert row.operational_failure


def test_technical_failure_stopping_submission_is_operational():
    case = EvaluationCase("id", "Envie", {}, True, False)
    state = result(
        [],
        [],
        submission_attempted=True,
        submission_authorized=True,
        issues=(RunIssue("BROWSER_ERROR", "tool", "Falha ao enviar", "click_button"),),
    )
    row = score_form(case, 1, state, 1)
    assert not row.functional_success
    assert row.operational_failure


def test_tolerant_success_preserves_raw_values_and_records_presentation():
    case = EvaluationCase(
        "id", "Preencha", {"CPF": "638.451.920-89", "Objetivo": "Visitar o museu"}, False, False
    )
    state = result(
        [field("CPF", ""), field("Objetivo", "")],
        [field("CPF", "63845192089"), field("Objetivo", "visitar o museu.")],
    )
    row = score_form(case, 1, state, 0)
    assert row.functional_success
    assert row.correct == 2
    assert row.returned_data["CPF"] == "63845192089"
    assert row.comparison_version == "field-aware-v1"
    assert row.presentation_differences["CPF"]["rule"] == "identifier_digits"
    assert (
        row.presentation_differences["Objetivo"]["rule"] == "text_case_spaces_terminal_punctuation"
    )
    assert not assess(case.expected, state, policy="exact-v1").matches
    altered = replace(
        state,
        final_inspection=FormInspection(
            "file:///form", (*state.final_inspection.fields, field("Extra", "Alterado"))
        ),
    )
    assert not score_form(case, 1, altered, 0).functional_success
