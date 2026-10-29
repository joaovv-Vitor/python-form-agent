"""Recognize typed data in native controls and ordinary text fields."""

import re
import unicodedata

from form_agent.core.schemas import FormField

from .normalization import FieldKind


def field_kind(field: FormField) -> FieldKind | None:
    if field.type == "email":
        return "email"
    if field.type == "tel":
        return "phone"
    if field.type not in {"text", "search"}:
        return None
    text = " ".join((field.label, field.name or "", field.id or "", field.placeholder or ""))
    text = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c)
    )
    if re.search(r"e[-_ ]?mail", text):
        return "email"
    if re.search(r"telefone|phone|celular|whatsapp", text):
        return "phone"
    return None
