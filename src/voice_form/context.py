"""Build bounded Whisper vocabulary hints from the inspected form schema."""

from dataclasses import replace

from audio_agent.models import TranscriptionSettings
from form_agent.core.schemas import FormInspection

from .fields import field_kind

MAX_PROMPT_CHARS = 450
MAX_HOTWORDS_CHARS = 200
MAX_FIELDS = 20

TYPE_HINTS = {
    "email": "e-mail arroba @ ponto .",
    "phone": "telefone celular DDD",
    "date": "data dia mês ano",
    "datetime-local": "data dia mês ano horário",
    "time": "horário horas minutos",
    "number": "número",
    "url": "endereço de site ponto barra",
}


def _text(value: str) -> str:
    return " ".join(value.split())[:60]


def _bounded(parts: list[str], limit: int, separator: str) -> str | None:
    selected: list[str] = []
    for part in dict.fromkeys(parts):
        if part and len(separator.join([*selected, part])) <= limit:
            selected.append(part)
    return separator.join(selected) or None


def contextualize(
    settings: TranscriptionSettings, inspection: FormInspection
) -> TranscriptionSettings:
    """Use labels/types/option labels, never populated values or button text.

    Each explicitly configured hint takes precedence over its generated equivalent.
    The original settings remain immutable for reproducible evaluation.
    """
    fields = [
        field
        for field in inspection.fields
        if not field.disabled
        and not field.readonly
        and field.type not in {"hidden", "password", "file", "submit", "button", "reset", "image"}
    ][:MAX_FIELDS]
    labels = [_text(field.label or field.name or field.id or "") for field in fields]
    kinds = [field_kind(field) or field.type for field in fields]
    type_hints = [TYPE_HINTS[kind] for kind in kinds if kind in TYPE_HINTS]
    options = [
        _text(option.label)
        for field in fields
        for option in field.options[:5]
        if option.value  # Ignore the empty "choose an option" entry.
    ]
    prompt = _bounded(labels, MAX_PROMPT_CHARS - len("Formulário: ."), ". ")
    automatic_prompt = f"Formulário: {prompt}." if prompt else None
    return replace(
        settings,
        initial_prompt=settings.initial_prompt
        if settings.initial_prompt is not None
        else automatic_prompt,
        hotwords=settings.hotwords
        if settings.hotwords is not None
        else _bounded([*type_hints, *labels, *options], MAX_HOTWORDS_CHARS, " "),
    )
