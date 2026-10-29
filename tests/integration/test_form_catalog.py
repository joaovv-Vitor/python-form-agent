"""Different form schemas exercised through the same agent and real MCP browser."""

import pytest

from form_agent.adapters.mcp_client import BrowserToolsClient
from form_agent.bootstrap import Application
from form_agent.config import BrowserConfig, ModelConfig
from form_agent.confirmation import submit_confirmed
from form_agent.core.agent import FormAgent
from form_agent.core.errors import ToolClientError
from form_agent.core.schemas import ToolCall
from web_api.config import asset
from web_api.forms import DEMO_FORMS

pytestmark = pytest.mark.integration

CASES = (
    (
        "cadastro",
        {
            "fullName": "Ana",
            "email": "ana@example.com",
            "city": "Fortaleza",
            "state": "CE",
            "acceptTerms": True,
        },
    ),
    (
        "contato",
        {
            "contactName": "Ana",
            "replyEmail": "ana@example.com",
            "topic": "informacao",
            "messageBody": "Quero informações sobre o atendimento.",
            "returnChannel": "email",
        },
    ),
    (
        "inscricao",
        {
            "attendee": "Ana",
            "eventChoice": "oficina-ia",
            "eventDate": "2027-03-15",
            "attendanceMode": "online",
            "accessibilityNotes": "Preciso de legendas.",
            "receiveUpdates": True,
        },
    ),
    (
        "suporte",
        {
            "requester": "Ana",
            "product": "notebook",
            "problemCategory": "software",
            "urgency": "alta",
            "problemDescription": "Meu computador não inicia.",
            "incidentDate": "2026-10-29",
        },
    ),
)


class ScriptedModel:
    def __init__(self, values):
        self.batches = iter(
            [
                [
                    ToolCall(
                        str(index),
                        "fill_field",
                        {
                            "field": reference,
                            "value": str(value).lower() if isinstance(value, bool) else value,
                        },
                    )
                    for index, (reference, value) in enumerate(values.items())
                ],
                [],
            ]
        )

    def create_session(self, instruction, inspection, tools):
        return self

    async def next(self, completed):
        return next(self.batches)

    async def close(self):
        pass


@pytest.mark.parametrize("form_id,values", CASES)
async def test_same_agent_fills_and_confirms_each_catalogue_form(form_id, values):
    demo = next(form for form in DEMO_FORMS if form.id == form_id)
    browser = BrowserConfig(asset(demo.filename).as_uri(), form_selector="form")
    client = BrowserToolsClient(browser_config=browser)
    model = ScriptedModel(values)
    app = Application(
        ModelConfig("test", "test", "test", "test-key"), FormAgent(client, model), client, model
    )
    try:
        result = await app.agent.run("Preencha os dados fornecidos para este formulário.")
        assert result.verification_complete and not result.issues
        fields = {field.reference: field for field in result.final_inspection.fields}
        assert {reference: fields[reference].value for reference in values} == values
        assert all(field.valid is not False for field in fields.values())
        assert not result.submitted and not result.submission_attempted
        output = await submit_confirmed(app, result)
        assert output["submitted"] is True
    finally:
        await app.close()


async def test_web_scope_ignores_controls_outside_the_form(tmp_path):
    page = tmp_path / "scoped.html"
    page.write_text(
        '<label>Pesquisa<input name="search"></label><form><label>Código<input id="code"></label><button type="submit">Salvar</button></form>'
    )
    client = BrowserToolsClient(browser_config=BrowserConfig(page.as_uri(), form_selector="form"))
    try:
        inspection = await client.inspect_form()
        assert [field.reference for field in inspection.fields] == ["code"]
    finally:
        await client.close()


async def test_web_scope_rejects_a_page_with_multiple_forms(tmp_path):
    page = tmp_path / "ambiguous.html"
    page.write_text('<form><input name="first"></form><form><input name="second"></form>')
    client = BrowserToolsClient(browser_config=BrowserConfig(page.as_uri(), form_selector="form"))
    try:
        with pytest.raises(ToolClientError, match="único formulário"):
            await client.inspect_form()
    finally:
        await client.close()
