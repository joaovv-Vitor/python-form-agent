import pytest

from voice_form.normalization import normalize_spoken_data


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("Meu e-mail é ana ponto silva arroba gmail ponto com.", "email", "ana.silva@gmail.com"),
        ("E-mail: ana mais teste arroba example ponto com", "email", "ana+teste@example.com"),
        ("E-mail: ana sublinhado silva arroba example ponto com", "email", "ana_silva@example.com"),
        ("E-mail: ana hífen silva arroba example ponto com", "email", "ana-silva@example.com"),
        ("E-mail: ponto.arroba@EXAMPLE.COM", "email", "ponto.arroba@example.com"),
        ("E-mail: Ana.Silva@example.com", "email", "Ana.Silva@example.com"),
        ("E-mail: mais arroba example ponto com", "email", "mais@example.com"),
        ("E-mail: ponto arroba example ponto com", "email", "ponto@example.com"),
        ("E-mail: envie@example.com", "email", "envie@example.com"),
        ("E-mail: aceito@example.com", "email", "aceito@example.com"),
        ("E-mail: sem@example.com", "email", "sem@example.com"),
        ("E-mail: ana @ example.com", "email", "ana@example.com"),
        ("E-mail: joão.pedro arroba gmail.com", "email", "joao.pedro@gmail.com"),
        ("E-mail: joão.pedro, arroba, gmail, ponto, com", "email", "joao.pedro@gmail.com"),
        ("E-mail: João.pedro@gmail.com", "email", "Joao.pedro@gmail.com"),
        ("Telefone: 85 999123456", "phone", "(85) 99912-3456"),
        ("Celular: (85) 99912-3456.", "phone", "(85) 99912-3456"),
        ("Telefone: 85 34567890", "phone", "(85) 3456-7890"),
        ("Whatsapp: +55 85 99912-3456", "phone", "+55 (85) 99912-3456"),
        ("Telefone: 5585999123456", "phone", "+55 (85) 99912-3456"),
        (
            "Telefone: DDD oito cinco nove nove nove um dois três quatro cinco meia",
            "phone",
            "(85) 99912-3456",
        ),
        ("Minha data de nascimento é 15 de março de 2001.", "date", "2001-03-15"),
        ("Nascimento: quinze de março de 2001", "date", "2001-03-15"),
        ("Data: vinte e nove de fevereiro de 2000", "date", "2000-02-29"),
        ("Data: dia 15 março 2001", "date", "2001-03-15"),
        ("Data: 15/03/2001", "date", "2001-03-15"),
        ("Data: 03/04/2001", "date", "2001-04-03"),
        ("Data: 2001-03-15", "date", "2001-03-15"),
        ("Data: 15.03.2001", "date", "2001-03-15"),
    ],
)
def test_explicit_values_are_normalized_without_changing_source(text, kind, value):
    result = normalize_spoken_data(text)
    assert result.original_text == text
    assert len(result.fields) == 1
    field = result.fields[0]
    assert (field.kind, field.status, field.value) == (kind, "normalized", value)
    assert field.source_text == text[field.start : field.end]
    assert value in result.instruction
    assert not result.issues


@pytest.mark.parametrize(
    "text",
    [
        "E-mail: João.pedroarrobajimeio.com",
        "E-mail: www.john.pedroarrobasgmail.com",
        "E-mail: joão.pedro.gmail.com",
        "E-mail: joão.pedro arroba gmáil.com",
        "E-mail: ana silva arroba gmail ponto com",
        "E-mail: ana..silva@example.com",
        "E-mail: ana arroba example",
        "E-mail: ana arroba example ponto com ou ana arroba outro ponto com",
        "Telefone: 859919123456",
        "Telefone: 999123456",
        "Telefone: +1 85999123456",
        "Telefone: oitenta e cinco 999123456",
        "Telefone: 85 99912-????",
        "Data: 29 de fevereiro de 2001",
        "Data: 31/04/2001",
        "Data: 15/03/01",
        "Data: 15 de março",
        "E-mail: ",
    ],
)
def test_ambiguous_or_invalid_values_become_pending_without_guessing(text):
    result = normalize_spoken_data(text)
    assert result.original_text == text
    assert result.fields[0].value is None
    assert result.fields[0].status == "pending"
    assert result.issues[0].code == "DATA_PENDING"
    assert "não preencher" in result.instruction
    assert result.to_dict()["fields"][0]["source_text"] == result.fields[0].source_text


def test_only_representation_is_changed_not_domain_spelling():
    result = normalize_spoken_data("E-mail: ana arroba jimeio ponto com")
    assert result.fields[0].value == "ana@jimeio.com"
    assert "gmail" not in result.instruction


def test_email_ascii_convention_is_traced_and_does_not_change_the_person_name():
    text = "Meu nome é João Pedro. Meu e-mail é joão.pedro arroba gmail.com."
    result = normalize_spoken_data(text)
    assert result.original_text == text
    assert result.instruction == "Meu nome é João Pedro. Meu e-mail é joao.pedro@gmail.com."
    assert result.fields[0].source_text == "joão.pedro arroba gmail.com"
    assert "email_local_remove_accents" in result.fields[0].rules
    assert result.version == "spoken-data-pt-BR-v2"


def test_multiple_fields_keep_names_city_terms_and_submission_instruction():
    text = (
        "Meu nome completo é João Pedro Almeida, meu e-mail é ana ponto silva arroba gmail ponto com "
        "Meu telefone é 85 999123456 Minha data de nascimento é 15 de março de 2001 "
        "Minha cidade é Quichadá, meu estado é Ceará Eu aceito os termos, não envie o formulário."
    )
    result = normalize_spoken_data(text)
    assert [item.value for item in result.fields] == [
        "ana.silva@gmail.com",
        "(85) 99912-3456",
        "2001-03-15",
    ]
    assert result.instruction == (
        "Meu nome completo é João Pedro Almeida, meu e-mail é ana.silva@gmail.com "
        "Meu telefone é (85) 99912-3456 Minha data de nascimento é 2001-03-15 "
        "Minha cidade é Quichadá, meu estado é Ceará Eu aceito os termos, não envie o formulário."
    )


@pytest.mark.parametrize(
    "command", ["Não envie.", "Nunca mande.", "Pode enviar.", "Eu aceito os termos."]
)
def test_trailing_commands_are_preserved(command):
    text = f"Telefone: 85 999123456 {command}"
    result = normalize_spoken_data(text)
    assert result.instruction == f"Telefone: (85) 99912-3456 {command}"


def test_unlabelled_text_is_unchanged():
    text = "Não preencha o telefone. Moro em Quichadá. ana arroba example ponto com"
    result = normalize_spoken_data(text)
    assert result.instruction == text
    assert result.fields == ()


def test_conflicting_repetitions_are_pending_but_identical_repetitions_are_not():
    conflict = normalize_spoken_data("E-mail: ana@example.com. E-mail: bia@example.com.")
    assert all(item.status == "pending" for item in conflict.fields)
    assert "ana@example.com" not in conflict.instruction
    repeated = normalize_spoken_data("Telefone: 85 999123456. Telefone: (85) 99912-3456.")
    assert not repeated.issues
