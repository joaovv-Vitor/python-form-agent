"""Deterministic equivalences for field values; never rewrite browser evidence."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from ..core.schemas import FormField, JsonValue

COMPARISON_VERSION: Literal["field-aware-v1"] = "field-aware-v1"
type ComparisonPolicy = Literal["exact-v1", "field-aware-v1"]


@dataclass(frozen=True, slots=True)
class FieldComparison:
    matches: bool
    rule: str


def _spaces(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _date(value: str) -> object:
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def compare_field(
    label: str,
    expected: JsonValue,
    actual: JsonValue,
    field: FormField | None = None,
    *,
    policy: ComparisonPolicy = COMPARISON_VERSION,
) -> FieldComparison:
    if policy not in {"exact-v1", COMPARISON_VERSION}:
        raise ValueError(f"Política de comparação desconhecida: {policy}")
    if type(expected) is type(actual) and expected == actual:
        return FieldComparison(True, "exact")
    if policy == "exact-v1" or not isinstance(expected, str) or not isinstance(actual, str):
        return FieldComparison(False, "exact")
    wanted, observed = _spaces(expected), _spaces(actual)
    key = "".join(
        c for c in unicodedata.normalize("NFD", label.casefold()) if not unicodedata.combining(c)
    )
    kind = field.type if field else "text"
    if kind == "date" or re.search(r"\bdata\b", key):
        left, right = _date(wanted), _date(observed)
        return FieldComparison(left is not None and left == right, "date")
    if any(token in key for token in ("telefone", "phone", "cpf", "cep")):
        valid = all(re.fullmatch(r"[+0-9().\s-]+", value) for value in (wanted, observed))
        left, right = re.sub(r"[^0-9]", "", wanted), re.sub(r"[^0-9]", "", observed)
        return FieldComparison(bool(valid and left and left == right), "identifier_digits")
    if "mail" in key:

        def address(value: str) -> tuple[str, str] | None:
            if value.count("@") != 1:
                return None
            local, domain = value.split("@")
            return (
                (local, domain.casefold())
                if local and domain and not re.search(r"\s", value)
                else None
            )

        left, right = address(wanted), address(observed)
        return FieldComparison(left is not None and left == right, "email_identity")
    if kind in {"select", "radio", "checkbox"}:
        return FieldComparison(wanted.casefold() == observed.casefold(), "option")
    if "nome" in key or "name" in key:
        return FieldComparison(wanted.casefold() == observed.casefold(), "name_identity")
    if kind == "number" or any(
        token in key for token in ("quantidade", "numero de participantes", "duracao")
    ):
        if all(re.fullmatch(r"[+-]?[0-9]+(?:[.,][0-9]+)?", value) for value in (wanted, observed)):
            return FieldComparison(
                Decimal(wanted.replace(",", ".")) == Decimal(observed.replace(",", ".")), "number"
            )
        return FieldComparison(False, "number")
    return FieldComparison(
        wanted.rstrip(".!? ").casefold() == observed.rstrip(".!? ").casefold(),
        "text_case_spaces_terminal_punctuation",
    )
