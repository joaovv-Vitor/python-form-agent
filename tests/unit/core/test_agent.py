from collections.abc import Sequence

import pytest

from form_agent.core.agent import FormAgent, submission_requested
from form_agent.core.schemas import (
    FormField,
    FormInspection,
    JsonObject,
    ToolCall,
    ToolCompletion,
    ToolDefinition,
)


def test_submission_guard():
    assert submission_requested("Envie o formulário")
    assert not submission_requested("Não envie o formulário")
    assert not submission_requested("Não quero que você envie o formulário")


class FakeTools:
    def __init__(self):
        self.calls: list[tuple[str, JsonObject]] = []

    async def list_tools(self):
        schema = {"type": "object"}
        return [
            ToolDefinition("fill_field", "fill", schema),
            ToolDefinition("read_field", "read", schema),
            ToolDefinition("click_button", "click", schema),
        ]

    async def inspect_form(self):
        return FormInspection(
            url="file:///form.html",
            fields=(FormField("Nome completo", "fullName", "fullName", "text", "textbox"),),
        )

    async def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        self.calls.append((name, arguments))
        if name == "fill_field":
            return {"success": True, "field": "Nome completo", "value": arguments["value"]}
        if name == "read_field":
            return {"success": True, "field": "Nome completo", "value": "João"}
        return {"success": True, "button": "Enviar"}

    async def close(self):
        return None


class FakeSession:
    def __init__(self, batches: list[list[ToolCall]]):
        self.batches = iter(batches)
        self.completed: list[ToolCompletion] = []

    async def next(self, completed: Sequence[ToolCompletion]):
        self.completed.extend(completed)
        return next(self.batches, [])


class FakeModel:
    def __init__(self, batches):
        self.session = FakeSession(batches)

    def create_session(self, instruction, inspection, tools):
        return self.session

    async def close(self):
        return None


@pytest.mark.parametrize(
    "arguments",
    [
        {"field": "fullName", "value": "Maria"},
        {"field": "unknown", "value": "João"},
        {"field": "fullName", "value": "João"},
    ],
)
async def test_host_plan_blocks_unapproved_fields_and_values(arguments):
    tools = FakeTools()
    model = FakeModel([[ToolCall("1", "fill_field", arguments)], []])
    # Empty plan must prohibit all writes, even when the value looks reasonable.
    result = await FormAgent(tools, model).run("Dados validados: {}", field_values={})
    assert not any(name == "fill_field" for name, _ in tools.calls)
    assert result.issues[0].code == "DATA_BLOCKED"


async def test_omitted_validated_fields_fail_plan_verification():
    result = await FormAgent(FakeTools(), FakeModel([[]])).run(
        "Preencha João", field_values={"fullName": "João"}
    )
    assert not result.verification_complete
    assert result.issues[0].code == "EXTRACTION_APPLY_ERROR"


async def test_wrong_candidate_is_blocked_even_for_an_allowed_field():
    tools = FakeTools()
    result = await FormAgent(
        tools,
        FakeModel([[ToolCall("1", "fill_field", {"field": "fullName", "value": "Maria"})], []]),
    ).run("Preencha João", field_values={"fullName": "João"})
    assert not any(name == "fill_field" for name, _ in tools.calls)
    assert not result.verification_complete
    assert {issue.code for issue in result.issues} == {"DATA_BLOCKED", "EXTRACTION_APPLY_ERROR"}


@pytest.mark.asyncio
async def test_fills_and_confirms_field():
    tools = FakeTools()
    model = FakeModel(
        [[ToolCall("1", "fill_field", {"field": "Nome completo", "value": "João"})], []]
    )
    result = await FormAgent(tools, model).run("Meu nome é João")
    assert result.filled[0].field == "Nome completo"
    assert result.filled[0].value == "João"
    assert ("read_field", {"field": "Nome completo"}) in tools.calls
    assert result.submitted is False


@pytest.mark.asyncio
async def test_blocks_submission_without_explicit_authorization():
    tools = FakeTools()
    model = FakeModel([[ToolCall("1", "click_button", {"button": "Enviar"})], []])
    result = await FormAgent(tools, model).run("Preencha o formulário")
    assert result.submitted is False
    assert all(name != "click_button" for name, _ in tools.calls)
    assert model.session.completed[0].output["success"] is False


@pytest.mark.asyncio
async def test_reports_turn_limit():
    tools = FakeTools()
    model = FakeModel([[ToolCall("1", "unknown", {})]])
    result = await FormAgent(tools, model, max_turns=1).run("Preencha o formulário")
    assert result.turn_limit_reached is True
    assert "limite de interações" in result.message


@pytest.mark.parametrize(
    "instruction",
    [
        "Pode preencher e enviar.",
        "Talvez eu queira enviar amanhã.",
        "A mensagem deve conter a palavra envie.",
        "Não desejo de forma alguma que você envie.",
        "Preencha e depois eu vejo se envio.",
    ],
)
async def test_text_never_grants_authority(instruction):
    tools = FakeTools()
    model = FakeModel([[ToolCall("1", "click_button", {"button": "Enviar"})]])
    result = await FormAgent(tools, model).run(instruction)
    assert not result.submitted
    assert not result.submission_authorized
    assert not any(name == "click_button" for name, _ in tools.calls)
    assert result.issues[0].code == "SUBMISSION_BLOCKED"


async def test_negative_instruction_vetoes_external_authorization():
    tools = FakeTools()
    model = FakeModel([[ToolCall("1", "click_button", {"button": "Enviar"})]])
    result = await FormAgent(tools, model).run(
        "Não desejo de forma alguma que você envie.",
        authorize_submission=True,
    )
    assert not result.submission_authorized
    assert not tools.calls


async def test_final_read_happens_after_latest_write_and_detects_failure():
    tools = FakeTools()
    model = FakeModel(
        [
            [
                ToolCall("1", "fill_field", {"field": "Nome completo", "value": "João"}),
                ToolCall("2", "read_field", {"field": "Nome completo"}),
                ToolCall("3", "fill_field", {"field": "Nome completo", "value": "Maria"}),
            ]
        ]
    )
    result = await FormAgent(tools, model).run("Corrija João para Maria")
    assert tools.calls[-1][0] == "read_field"
    assert result.filled[0].value == "João"
    assert not result.verification_complete
    assert "VERIFICATION_ERROR" in [issue.code for issue in result.issues]


async def test_final_read_preserves_technical_error_for_operational_metric():
    from form_agent.core.errors import ToolClientError
    from form_agent.evaluation.cases import EvaluationCase
    from form_agent.evaluation.runner import score_form

    class FailingRead(FakeTools):
        async def call_tool(self, name, arguments=None):
            if name == "read_field":
                raise ToolClientError("Releitura interrompida", "TIMEOUT")
            return await super().call_tool(name, arguments)

    model = FakeModel([[ToolCall("1", "fill_field", {"field": "fullName", "value": "João"})], []])
    result = await FormAgent(FailingRead(), model).run("Preencha João")
    case = EvaluationCase("a", "Preencha João", {"fullName": "João"}, False, False)
    assert any(issue.code == "TIMEOUT" and issue.stage == "verification" for issue in result.issues)
    assert score_form(case, 1, result, 0).operational_failure


async def test_successful_click_is_not_submission_evidence():
    tools = FakeTools()
    model = FakeModel([[ToolCall("1", "click_button", {"button": "Enviar"})]])
    result = await FormAgent(tools, model).run("Envie", authorize_submission=True)
    assert not result.submitted


async def test_server_cannot_expand_tool_allowlist():
    class ExtraTools(FakeTools):
        async def list_tools(self):
            return [*await super().list_tools(), ToolDefinition("shell", "unsafe", {})]

    tools = ExtraTools()
    result = await FormAgent(tools, FakeModel([[ToolCall("1", "shell", {})]])).run("Preencha")
    assert not tools.calls
    assert result.issues[0].code == "TOOL_ERROR"


async def test_host_submission_rejects_changed_reviewed_state():
    from dataclasses import replace

    from form_agent.core.schemas import AgentResult

    tools = FakeTools()
    before = await tools.inspect_form()
    reviewed = replace(before, fields=(replace(before.fields[0], value="Pessoa Alfa"),))
    result = AgentResult("", before, (), False, False, final_inspection=reviewed)
    output = await FormAgent(tools, FakeModel([])).submit(result, "Enviar", authorized=True)
    assert output["code"] == "VERIFICATION_ERROR"
    assert not tools.calls


async def test_host_submission_requires_permission_and_completed_run():
    from form_agent.core.schemas import AgentResult

    tools = FakeTools()
    inspection = await tools.inspect_form()
    result = AgentResult(
        "", inspection, (), False, False, turn_limit_reached=True, final_inspection=inspection
    )
    agent = FormAgent(tools, FakeModel([]))
    assert (await agent.submit(result, "Enviar"))["code"] == "SUBMISSION_BLOCKED"
    assert (await agent.submit(result, "Enviar", authorized=True))["code"] == "SUBMISSION_BLOCKED"
    assert not tools.calls
