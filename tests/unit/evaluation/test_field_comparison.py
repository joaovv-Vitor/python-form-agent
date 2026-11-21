import pytest

from form_agent.core.schemas import FormField
from form_agent.evaluation.comparison import compare_field


@pytest.mark.parametrize(
    "label,expected,actual,matches",
    [
        ("Objetivo", "Conhecer o museu", "  conhecer   o museu.  ", True),
        ("Objetivo", "Conhecer o museu", "Conhecer o museu de arte", False),
        ("Objetivo", "Não enviar", "Enviar", False),
        ("Nome", "Ana Costa", " ANA  COSTA ", True),
        ("Nome", "Ana Costa", "Carlos Costa", False),
        ("Nome", "João", "Joao", False),
        ("E-mail", "ana@example.com", " ana@EXAMPLE.COM ", True),
        ("E-mail", "ana@example.com", "ana@example.org", False),
        ("E-mail", "ana@example.com", "ANA@example.com", False),
        ("E-mail", "ana@example.com", "ana@example.com.", False),
        ("Telefone com DDD", "(85) 9090-9595", "8590909595", True),
        ("Telefone", "(85) 9090-9595", "8590909596", False),
        ("Telefone", "8590909595", "+558590909595", False),
        ("CPF", "638.451.920-89", "63845192089", True),
        ("CPF", "638.451.920-89", "6384519208", False),
        ("CPF", "63845192089", "CPF:63845192089", False),
        ("CEP", "63050-205", "63050205", True),
        ("Data de nascimento", "1999-09-23", "23/09/1999", True),
        ("Data de retirada", "2026-11-20", "21/11/2026", False),
        ("Data de retirada", "2026-02-28", "30/02/2026", False),
        ("Quantidade", "6", "6,0", True),
        ("Duração prevista em meses", "6", "seis meses", False),
        ("Checkbox", True, "true", False),
        ("Checkbox", True, 1, False),
        ("Checkbox", True, False, False),
        ("Texto", "Ana", None, False),
        ("Texto", "Ana", "", False),
    ],
)
def test_field_equivalences_preserve_content_and_identity(label, expected, actual, matches):
    assert compare_field(label, expected, actual).matches is matches


def test_option_values_do_not_receive_free_text_punctuation_rules():
    field = FormField("Turno", None, None, "select", "radiogroup")
    assert compare_field("Turno", "Manhã", "manhã", field).matches
    assert not compare_field("Turno", "Manhã", "Manhã.", field).matches


def test_exact_policy_remains_available_for_historical_reproduction():
    assert not compare_field("Objetivo", "Visitar", "visitar.", policy="exact-v1").matches
    with pytest.raises(ValueError):
        compare_field("Objetivo", "Visitar", "Visitar", policy="unknown")
