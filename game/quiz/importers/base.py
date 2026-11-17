"""Shared pieces for every quiz upload format (Phase 8).

Parsers only *read* a file and return :class:`RawItem` objects plus fatal
errors; :func:`validate_items` applies the same content rules to every format
and produces :class:`ParsedItem` rows.  Nothing here raises on bad content: a
bad item becomes a line in ``errors`` so the teacher sees every problem at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.conf import settings

from game.models import DIFFICULTY_KEYS, QUIZ_CHOICE_MAX, QUIZ_EXPLANATION_MAX, QUIZ_PROMPT_MAX
from game.validators import contains_blocked_language

# Control characters other than tab/newline are stripped before validation.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")

LETTERS = "ABCD"


def clean_text(value: object) -> str:
    """Normalize whitespace and strip control characters (keep smart quotes)."""
    text = "" if value is None else str(value)
    text = _CONTROL.sub("", text).replace("\u00a0", " ")
    return _WHITESPACE.sub(" ", text).strip()


@dataclass(frozen=True)
class ParsedItem:
    """One validated item, ready to become a ``Question``."""

    number: int
    prompt: str
    choices: list[str]
    correct_index: int
    explanation: str
    source_ref: str


@dataclass
class RawItem:
    """One item as the parser read it, before shared validation."""

    prompt: str
    choices: list[str]
    answer: str | None
    explanation: str = ""
    number: int | None = None
    source_ref: str = ""


@dataclass
class ParseResult:
    """Everything the preview page needs."""

    format: str = ""
    encoding: str = ""
    items: list[ParsedItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.items)


def _where(raw: RawItem, number: int | None = None) -> str:
    label = number if number is not None else raw.number
    prefix = raw.source_ref or "The file"
    if label is None:
        return prefix
    return f"{prefix}, item {label}"


def answer_to_index(answer: object) -> int | None:
    """Map ``A``/``a``/``(B)``/``1``-``4`` to a zero-based index, else ``None``."""
    value = clean_text(answer).strip().strip("()").upper().rstrip(".")
    if not value:
        return None
    if value in LETTERS:
        return LETTERS.index(value)
    if value in {"1", "2", "3", "4"}:
        return int(value) - 1
    return None


def validate_items(raws: list[RawItem], result: ParseResult) -> ParseResult:
    """Validate every raw item into ``result``, never raising.

    Item numbers keep their file value; missing numbers are assigned
    sequentially so item ranges mean what the teacher sees in their file.  A
    duplicate is an error (the later item is skipped), because a range would
    otherwise hit two questions.
    """
    maximum = int(settings.GAME_SETTINGS["QUIZ_SET_MAX_QUESTIONS"])
    if len(raws) > maximum:
        result.errors.append(
            f"The file has {len(raws)} items; a quiz can have at most {maximum}. "
            "Split it into two quizzes."
        )
        raws = raws[:maximum]

    seen_numbers: set[int] = set()
    next_number = 1

    for raw in raws:
        number = raw.number
        if number is None:
            number = next_number
        if number in seen_numbers:
            result.errors.append(
                f"{_where(raw, number)}: this item number is used twice. "
                "Give every item its own number."
            )
            continue
        seen_numbers.add(number)
        next_number = max(next_number, number + 1)

        where = _where(raw, number)
        prompt = clean_text(raw.prompt)
        if not prompt:
            result.errors.append(
                f"{where}: the question text is empty. Put the question on the "
                "line(s) before the choices."
            )
            continue
        if len(prompt) > QUIZ_PROMPT_MAX:
            result.errors.append(
                f"{where}: the question is {len(prompt)} characters; the limit "
                f"is {QUIZ_PROMPT_MAX}. Shorten it or split it."
            )
            continue

        choices = [clean_text(choice) for choice in raw.choices]
        if not 3 <= len(choices) <= 4:
            result.errors.append(
                f"{where}: found {len(choices)} choice(s). Provide 3 or 4 choices "
                "labelled A, B, C (and optionally D)."
            )
            continue
        if any(not choice for choice in choices):
            result.errors.append(
                f"{where}: one of the choices is empty. Fill in every choice you use."
            )
            continue
        if len({choice.casefold() for choice in choices}) != len(choices):
            result.errors.append(
                f"{where}: two choices are the same. Every choice must be different."
            )
            continue
        if any(len(choice) > QUIZ_CHOICE_MAX for choice in choices):
            result.errors.append(
                f"{where}: a choice is longer than {QUIZ_CHOICE_MAX} characters. "
                "Shorten it."
            )
            continue

        correct_index = answer_to_index(raw.answer)
        if correct_index is None:
            result.errors.append(
                f"{where}: the answer is missing or not a letter. Use "
                "``Answer: B`` (or 1-4 in a spreadsheet)."
            )
            continue
        if correct_index >= len(choices):
            result.errors.append(
                f"{where}: the answer points at a choice that does not exist. "
                f"With {len(choices)} choices, use A-{LETTERS[len(choices) - 1]}."
            )
            continue

        explanation = clean_text(raw.explanation)
        if len(explanation) > QUIZ_EXPLANATION_MAX:
            result.errors.append(
                f"{where}: the explanation is {len(explanation)} characters; the "
                f"limit is {QUIZ_EXPLANATION_MAX}. Shorten it."
            )
            continue

        if contains_blocked_language(" ".join([prompt, *choices])):
            result.warnings.append(
                f"{where}: the question or a choice may contain unsuitable "
                "language. Check it before activating."
            )

        result.items.append(
            ParsedItem(
                number=number,
                prompt=prompt,
                choices=choices,
                correct_index=correct_index,
                explanation=explanation,
                source_ref=raw.source_ref,
            )
        )

    return result


def difficulty_from_number(number: int, bands) -> str:
    """Return the band difficulty covering *number*, or ``""`` if unused."""
    for band in bands:
        if band.start <= number <= band.end:
            return band.difficulty
    return ""


def difficulty_is_valid(value: object) -> bool:
    return value in DIFFICULTY_KEYS


__all__ = [
    "LETTERS",
    "ParseResult",
    "ParsedItem",
    "RawItem",
    "answer_to_index",
    "clean_text",
    "difficulty_from_number",
    "validate_items",
]
