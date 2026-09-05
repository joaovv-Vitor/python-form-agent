from types import SimpleNamespace

import pytest

from form_agent.confirmation import confirm_submission
from form_agent.core.schemas import AgentResult, FormButton, FormField, FormInspection


@pytest.mark.parametrize(
    "answer,expected", [("ENVIAR", [True, "submit", False]), ("sim", []), ("", [])]
)
async def test_only_explicit_confirmation_grants_and_then_revokes_permission(
    monkeypatch, capsys, answer, expected
):
    actions = []

    class Client:
        async def set_submission_authorized(self, authorized):
            actions.append(authorized)

    class Agent:
        async def submit(self, result, button, *, authorized=False):
            assert authorized
            actions.append("submit")
            return {"success": True, "submitted": True}

    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    inspection = FormInspection(
        "file:///form",
        fields=(FormField("Nome", "name", "name", "text", "textbox", value="Pessoa Alfa"),),
        buttons=(FormButton("Enviar", "send", "send", "submit"),),
    )
    result = AgentResult("", inspection, (), False, False, final_inspection=inspection)
    output = await confirm_submission(SimpleNamespace(client=Client(), agent=Agent()), result)
    assert "Nome: Pessoa Alfa" in capsys.readouterr().out
    assert actions == expected
    assert output.get("submitted", False) == bool(expected)
