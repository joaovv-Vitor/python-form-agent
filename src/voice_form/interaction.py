"""Typed review input; terminal command parsing stays at the terminal boundary."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type InputKind = Literal["text", "audio", "show", "pending", "skip", "complete", "close", "send"]


@dataclass(frozen=True)
class ReviewInput:
    kind: InputKind
    text: str = ""
    audio_path: Path | None = None


type ReviewAsk = Callable[[str], Awaitable[str | ReviewInput]]

COMMANDS: dict[str, InputKind] = {
    "mostrar": "show",
    "revisar": "show",
    "mostre os dados": "show",
    "leia os dados": "show",
    "pendencias": "pending",
    "o que falta": "pending",
    "o que ainda falta": "pending",
    "pular": "skip",
    "cancelar": "skip",
    "concluir": "complete",
    "terminar": "complete",
    "encerrar": "close",
    "sair": "close",
    "enviar": "send",
    "pode enviar": "send",
    "envie": "send",
}


def terminal_input(answer: str) -> ReviewInput:
    answer = answer.strip()
    folded = "".join(
        c for c in unicodedata.normalize("NFD", answer.casefold()) if not unicodedata.combining(c)
    ).rstrip(".!?")
    if folded in COMMANDS:
        return ReviewInput(COMMANDS[folded], answer)
    match = re.match(r"^(?:audio|áudio)\s+(.+)$", answer, re.IGNORECASE)
    if match:
        return ReviewInput(
            "audio", answer, Path(match[1].strip().strip('"').strip("'")).expanduser()
        )
    return ReviewInput("text", answer)
