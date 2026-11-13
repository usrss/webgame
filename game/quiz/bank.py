"""Question selection (Phase 7).

Picks a subject from the tank's configured list, generates a math question or
loads an active bank question at the tank's grade, and shuffles the choices
**server-side** so ``correct_index`` is only known after shuffling.

All randomness comes from an optional seeded ``rng`` so tests are deterministic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from django.conf import settings

from game.models import SUBJECT_KEYS, Question, QuestionAttempt, Tank

from .exceptions import NoQuestionsAvailable
from .generators import generate_math


@dataclass(frozen=True)
class PickedQuestion:
    """A question snapshot, ready to be stored as a ``QuestionAttempt``."""

    subject: str
    grade: int
    prompt: str
    choices: list[str] = field(default_factory=list)
    correct_index: int = 0
    explanation: str = ""
    question: Question | None = None


def _recent_question_ids(user) -> list[int]:
    """The user's last ``QUIZ_RECENT_EXCLUDE`` bank questions, newest first."""
    limit = settings.GAME_SETTINGS["QUIZ_RECENT_EXCLUDE"]
    return list(
        QuestionAttempt.objects.filter(user=user, question__isnull=False)
        .order_by("-issued_at")
        .values_list("question_id", flat=True)[:limit]
    )


def _shuffle(choices, correct_text: str, rng: random.Random) -> tuple[list[str], int]:
    """Shuffle choices and return them with the new index of the correct one."""
    options = list(choices)
    rng.shuffle(options)
    return options, options.index(correct_text)


def _from_bank(
    subject: str, grade: int, recent_ids: list[int], rng: random.Random
) -> PickedQuestion | None:
    """One active bank question, avoiding the user's recent ones when possible."""
    queryset = Question.objects.filter(active=True, subject=subject, grade=grade)
    pool = list(queryset.exclude(pk__in=recent_ids))
    if not pool:
        # Only fall back to repeats once the pool really is exhausted.
        pool = list(queryset)
    if not pool:
        return None

    question = rng.choice(pool)
    correct_text = question.choices[question.correct_index]
    choices, correct_index = _shuffle(question.choices, correct_text, rng)
    return PickedQuestion(
        subject=question.subject,
        grade=question.grade,
        prompt=question.prompt,
        choices=choices,
        correct_index=correct_index,
        explanation=question.explanation,
        question=question,
    )


def pick_question(user, tank: Tank, rng: random.Random | None = None) -> PickedQuestion:
    """Return a question for *tank*, or raise :class:`NoQuestionsAvailable`.

    Subjects are tried in a shuffled order, so a tank that asks for science and
    math does not always get the same subject first. If a subject has no active
    question at the tank's grade, the next subject is tried; math is always
    available because it is generated.
    """
    rng = rng or random.Random()
    configured = [key for key in (tank.quiz_subjects or []) if key in SUBJECT_KEYS]
    if not configured:
        configured = list(settings.GAME_SETTINGS["QUIZ_DEFAULT_SUBJECTS"])
    grade = tank.quiz_grade or settings.GAME_SETTINGS["QUIZ_DEFAULT_GRADE"]

    order = list(configured)
    rng.shuffle(order)
    recent_ids = _recent_question_ids(user)

    for subject in order:
        if subject == "math":
            generated = generate_math(grade, rng=rng)
            choices, correct_index = _shuffle(
                [generated.correct, *generated.distractors],
                generated.correct,
                rng,
            )
            return PickedQuestion(
                subject="math",
                grade=grade,
                prompt=generated.prompt,
                choices=choices,
                correct_index=correct_index,
            )

        picked = _from_bank(subject, grade, recent_ids, rng)
        if picked is not None:
            return picked

    raise NoQuestionsAvailable(
        f"No active questions for grade {grade} in {', '.join(configured)}."
    )
