"""Versioned lexical scoring independent of functional form success."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

NORMALIZATION_VERSION = "nfc-casefold-whitespace-v1"


def normalize_transcript(text: str) -> str:
    # Retain accents and punctuation, which can carry information in emails/numbers.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).casefold()).strip()


def edit_distance[T](reference: Sequence[T], hypothesis: Sequence[T]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, 1):
        current = [row]
        for column, actual in enumerate(hypothesis, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected != actual),
                )
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True, slots=True)
class SpeechScore:
    word_edits: int
    reference_words: int
    character_edits: int
    reference_characters: int
    wer: float | None
    cer: float | None


def score_transcript(reference: str, hypothesis: str) -> SpeechScore:
    expected, actual = normalize_transcript(reference), normalize_transcript(hypothesis)
    words = expected.split()
    word_edits = edit_distance(words, actual.split())
    character_edits = edit_distance(expected, actual)
    return SpeechScore(
        word_edits,
        len(words),
        character_edits,
        len(expected),
        word_edits / len(words) if words else None,
        character_edits / len(expected) if expected else None,
    )


def real_time_factor(processing_seconds: float, duration_seconds: float | None) -> float | None:
    return (
        processing_seconds / duration_seconds
        if duration_seconds is not None and duration_seconds > 0
        else None
    )
