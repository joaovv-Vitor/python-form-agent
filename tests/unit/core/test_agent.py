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
