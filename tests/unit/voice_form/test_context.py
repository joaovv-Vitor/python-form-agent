from dataclasses import replace

import pytest

from audio_agent.models import TranscriptionSettings
from form_agent.core.schemas import FormButton, FormField, FormInspection, FormOption
from voice_form.context import MAX_HOTWORDS_CHARS, MAX_PROMPT_CHARS, contextualize


def field(label, kind="text", **kwargs):
    return FormField(label, label, label, kind, "textbox", **kwargs)


def test_vocabulary_comes_from_schema_without_current_values_or_buttons():
    inventory = FormInspection(
        "https://example.com/private-path",
        (
            field("Nome completo", value="Nome privado"),
            field("E-mail", "email", value="privado@example.com"),
            field("Telefone", "tel"),
            field("Data de nascimento", "date"),
            field(
                "Estado",
                "select",
                options=(
                    FormOption("Selecione", ""),
                    FormOption("Ceará", "CE-secret"),
                ),
            ),
        ),
        (FormButton("Enviar formulário", None, "submit"),),
    )
    result = contextualize(TranscriptionSettings(), inventory)
    assert "Nome completo" in result.initial_prompt
    assert "Data de nascimento" in result.initial_prompt
    assert "arroba" in result.hotwords
    assert "DDD" in result.hotwords
    assert "Ceará" in result.hotwords
    for excluded in ("privado", "Enviar formulário", "CE-secret", "Selecione", "private-path"):
        assert excluded not in result.initial_prompt + result.hotwords


def test_ineligible_fields_are_excluded_and_empty_form_adds_no_context():
    inventory = FormInspection(
        "file:///form",
        (
            field("Segredo", "password"),
            field("Arquivo", "file"),
            field("Interno", "hidden"),
            field("Desabilitado", disabled=True),
            field("Somente leitura", readonly=True),
        ),
    )
    settings = TranscriptionSettings()
    assert contextualize(settings, inventory) == settings


@pytest.mark.parametrize(
    "prompt,hotwords", [(None, "Vocabulário manual"), ("Contexto manual", None), ("", "")]
)
def test_manual_parameters_override_their_automatic_equivalents(prompt, hotwords):
    settings = TranscriptionSettings(initial_prompt=prompt, hotwords=hotwords)
    inventory = FormInspection("file:///form", (field("E-mail", "email"),))
    result = contextualize(settings, inventory)
    assert result.initial_prompt == (prompt if prompt is not None else "Formulário: E-mail.")
    assert result.hotwords == (
        hotwords if hotwords is not None else "e-mail arroba @ ponto . E-mail"
    )
    assert settings == replace(result, initial_prompt=prompt, hotwords=hotwords)


def test_large_form_produces_bounded_context_with_normalized_whitespace():
    fields = tuple(field(f"Campo\n\t{i} " + "x" * 300) for i in range(100))
    result = contextualize(TranscriptionSettings(), FormInspection("file:///form", fields))
    assert len(result.initial_prompt) <= MAX_PROMPT_CHARS
    assert len(result.hotwords) <= MAX_HOTWORDS_CHARS
    assert "\n" not in result.initial_prompt + result.hotwords
    assert "Campo 99" not in result.initial_prompt + result.hotwords
