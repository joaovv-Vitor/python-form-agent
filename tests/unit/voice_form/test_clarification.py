import json
from dataclasses import replace

import pytest

from form_agent.core.errors import ToolClientError
from form_agent.core.schemas import AgentResult, FormField, FormInspection, RunIssue
from voice_form.clarification import ClarificationSession
from voice_form.extraction import validate_extraction
from voice_form.normalization import normalize_spoken_data


def field(ref, kind="email", **kwargs):
    return FormField(ref, ref, ref, kind, "textbox", value="", **kwargs)


class Tools:
    def __init__(self, *fields):
        self.inspection = FormInspection("file:///form", tuple(fields))
        self.calls = []
        self.side_effect = False
        self.error = None
        self.native_rejections = 0

    async def inspect_form(self):
        return self.inspection

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        assert name == "fill_field"
        fields = []
        for item in self.inspection.fields:
            if item.reference == arguments["field"]:
                item = replace(
                    item,
                    value=arguments["value"],
                    valid=not self.native_rejections,
                    validation_message="Formato exigido pelo formulário.",
                )
            elif self.side_effect:
                item = replace(item, value="alterado")
            fields.append(item)
        self.inspection = replace(self.inspection, fields=tuple(fields))
        self.native_rejections = max(0, self.native_rejections - 1)
        return {
            "success": True,
            "field": arguments["field"],
            "field_ref": arguments["field"],
            "value": arguments["value"],
        }


def initial_form(tools, **kwargs):
    return AgentResult(
        "Nenhum campo preenchido.",
        tools.inspection,
        (),
        False,
        True,
        final_inspection=tools.inspection,
        **kwargs,
    )


def session(*answers):
    prompts, notices = [], []
    iterator = iter(answers)

    async def ask(question):
        prompts.append(question)
        answer = next(iterator)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return ClarificationSession(ask, notify=notices.append), prompts, notices


async def test_conflict_is_resolved_once_and_other_data_and_evidence_are_preserved():
    tools = Tools(field("email"), replace(field("name", "text"), value="Ana"))
    normalization = normalize_spoken_data("E-mail: a@example.com. E-mail: b@example.com.")
    clarification, prompts, _ = session("c arroba example ponto com")
    unrelated = RunIssue("DATA_BLOCKED", "tool", "Ação bloqueada")
    result = await clarification.run(
        tools,
        initial_form(tools),
        (*normalization.issues, unrelated),
        normalization=normalization,
    )
    assert result.issues == (unrelated,)
    assert len(prompts) == len(tools.calls) == 1
    assert result.records[0].status == "resolved"
    assert result.records[0].value == "c@example.com"
    assert tools.inspection.fields[1].value == "Ana"
    assert result.form.filled[0].value == "c@example.com"
    assert not result.form.unmatched
    assert normalization.fields[0].status == "pending"


@pytest.mark.parametrize(
    "answer", ["85999991234", "oitenta e cinco nove nove nove nove nove um dois três quatro"]
)
async def test_invalid_answer_is_not_written_and_second_attempt_formats_phone(answer):
    tools = Tools(field("phone", "tel", required=True))
    clarification, prompts, _ = session("9999", answer)
    result = await clarification.run(tools, initial_form(tools), ())
    assert len(prompts) == 2
    assert len(tools.calls) == 1
    assert result.records[0].attempts == 2
    assert result.records[0].value == "(85) 99999-1234"
    assert result.issues == ()


@pytest.mark.parametrize(
    "answers,status",
    [
        (("PULAR",), "skipped"),
        (("ENCERRAR",), "cancelled"),
        ((EOFError(),), "cancelled"),
        (("inválido", ""), "exhausted"),
    ],
)
async def test_unresolved_field_remains_pending_without_writes(answers, status):
    tools = Tools(field("email", required=True))
    clarification, _, _ = session(*answers)
    result = await clarification.run(tools, initial_form(tools), ())
    assert result.records[0].status == status
    assert any(i.code == "DATA_PENDING" for i in result.issues)
    assert not tools.calls


async def test_optional_absent_readonly_and_disabled_fields_are_not_requested():
    tools = Tools(
        field("email"),
        field("phone", "tel", required=True, readonly=True),
        field("otherEmail", required=True, disabled=True),
        field("name", "text", required=True),
    )
    clarification, prompts, _ = session()
    result = await clarification.run(tools, initial_form(tools), ())
    assert not prompts
    assert not result.records


async def test_skipping_one_required_field_is_not_erased_by_resolving_another():
    tools = Tools(field("email", required=True), field("backupEmail", required=True))
    clarification, _, _ = session("PULAR", "b@example.com")
    result = await clarification.run(tools, initial_form(tools), ())
    assert [r.status for r in result.records] == ["skipped", "resolved"]
    assert len(result.issues) == 1
    assert result.issues[0].message.startswith("email:")


async def test_ambiguous_mapping_requires_field_choice_and_asks_other_required_field():
    tools = Tools(field("email", required=True), field("backupEmail", required=True))
    normalization = normalize_spoken_data("E-mail: incompleto")
    clarification, prompts, _ = session("2", "b@example.com", "a@example.com")
    result = await clarification.run(
        tools, initial_form(tools), normalization.issues, normalization=normalization
    )
    assert "A qual campo" in prompts[0]
    assert [r.field for r in result.records] == ["backupEmail", "email"]
    assert result.issues == ()
    assert [args["field"] for _, args in tools.calls] == ["backupEmail", "email"]


async def test_extraction_pending_uses_exact_field_and_does_not_reextract():
    tools = Tools(field("email"), field("backupEmail"))
    extraction = validate_extraction(
        json.dumps(
            {
                "fields": [
                    {
                        "field": "backupEmail",
                        "value": None,
                        "source_text": "incompleto",
                        "status": "pending",
                        "reason": "E-mail incompleto.",
                    }
                ]
            }
        ),
        "E-mail: incompleto",
        tools.inspection,
    )
    clarification, prompts, _ = session("b@example.com")
    result = await clarification.run(
        tools, initial_form(tools), extraction.issues, extraction=extraction
    )
    assert len(prompts) == 1
    assert result.issues == ()
    assert tools.inspection.fields[0].value == ""
    assert tools.inspection.fields[1].value == "b@example.com"
    assert extraction.fields[0].status == "pending"


async def test_native_validation_can_reject_a_locally_valid_answer_and_retry():
    tools = Tools(field("email", required=True))
    tools.native_rejections = 1
    clarification, _, notices = session("a@example.com", "b@example.com")
    result = await clarification.run(tools, initial_form(tools), ())
    assert result.records[0].status == "resolved"
    assert len(tools.calls) == 2
    assert "Formato exigido pelo formulário." in notices


@pytest.mark.parametrize("mode", ["side_effect", "tool_error", "false_success"])
async def test_technical_or_verification_failure_stops_questions_and_blocks_submission(mode):
    tools = Tools(field("email", required=True), replace(field("name", "text"), value="Ana"))
    if mode == "side_effect":
        tools.side_effect = True
    elif mode == "tool_error":
        tools.error = ToolClientError("offline", "TIMEOUT")
    else:

        async def no_write(*args):
            return {"success": True}

        tools.call_tool = no_write
    clarification, prompts, _ = session("a@example.com")
    result = await clarification.run(tools, initial_form(tools), ())
    assert len(prompts) == 1
    assert result.records[0].status == "failed"
    assert not result.form.verification_complete
    assert any(i.code == "DATA_PENDING" for i in result.issues)
    if mode == "side_effect":
        assert result.form.final_inspection.fields[1].value == "alterado"


async def test_form_changed_during_user_answer_is_not_written():
    tools = Tools(field("email", required=True), replace(field("name", "text"), value="Ana"))
    form = initial_form(tools)

    async def ask(question):
        tools.inspection = replace(tools.inspection, url="file:///different")
        return "a@example.com"

    result = await ClarificationSession(ask, notify=lambda _: None).run(tools, form, ())
    assert not tools.calls
    assert not result.form.verification_complete


async def test_change_between_application_and_final_review_is_not_accepted():
    class ChangingTools(Tools):
        inspections = 0

        async def inspect_form(self):
            self.inspections += 1
            if self.inspections == 4:
                self.inspection = replace(
                    self.inspection,
                    fields=(replace(self.inspection.fields[0], value="outro@example.com"),),
                )
            return self.inspection

    tools = ChangingTools(field("email", required=True))
    clarification, _, _ = session("a@example.com")
    result = await clarification.run(tools, initial_form(tools), ())
    assert result.records[0].status == "failed"
    assert not result.form.verification_complete
    assert any(i.code == "DATA_PENDING" for i in result.issues)


@pytest.mark.parametrize(
    "changes",
    [
        {"verification_complete": False},
        {"submission_attempted": True},
        {"turn_limit_reached": True},
    ],
)
async def test_uncertain_or_already_submitted_run_does_not_ask(changes):
    tools = Tools(field("email", required=True))
    clarification, prompts, _ = session()
    result = await clarification.run(tools, initial_form(tools, **changes), ())
    assert not prompts
    assert not result.records


async def test_unmapped_or_out_of_scope_source_is_preserved():
    tools = Tools(field("phone", "tel"))
    normalization = normalize_spoken_data("E-mail: incompleto. Data: amanhã.")
    clarification, prompts, _ = session()
    result = await clarification.run(
        tools, initial_form(tools), normalization.issues, normalization=normalization
    )
    assert result.issues == normalization.issues
    assert not prompts
