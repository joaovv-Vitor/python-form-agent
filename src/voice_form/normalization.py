"""Conservative pt-BR representation rules, independent of STT and the LLM.

Only explicitly labelled values are processed. The PoC uses ASCII email users;
names, domains and digits are never guessed from expected evaluation data.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Literal

from form_agent.core.schemas import RunIssue

DATA_NORMALIZATION_VERSION = "spoken-data-pt-BR-v2"
type FieldKind = Literal["email", "phone", "date"]

# A connector is required so ordinary mentions ("não preencha o telefone")
# are not mistaken for a labelled value.
_LABEL = re.compile(
    r"(?<!\w)(?P<label>e[- ]?mail|telefone|celular|whatsapp|"
    r"data\s+de\s+nascimento|data|nascimento)\s*(?:é\s+|:\s*|=\s*)",
    re.IGNORECASE,
)
_BOUNDARY = re.compile(
    r"[.!?;](?=\s|$)|"
    r"\b(?:meu|minha|seu|sua)\s+(?:nome|e[- ]?mail|telefone|celular|whatsapp|"
    r"data|nascimento|cidade|estado|endereço|cep)\b|"
    r"\b(?:nome(?:\s+completo)?|cidade|estado|endereço|cep)\s*(?:é\s+|:)|"
    r"(?<!\S)(?:eu\s+)?(?:aceito|aceitar|concordo)(?=\s|$|[.!?;](?=\s|$))|"
    r"(?<!\S)(?:não|nao|nunca|jamais|sem)(?=\s|$|[.!?;](?=\s|$))|"
    r"(?<!\S)(?:pode[m]?|por\s+favor)\s+(?:preencher|enviar|envie|submeter|mandar)"
    r"(?=\s|$|[.!?;](?=\s|$))|"
    r"(?<!\S)(?:envie|enviar|submeta|submeter|mande|mandar)(?=\s|$|[.!?;](?=\s|$))",
    re.IGNORECASE,
)
_DIGITS = {
    "zero": "0",
    "um": "1",
    "uma": "1",
    "dois": "2",
    "duas": "2",
    "tres": "3",
    "quatro": "4",
    "cinco": "5",
    "seis": "6",
    "meia": "6",
    "sete": "7",
    "oito": "8",
    "nove": "9",
}
_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_DAYS = {
    "primeiro": 1,
    "um": 1,
    "dois": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
    "trinta": 30,
}


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn"
    )


@dataclass(frozen=True, slots=True)
class NormalizedField:
    kind: FieldKind
    source_text: str
    start: int
    end: int
    value: str | None
    status: Literal["normalized", "pending"]
    rules: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    original_text: str
    instruction: str
    fields: tuple[NormalizedField, ...]
    version: str = DATA_NORMALIZATION_VERSION

    @property
    def issues(self) -> tuple[RunIssue, ...]:
        return tuple(
            RunIssue("DATA_PENDING", "normalization", f"{item.kind}: {item.reason}")
            for item in self.fields
            if item.status == "pending"
        )

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "issues": [asdict(issue) for issue in self.issues]}


def _email(raw: str) -> tuple[str | None, tuple[str, ...], str | None]:
    value = raw.strip()
    rules: list[str] = []
    # Already-written compact addresses may legitimately contain "ponto" or
    # "arroba" in the local part. Spoken rules must not rewrite those names.
    if "@" not in value or re.search(r"\s", value):
        for word, symbol in (
            ("arroba", "@"),
            ("ponto", "."),
            ("hífen|hifen|traço|traco", "-"),
            ("underscore|sublinhado", "_"),
            ("mais", "+"),
        ):
            # Separators must sit between components: a username literally
            # called "mais" or "ponto" is not a leading + or dot.
            value, count = re.subn(
                rf"(?<=\w)[\s,]+(?:{word})[\s,]+(?=\w)", symbol, value, flags=re.IGNORECASE
            )
            if count:
                rules.append(f"spoken_{symbol}")
        value = re.sub(r"\s*([@._+-])\s*", r"\1", value)
    if value.count("@") != 1:
        return None, tuple(rules), "Separação entre usuário e domínio ausente ou ambígua."
    local, domain = value.split("@")
    # Explicit experiment convention: ASCII email local parts. Do not remove
    # accents from names, domains, or an email whose separator is still missing.
    ascii_local = "".join(
        c for c in unicodedata.normalize("NFD", local) if unicodedata.category(c) != "Mn"
    )
    if ascii_local != local:
        rules.append("email_local_remove_accents")
        local = ascii_local
    label = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
    if (
        len(value) > 254
        or len(local) > 64
        or not re.fullmatch(r"[a-zA-Z0-9_%+.-]+", local)
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not re.fullmatch(rf"(?:{label}\.)+[a-zA-Z]{{2,}}", domain)
    ):
        return (
            None,
            tuple(rules),
            "Formato de e-mail incerto; revise sem adivinhar grafia ou domínio.",
        )
    if domain != domain.lower():
        rules.append("lowercase_domain")
    return f"{local}@{domain.lower()}", tuple(rules), None


def _phone(raw: str) -> tuple[str | None, tuple[str, ...], str | None]:
    value = re.sub(r"^ddd\s*", "", _fold(raw).strip())
    rules = ["phone_br_format"]

    def spoken_digit(match: re.Match[str]) -> str:
        return _DIGITS[match.group()]

    value, count = re.subn(
        r"\b(?:" + "|".join(_DIGITS) + r")\b",
        spoken_digit,
        value,
    )
    if count:
        rules.append("spoken_digits")
    if not re.fullmatch(r"\+?[\d\s().-]+", value, flags=re.ASCII):
        return None, tuple(rules), "Telefone contém palavras ou símbolos não reconhecidos."
    digits = re.sub(r"\D", "", value, flags=re.ASCII)
    country = ""
    if len(digits) in (12, 13) and digits.startswith("55"):
        country, digits = "+55 ", digits[2:]
    elif value.startswith("+"):
        return None, tuple(rules), "Código internacional não reconhecido como +55."
    if len(digits) not in (10, 11) or digits[0] == "0":
        return (
            None,
            tuple(rules),
            "Esperados 10 ou 11 dígitos com DDD; nenhum dígito foi corrigido.",
        )
    return f"{country}({digits[:2]}) {digits[2:-4]}-{digits[-4:]}", tuple(rules), None


def _day(text: str) -> int:
    if text.isascii() and text.isdigit():
        return int(text)
    if text in _DAYS:
        return _DAYS[text]
    parts = text.split(" e ")
    if len(parts) == 2 and parts[0] in ("vinte", "trinta") and parts[1] in _DAYS:
        unit = _DAYS[parts[1]]
        if 1 <= unit <= 9:
            return _DAYS[parts[0]] + unit
    raise ValueError("Dia não reconhecido")


def _date(raw: str) -> tuple[str | None, tuple[str, ...], str | None]:
    value = re.sub(r"\s+", " ", _fold(raw).strip())
    value = re.sub(r"^dia\s+", "", value)
    rules = ("date_iso_pt_br",)
    try:
        iso = re.fullmatch(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", value)
        numeric = re.fullmatch(r"([0-9]{1,2})([/.-])([0-9]{1,2})\2([0-9]{4})", value)
        spoken = re.fullmatch(r"(.+?) (?:de )?([a-z]+) (?:de )?([0-9]{4})", value)
        if iso:
            year, month, day = map(int, iso.groups())
        elif numeric:
            day, month, year = int(numeric[1]), int(numeric[3]), int(numeric[4])
        elif spoken and spoken[2] in _MONTHS:
            day, month, year = _day(spoken[1]), _MONTHS[spoken[2]], int(spoken[3])
        else:
            raise ValueError("Formato não reconhecido")
        return date(year, month, day).isoformat(), rules, None
    except ValueError:
        return (
            None,
            rules,
            "Data inválida ou incompleta; informe dia, mês e ano com quatro dígitos.",
        )


def normalize_field_value(
    kind: FieldKind, value: str
) -> tuple[str | None, tuple[str, ...], str | None]:
    return {"email": _email, "phone": _phone, "date": _date}[kind](value)


def normalize_spoken_data(text: str) -> NormalizationResult:
    """Keep unaffected text verbatim and replace only explicitly labelled values.

    Pending raw values remain in evidence, but are replaced with a pending marker
    in the instruction so they are not presented to the LLM as usable data.
    """
    labels = list(_LABEL.finditer(text))
    fields: list[NormalizedField] = []
    for index, match in enumerate(labels):
        start = match.end()
        limit = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        boundary = _BOUNDARY.search(text, start)
        end = min(boundary.start(), limit) if boundary else limit
        # Keep separators/conjunctions outside the replaced value.
        tail = re.search(r"(?:\s+e)?[\s,]*$", text[start:end])
        if tail:
            end = start + tail.start()
        while start < end and text[start].isspace():
            start += 1
        raw = text[start:end]
        label = _fold(match["label"])
        kind: FieldKind = (
            "email"
            if label.replace("-", "").replace(" ", "") == "email"
            else "phone"
            if label in {"telefone", "celular", "whatsapp"}
            else "date"
        )
        value, rules, reason = normalize_field_value(kind, raw)
        fields.append(
            NormalizedField(
                kind, raw, start, end, value, "pending" if reason else "normalized", rules, reason
            )
        )
    # Conflicting repetitions or corrections still require review.
    # Multiple distinct values must be reviewed rather than letting the LLM choose.
    for kind in ("email", "phone", "date"):
        items = [item for item in fields if item.kind == kind]
        if len(items) > 1 and (
            any(item.status == "pending" for item in items)
            or len({item.value for item in items}) > 1
        ):
            fields = [
                replace(
                    item,
                    value=None,
                    status="pending",
                    reason="Valores repetidos sem resolução inequívoca.",
                )
                if item.kind == kind
                else item
                for item in fields
            ]
    instruction = text
    for item in reversed(fields):
        replacement = (
            item.value if item.value is not None else f"[PENDENTE: {item.kind}; não preencher]"
        )
        instruction = instruction[: item.start] + replacement + instruction[item.end :]
    return NormalizationResult(text, instruction, tuple(fields))
