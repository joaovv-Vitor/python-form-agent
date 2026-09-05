import pytest

from form_agent.adapters.mcp_client import BrowserToolsClient
from form_agent.config import PROJECT_ROOT

pytestmark = pytest.mark.integration


@pytest.fixture
async def browser_tools(monkeypatch):
    monkeypatch.setenv("HEADLESS", "true")
    monkeypatch.setenv("FORM_URL", (PROJECT_ROOT / "examples/adversarial-form/index.html").as_uri())
    monkeypatch.setenv("BROWSER_TIMEOUT_MS", "800")
    async with BrowserToolsClient() as client:
        yield client


async def test_native_controls_and_dynamic_reinspection(browser_tools):
    client = browser_tools
    inspection = await client.inspect_form()
    assert not {"secret", "css-hidden"} & {field.id for field in inspection.fields}
    for field, value in [
        ("Cidade de residência", "Quixadá"),
        ("Telefone alternativo", "85900000000"),
        ("Estado", "Ceara"),
        ("Por e-mail", "true"),
        ("Por telefone", "true"),
        ("Adicionar complemento", "true"),
        ("Complemento", "Bloco fictício"),
        ("Data", "2000-01-02"),
    ]:
        output = await client.call_tool("fill_field", {"field": field, "value": value})
        assert output["success"], output
    assert (await client.call_tool("read_field", {"field": "Por e-mail"}))["value"] is False
    assert (await client.call_tool("read_field", {"field": "Estado"}))["value"] == "CE"
    assert (await client.call_tool("read_field", {"field": "phone"}))["value"] == "(85) 90000-0000"
    for field, code in [
        ("Nome", "FIELD_AMBIGUOUS"),
        ("Profissão", "FIELD_NOT_FOUND"),
        ("Bloqueado", "BROWSER_ERROR"),
        ("Somente leitura", "BROWSER_ERROR"),
    ]:
        output = await client.call_tool("fill_field", {"field": field, "value": "teste"})
        assert output.get("code") == code, (field, output)
    assert (await client.call_tool("fill_field", {"field": "b", "value": "Segundo"}))[
        "field_ref"
    ] == "b"


async def test_submission_requires_host_permission_and_validation(browser_tools):
    client = browser_tools
    assert (await client.call_tool("click_button", {"button": "Enviar"}))[
        "code"
    ] == "SUBMISSION_BLOCKED"
    await client.set_submission_authorized(True)
    assert (await client.call_tool("click_button", {"button": "Limpar"}))[
        "code"
    ] == "SUBMISSION_BLOCKED"
    assert (await client.call_tool("click_button", {"button": "Enviar"}))[
        "code"
    ] == "VALIDATION_ERROR"
    await client.call_tool("fill_field", {"field": "email", "value": "pessoa@example.com"})
    output = await client.call_tool("click_button", {"button": "Enviar"})
    assert output["submitted"] is True
    assert output["submission_attempted"] is True
    assert (await client.call_tool("click_button", {"button": "Enviar"}))[
        "code"
    ] == "SUBMISSION_BLOCKED"


async def test_javascript_rejection_is_not_counted_as_sent(browser_tools):
    client = browser_tools
    await client.set_submission_authorized(True)
    await client.call_tool("fill_field", {"field": "email", "value": "recusado@example.com"})
    output = await client.call_tool("click_button", {"button": "Enviar"})
    assert output["submitted"] is False
    assert output["submission_attempted"] is True
    assert output["code"] == "SUBMISSION_ERROR"


async def test_spa_replacement_preserves_semantic_resolution():
    from form_agent.adapters.playwright_browser import BrowserController
    from form_agent.config import BrowserConfig

    controller = BrowserController(
        BrowserConfig((PROJECT_ROOT / "examples/adversarial-form/index.html").as_uri())
    )
    try:
        page = await controller.start()
        await controller.inspect_form()
        await page.locator("#name").evaluate(
            'el => { el.outerHTML = \'<input id="name" value="Novo DOM">\'; }'
        )
        output = await controller.fill_field("Nome completo", "Pessoa Beta")
        assert output["value"] == "Pessoa Beta"
    finally:
        await controller.close()


async def test_agent_verifies_radio_correction(browser_tools):
    from form_agent.core.agent import FormAgent
    from form_agent.core.schemas import ToolCall

    class Model:
        def create_session(self, instruction, inspection, tools):
            self.calls = iter(
                [
                    [
                        ToolCall("1", "fill_field", {"field": "Por e-mail", "value": "true"}),
                        ToolCall("2", "fill_field", {"field": "Por telefone", "value": "true"}),
                    ],
                    [],
                ]
            )
            return self

        async def next(self, completed):
            return next(self.calls, [])

        async def close(self):
            pass

    result = await FormAgent(browser_tools, Model()).run(
        "Prefiro e-mail, corrigindo: prefiro telefone"
    )
    assert result.verification_complete
    assert {entry.field: entry.value for entry in result.filled} == {
        "Por e-mail": False,
        "Por telefone": True,
    }
