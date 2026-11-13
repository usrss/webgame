"""Shared player-text validation (Phases 2 and 5).

Tank names and fish names (including renames and admin edits) are validated by
the same function, so the character rules and the profanity filter live in
exactly one place.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from django.core.exceptions import ValidationError

# Letters, digits, spaces, apostrophe, hyphen and underscore. Deliberately
# excludes HTML characters, emoji, punctuation and every control character.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _'\-]+$")

# Control characters are rejected outright rather than folded into spaces.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")

# Shortest accepted name for both tanks and fish.
MIN_NAME_LENGTH = 2

BLOCKLIST_PATH = Path(__file__).resolve().parent / "data" / "blocked_words.txt"

# Leetspeak substitutions applied before matching, in both directions.
_LEET_MAP = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "@": "a",
        "$": "s",
    }
)

# Placeholder severe terms matched as substrings, because they are not real
# words on their own. Kept very short to limit false positives (Scunthorpe).
SEVERE_SUBSTRINGS = ("verybadterm1", "verybadterm2")

GENERIC_BLOCKED_MESSAGE = "That name isn't allowed."


def _normalize_token(token: str) -> str:
    """Lowercase, undo leetspeak, drop punctuation and collapse letter runs."""
    token = token.lower().translate(_LEET_MAP)
    token = re.sub(r"[^a-z0-9]", "", token)
    return re.sub(r"(.)\1+", r"\1", token)


@lru_cache(maxsize=1)
def get_blocklist() -> tuple[str, ...]:
    """Load the project-owned blocklist (cached). Missing file = empty list."""
    try:
        lines = BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    terms = []
    for line in lines:
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append(term)
    return tuple(terms)


def contains_blocked_language(value: str, blocklist=None) -> bool:
    """Return True when *value* hits the blocklist after normalization.

    Matching strategy:

    * whole-token match on the normalized name, and on the concatenation of all
      tokens (so ``bad word1`` or ``b a d w o r d 1`` can't slip past);
    * substring match only for the short :data:`SEVERE_SUBSTRINGS` list.

    Whole-token matching is what keeps innocent words that merely contain a
    blocked substring (the Scunthorpe problem) from being rejected.

    *blocklist* exists so tests can inject fake terms instead of shipping real
    offensive words in the repository.
    """
    terms = get_blocklist() if blocklist is None else blocklist
    normalized_terms = {_normalize_token(term) for term in terms if term}
    if not normalized_terms:
        return False

    tokens = [_normalize_token(part) for part in re.split(r"[^A-Za-z0-9]+", value)]
    tokens = [token for token in tokens if token]
    if not tokens:
        return False

    if any(token in normalized_terms for token in tokens):
        return True
    joined = "".join(tokens)
    if joined in normalized_terms:
        return True
    return any(_normalize_token(term) in joined for term in SEVERE_SUBSTRINGS)


def validate_display_name(
    value: object,
    *,
    max_length: int,
    field_label: str = "Name",
) -> str:
    """Clean and validate a player-supplied tank or fish name.

    Trims the ends and collapses internal whitespace runs to a single space,
    enforces the ``MIN_NAME_LENGTH``..``max_length`` range, rejects any character
    outside letters, digits, spaces, ``'``, ``-`` and ``_``, and rejects names
    that hit the blocklist.

    Returns the cleaned string; raises :class:`ValidationError` otherwise. The
    profanity error is deliberately generic so it never echoes the matched term.
    """
    text = "" if value is None else str(value)
    if _CONTROL_CHARACTERS.search(text):
        raise ValidationError(
            f"{field_label} can't contain line breaks, tabs or control characters."
        )

    cleaned = " ".join(text.split())

    if len(cleaned) < MIN_NAME_LENGTH:
        raise ValidationError(
            f"{field_label} must be at least {MIN_NAME_LENGTH} characters long."
        )
    if len(cleaned) > max_length:
        raise ValidationError(
            f"{field_label} cannot exceed {max_length} characters."
        )
    if not NAME_PATTERN.fullmatch(cleaned):
        raise ValidationError(
            f"{field_label} may only contain letters, numbers, spaces, "
            "apostrophes, hyphens and underscores."
        )
    if contains_blocked_language(cleaned):
        raise ValidationError(GENERIC_BLOCKED_MESSAGE)

    return cleaned
