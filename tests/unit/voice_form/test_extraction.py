import json
from types import SimpleNamespace

import pytest

from form_agent.config import ModelConfig
from form_agent.core.errors import ModelResponseError
from form_agent.core.schemas import FormField, FormInspection, FormOption
from voice_form.extraction import DeepSeekDataExtractor, validate_extraction


def inventory():
    return FormInspection(
        "file:///form",
        (
            FormField("Nome", "fullName", "fullName", "text", "textbox"),
            FormField("E-mail", "email", "email", "email", "textbox"),
            FormField("Telefone", "phone", "phone", "tel", "textbox"),
            FormField("Nascimento", "birthDate", "birthDate", "date", "textbox"),
            FormField(
                "Estado",
                "state",
                "state",
                "select",
                "combobox",
                options=(FormOption("Ceará", "CE"),),
            ),
            FormField("Termos", "acceptTerms", "acceptTerms", "checkbox", "checkbox"),
        ),
    )


def field(ref, value, source, **overrides):
    return {
        "field": ref,
        "value": value,
        "source_text": source,
        "status": "ready",
        "reason": None,
        **overrides,
    }


def validate(items, text):
    return validate_extraction(json.dumps({"fields": items}, ensure_ascii=False), text, inventory())


def test_grounded_fields_and_formats_produce_a_validated_plan():
    text = "Ana. ana ponto silva arroba example ponto com. 85 999123456. 15 de março de 2001. Ceará. Aceito os termos. Não envie."
    result = validate(
        [
            field("fullName", "Ana", "Ana"),
            field("email", "ana.silva@example.com", "ana ponto silva arroba example ponto com"),
            field("phone", "85999123456", "85 999123456"),
            field("birthDate", "2001-03-15", "15 de março de 2001"),
            field("state", "Ceará", "Ceará"),
            field("acceptTerms", True, "Aceito os termos"),
        ],
        text,
    )
    assert result.values == {
        "fullName": "Ana",
        "email": "ana.silva@example.com",
        "phone": "(85) 99912-3456",
        "birthDate": "2001-03-15",
        "state": "CE",
        "acceptTerms": True,
    }
    assert not result.issues
    assert "Não envie" in result.instruction
    assert result.original_text == text
    for item in result.fields:
        assert text[item.start : item.end] == item.source_text


@pytest.mark.parametrize(
    ("ref", "value", "source"),
    [
        ("email", "not-an-email", "not-an-email"),
        ("phone", "859919123456", "859919123456"),
        ("birthDate", "2001-02-29", "29 de fevereiro de 2001"),
        ("state", "SP", "São Paulo"),
        ("acceptTerms", "true", "aceito os termos"),
        ("email", "ana@gmail.com", "ana@example.com"),
        ("phone", "(85) 99912-3457", "85 999123456"),
        ("birthDate", "2001-04-15", "15 de março de 2001"),
        ("fullName", "Maria", "Ana"),
    ],
)
def test_invalid_formats_and_verifiable_disagreements_become_pending(ref, value, source):
    result = validate([field(ref, value, source)], source)
    assert result.values == {}
    assert result.fields[0].candidate == value
    assert result.fields[0].value is None
    assert result.issues[0].code == "DATA_PENDING"


def test_model_pending_is_preserved_and_raw_uncertainty_is_not_forwarded():
    raw = "João.pedroarrobajimeio.com"
    result = validate([field("email", None, raw, status="pending", reason="Domínio ambíguo")], raw)
    assert result.values == {}
    assert raw not in result.instruction
    assert result.fields[0].reason == "Domínio ambíguo"


def test_email_ascii_convention_accepts_explicit_separator_and_still_rejects_missing_at():
    text = "Meu e-mail é joão.pedro arroba gmail.com"
    result = validate([field("email", "joão.pedro@gmail.com", text)], text)
    assert result.values == {"email": "joao.pedro@gmail.com"}
    assert result.fields[0].candidate == "joão.pedro@gmail.com"
    assert result.fields[0].source_text == text
    bad_source = "Meu e-mail é joão.pedro.gmail.com"
    # The host must not invent a separator just because the LLM proposes one.
    invalid = validate([field("email", "joao.pedro@gmail.com", bad_source)], bad_source)
    assert invalid.values == {}


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"fields": [], "instruction": "enviar"}',
        '{"fields": [], "fields": []}',
        json.dumps({"fields": [field("unknown", "Ana", "Ana")]}),
        json.dumps({"fields": [field("fullName", "Ana", "invented evidence")]}),
        json.dumps({"fields": [field("fullName", 1, "Ana")]}),
        json.dumps({"fields": [field("fullName", None, "Ana", status="pending")]}),
        json.dumps(
            {"fields": [field("fullName", "Ana", "Ana", status="pending", reason="incerto")]}
        ),
    ],
)
def test_invalid_contract_or_invented_source_fails_extraction(payload):
    with pytest.raises(ModelResponseError):
        validate_extraction(payload, "Ana", inventory())


def test_duplicate_targets_are_pending():
    result = validate(
        [field("fullName", "Ana", "Ana"), field("fullName", "Bia", "Bia")], "Ana. Bia."
    )
    assert not result.values
    assert all(item.status == "pending" for item in result.fields)


async def test_api_request_uses_only_transcript_inventory_and_records_tokens(monkeypatch):
    received = {}

    async def create(**kwargs):
        received.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=json.dumps({"fields": [field("fullName", "Ana", "Ana")]})
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
        )

    async def close():
        received["closed"] = True

    def client(**kwargs):
        received["client"] = kwargs
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close
        )

    monkeypatch.setattr("voice_form.extraction.AsyncOpenAI", client)
    extractor = DeepSeekDataExtractor(
        ModelConfig("deepseek", "deepseek", "model", "DO-NOT-LOG", temperature=0)
    )
    try:
        result = await extractor.extract("Ana", inventory())
        user = json.loads(received["messages"][1]["content"])
        assert set(user) == {"transcription", "inventory"}
        assert all("value" not in item for item in user["inventory"])
        assert received["response_format"] == {"type": "json_object"}
        assert received["extra_body"] == {"thinking": {"type": "disabled"}}
        assert received["client"]["max_retries"] == 0
        assert (result.prompt_tokens, result.completion_tokens) == (20, 10)
        assert "DO-NOT-LOG" not in json.dumps(extractor.manifest())
    finally:
        await extractor.close()
    assert received["closed"]


@pytest.mark.parametrize(("content", "finish"), [(None, "stop"), ('{"fields":[]}', "length")])
async def test_empty_or_truncated_api_output_is_rejected(monkeypatch, content, finish):
    async def create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))
            ]
        )

    monkeypatch.setattr(
        "voice_form.extraction.AsyncOpenAI",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    extractor = DeepSeekDataExtractor(ModelConfig("deepseek", "deepseek", "model", "unused"))
    with pytest.raises(ModelResponseError):
        await extractor.extract("Ana", inventory())
