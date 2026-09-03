import pytest

from form_agent.adapters.playwright_browser import BrowserController
from form_agent.config import BrowserConfig
from form_agent.core.errors import AmbiguousElementError, ElementNotFoundError
from form_agent.core.schemas import FormField


def controller():
    return BrowserController(BrowserConfig(url="file:///form.html"))


def test_semantic_match_ignores_accents():
    fields = [FormField("Estado", "state", "state", "select", "combobox")]
    assert controller()._best("ESTADO", fields) == fields[0]


def test_semantic_match_rejects_missing_element():
    with pytest.raises(ElementNotFoundError):
        controller()._best("Telefone", [])


def test_semantic_match_rejects_ambiguity():
    fields = [
        FormField("Nome", "first", "first", "text", "textbox"),
        FormField("Nome", "last", "last", "text", "textbox"),
    ]
    with pytest.raises(AmbiguousElementError):
        controller()._best("Nome", fields)
