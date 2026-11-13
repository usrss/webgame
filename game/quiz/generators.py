"""Elementary-level math question generator (Phase 7).

Pure functions: no database access and no global randomness. Every generator
accepts an optional ``rng`` (a ``random.Random``) so tests are deterministic.

Each generator returns a :class:`MathQuestion` - a ``NamedTuple`` of
``(prompt, correct, distractors)`` - where ``correct`` and every distractor are
formatted strings in the same style (integers, one-decimal numbers or
fractions). Distractors are plausible (off by one, off by ten, common
fraction mistakes), distinct, never equal to the correct answer and never
negative.

Choices are shuffled and indexed later, in ``bank.pick_question``.
"""

from __future__ import annotations

import random
from fractions import Fraction
from typing import NamedTuple

from django.conf import settings

MAX_GRADE = 6
MIN_GRADE = 1


class MathQuestion(NamedTuple):
    """``(prompt, correct_answer, distractors)``, ready to be shuffled."""

    prompt: str
    correct: str
    distractors: list[str]


def _format_int(value) -> str:
    return str(int(value))


def _format_tenths(value: Fraction) -> str:
    """Format a value given in tenths as ``3.4`` (never via float rounding)."""
    tenths = int(value)
    return f"{tenths // 10}.{tenths % 10}"


def _format_fraction(value: Fraction) -> str:
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _finish(
    prompt: str,
    correct_value,
    candidates,
    formatter,
    step,
    *,
    allow_zero: bool = True,
) -> MathQuestion:
    """Build a question, keeping only plausible, distinct, non-negative choices."""
    choice_count = settings.GAME_SETTINGS["QUIZ_CHOICES"]
    correct_text = formatter(correct_value)
    picked: list[str] = []
    seen = {correct_text}

    def accept(value) -> None:
        if value < 0:
            return
        if value == 0 and not allow_zero:
            return
        text = formatter(value)
        if text in seen:
            return
        seen.add(text)
        picked.append(text)

    for candidate in candidates:
        if len(picked) >= choice_count - 1:
            break
        accept(candidate)

    # Always end with enough choices, even if the smart candidates collided.
    offset = 1
    while len(picked) < choice_count - 1:
        accept(correct_value + step * offset)
        if len(picked) < choice_count - 1:
            accept(correct_value - step * offset)
        offset += 1
        if offset > 500:  # pragma: no cover - defensive, cannot happen in range
            raise RuntimeError("Could not build distinct math choices")

    return MathQuestion(prompt=prompt, correct=correct_text, distractors=picked)


# ------------------------------------------------------------------ grade 1-2


def _add_sub_within(rng: random.Random, limit: int) -> MathQuestion:
    """Addition or subtraction with both operands and the result within *limit*."""
    if rng.random() < 0.5:
        left = rng.randint(1, max(1, limit - 1))
        right = rng.randint(1, max(1, limit - left))
        correct = left + right
        prompt = f"{left} + {right} = ?"
    else:
        left = rng.randint(1, limit)
        right = rng.randint(0, left)
        correct = left - right
        prompt = f"{left} - {right} = ?"

    candidates = [
        correct + 1,
        correct - 1,
        correct + 2,
        correct - 2,
        correct + 10,
        correct - 10,
        correct + 3,
    ]
    return _finish(prompt, correct, candidates, _format_int, step=1)


def generate_grade_1(rng: random.Random) -> MathQuestion:
    """Add/subtract within 20."""
    return _add_sub_within(rng, 20)


def generate_grade_2(rng: random.Random) -> MathQuestion:
    """Add/subtract within 100."""
    return _add_sub_within(rng, 100)


# -------------------------------------------------------------------- grade 3


def generate_grade_3(rng: random.Random) -> MathQuestion:
    """Multiplication and division facts up to 10 x 10."""
    left = rng.randint(2, 10)
    right = rng.randint(2, 10)
    product = left * right

    if rng.random() < 0.5:
        candidates = [
            product + left,
            product - left,
            product + right,
            product - right,
            product + 1,
            product - 1,
            product + 10,
        ]
        return _finish(
            f"{left} × {right} = ?", product, candidates, _format_int, step=1
        )

    # Division: always exact, and read as the inverse of a known fact.
    candidates = [
        right + 1,
        right - 1,
        right + 2,
        right - 2,
        product - right,
        left,
        right * 2,
    ]
    return _finish(
        f"{product} ÷ {left} = ?", right, candidates, _format_int, step=1
    )


# -------------------------------------------------------------------- grade 4


def generate_grade_4(rng: random.Random) -> MathQuestion:
    """Multi-digit add/subtract, 2-digit x 1-digit, and exact division."""
    kind = rng.choice(["add", "subtract", "multiply", "divide"])

    if kind == "add":
        left = rng.randint(101, 899)
        right = rng.randint(11, 98)
        correct = left + right
        candidates = [
            correct + 1,
            correct - 1,
            correct + 10,
            correct - 10,
            correct + 100,
            correct - 100,
        ]
        return _finish(
            f"{left} + {right} = ?", correct, candidates, _format_int, step=1
        )

    if kind == "subtract":
        left = rng.randint(201, 999)
        right = rng.randint(11, 199)
        correct = left - right
        candidates = [
            correct + 1,
            correct - 1,
            correct + 10,
            correct - 10,
            correct + 100,
            correct - 100,
        ]
        return _finish(
            f"{left} - {right} = ?", correct, candidates, _format_int, step=1
        )

    if kind == "multiply":
        left = rng.randint(11, 99)
        right = rng.randint(2, 9)
        correct = left * right
        candidates = [
            correct + left,
            correct - left,
            correct + right,
            correct - right,
            correct + 10,
            correct - 10,
        ]
        return _finish(
            f"{left} × {right} = ?", correct, candidates, _format_int, step=1
        )

    divisor = rng.randint(2, 9)
    quotient = rng.randint(11, 99)
    dividend = divisor * quotient
    candidates = [
        quotient + 1,
        quotient - 1,
        quotient + 10,
        quotient - 10,
        divisor,
        quotient * 2,
    ]
    return _finish(
        f"{dividend} ÷ {divisor} = ?", quotient, candidates, _format_int, step=1
    )


# -------------------------------------------------------------------- grade 5

_TENTH = Fraction(1, 10)


def _generate_same_denominator_fractions(rng: random.Random) -> MathQuestion:
    denominator = rng.randint(4, 10)
    if rng.random() < 0.5:
        first = rng.randint(1, denominator - 2)
        second = rng.randint(1, denominator - first - 1)
        total = Fraction(first + second, denominator)
        prompt = f"{first}/{denominator} + {second}/{denominator} = ?"
        # Common mistakes, then the chance that denominators were added.
        candidates = [
            Fraction(first + second, denominator * 2),
            Fraction(first + second + 1, denominator),
            Fraction(first + second, denominator) + Fraction(1, denominator),
            Fraction(first + second, denominator) - Fraction(1, denominator),
        ]
        return _finish(
            prompt, total, candidates, _format_fraction, step=Fraction(1, denominator)
        )

    first = rng.randint(2, denominator - 1)
    second = rng.randint(1, first - 1)
    difference = Fraction(first - second, denominator)
    prompt = f"{first}/{denominator} - {second}/{denominator} = ?"
    candidates = [
        Fraction(first - second, denominator * 2),
        Fraction(first - second + 1, denominator),
        Fraction(first + second, denominator),
        difference + Fraction(1, denominator),
    ]
    return _finish(
        prompt,
        difference,
        candidates,
        _format_fraction,
        step=Fraction(1, denominator),
        allow_zero=False,
    )


def _generate_decimals(rng: random.Random) -> MathQuestion:
    """One-decimal addition/subtraction, computed in integer tenths."""
    if rng.random() < 0.5:
        left = rng.randint(1, 60)
        right = rng.randint(1, 30)
        correct = left + right
        prompt = f"{_format_tenths(left)} + {_format_tenths(right)} = ?"
        candidates = [
            correct + 1,
            correct - 1,
            correct + 10,
            correct - 10,
            correct + 2,
            correct - 2,
        ]
    else:
        left = rng.randint(21, 99)
        right = rng.randint(1, left - 1)
        correct = left - right
        prompt = f"{_format_tenths(left)} - {_format_tenths(right)} = ?"
        candidates = [
            correct + 1,
            correct - 1,
            correct + 10,
            correct - 10,
            correct + 2,
            correct - 2,
        ]
    return _finish(prompt, correct, candidates, _format_tenths, step=1)


def _generate_order_of_operations(rng: random.Random) -> MathQuestion:
    """Two-step order of operations, e.g. ``2 + 3 × 4 = ?``."""
    if rng.random() < 0.5:
        first, second, third = rng.randint(1, 9), rng.randint(2, 9), rng.randint(2, 9)
        correct = first + second * third
        prompt = f"{first} + {second} × {third} = ?"
        candidates = [
            (first + second) * third,  # left-to-right mistake
            correct + second,
            correct - second,
            correct + 1,
            correct - 1,
        ]
    else:
        first, second = rng.randint(2, 9), rng.randint(2, 9)
        # Keep the result positive: never subtract more than the product.
        third = rng.randint(1, first * second - 1)
        correct = first * second - third
        prompt = f"{first} × {second} - {third} = ?"
        candidates = [
            correct + first,
            correct - first,
            first * (second - third),  # bracket mistake
            correct + 1,
            correct - 1,
        ]
    return _finish(prompt, correct, candidates, _format_int, step=1)


def generate_grade_5(rng: random.Random) -> MathQuestion:
    """Same-denominator fractions, decimals to tenths, two-step operations."""
    kind = rng.choice(["fraction", "decimal", "order"])
    if kind == "fraction":
        return _generate_same_denominator_fractions(rng)
    if kind == "decimal":
        return _generate_decimals(rng)
    return _generate_order_of_operations(rng)


# -------------------------------------------------------------------- grade 6


def _generate_unlike_fractions(rng: random.Random) -> MathQuestion:
    denominator_a = rng.choice([2, 3, 4, 5, 6])
    denominator_b = rng.choice([3, 4, 5, 6, 8])
    while denominator_b == denominator_a:
        denominator_b = rng.choice([3, 4, 5, 6, 8])

    numerator_a = rng.randint(1, denominator_a - 1)
    numerator_b = rng.randint(1, denominator_b - 1)
    left = Fraction(numerator_a, denominator_a)
    right = Fraction(numerator_b, denominator_b)

    if rng.random() < 0.5:
        correct = left + right
        prompt = (
            f"{numerator_a}/{denominator_a} + {numerator_b}/{denominator_b} = ?"
        )
        candidates = [
            Fraction(
                numerator_a + numerator_b, denominator_a + denominator_b
            ),  # added denominators
            correct + Fraction(1, denominator_a * denominator_b),
            correct - Fraction(1, denominator_a * denominator_b),
            left * right,  # multiplied instead of added
        ]
        step = Fraction(1, denominator_a * denominator_b)
        allow_zero = True
    else:
        correct = left - right
        if correct < 0:
            left, right = right, left
            numerator_a, denominator_a, numerator_b, denominator_b = (
                numerator_b,
                denominator_b,
                numerator_a,
                denominator_a,
            )
            correct = left - right
        prompt = (
            f"{numerator_a}/{denominator_a} - {numerator_b}/{denominator_b} = ?"
        )
        candidates = [
            Fraction(numerator_a + numerator_b, denominator_a + denominator_b),
            Fraction(abs(numerator_a - numerator_b), abs(denominator_a - denominator_b) or 1),
            correct + Fraction(1, denominator_a * denominator_b),
            correct - Fraction(1, denominator_a * denominator_b),
        ]
        step = Fraction(1, denominator_a * denominator_b)
        allow_zero = False

    # Keep the fraction format consistent (avoid "3" next to "4/5"): start
    # over until the result needs a denominator. Bounded so it cannot spin.
    if correct.denominator == 1:
        return _generate_unlike_fractions(rng)
    return _finish(
        prompt, correct, candidates, _format_fraction, step=step, allow_zero=allow_zero
    )


def _generate_percent(rng: random.Random) -> MathQuestion:
    """A percent of a multiple of ten, always with a whole-number answer."""
    percent = rng.choice([10, 20, 25, 50])
    multiples = [10, 20, 30, 40, 50, 60, 70, 80, 100]
    if percent == 25:
        multiples = [20, 40, 60, 80, 100]
    base = rng.choice(multiples)
    correct = base * percent // 100
    prompt = f"{percent}% of {base} = ?"
    candidates = [
        correct + 10,
        correct - 10,
        base - correct,
        percent,
        correct + 1,
    ]
    return _finish(
        prompt, correct, candidates, _format_int, step=1, allow_zero=False
    )


def _generate_ratio(rng: random.Random) -> MathQuestion:
    first = rng.randint(1, 5)
    second = rng.randint(2, 6)
    while second == first:
        second = rng.randint(2, 6)
    scale = rng.randint(2, 5)
    correct = second * scale
    prompt = f"{first} : {second} = {first * scale} : ?"
    candidates = [
        first * scale,
        correct + second,
        correct - second,
        first + second,
        correct + 1,
    ]
    return _finish(prompt, correct, candidates, _format_int, step=1)


def generate_grade_6(rng: random.Random) -> MathQuestion:
    """Unlike-denominator fractions, percent of a multiple of ten, simple ratio."""
    kind = rng.choice(["fraction", "percent", "ratio"])
    if kind == "fraction":
        return _generate_unlike_fractions(rng)
    if kind == "percent":
        return _generate_percent(rng)
    return _generate_ratio(rng)


# -------------------------------------------------------------------- dispatch

_GENERATORS = {
    1: generate_grade_1,
    2: generate_grade_2,
    3: generate_grade_3,
    4: generate_grade_4,
    5: generate_grade_5,
    6: generate_grade_6,
}


def generate_math(grade: int, rng: random.Random | None = None) -> MathQuestion:
    """Generate one math question for *grade* (1-6)."""
    if grade not in _GENERATORS:
        raise ValueError(f"No math generator for grade {grade!r}")
    return _GENERATORS[grade](rng or random.Random())
