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

from game.models import (
    DIFFICULTY_KEYS,
    STAGE_DIFFICULTY,
    SUBJECT_KEYS,
    Question,
    QuestionAttempt,
    Tank,
)

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
    # Custom quiz snapshot (Phase 8); blank for built-in questions.
    difficulty: str = ""
    quiz_set_name: str = ""


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


# ------------------------------------------------------- custom quiz branch


def _nearest_difficulty(preferred: str, available: list[str]) -> str | None:
    """Pick *preferred*, else the nearest available band, preferring easier."""
    if preferred in available:
        return preferred
    if not available:
        return None
    index = DIFFICULTY_KEYS.index(preferred)
    for key in reversed(DIFFICULTY_KEYS[:index]):
        if key in available:
            return key
    for key in DIFFICULTY_KEYS[index + 1 :]:
        if key in available:
            return key
    return None


def custom_allowed_difficulties(tank: Tank, fish=None) -> list[str]:
    """The band(s) a tank may draw from, based on its configured mode."""
    if tank.quiz_set_id is None:
        return []
    available = set(
        Question.objects.filter(
            quiz_set_id=tank.quiz_set_id,
            active=True,
            difficulty__in=DIFFICULTY_KEYS,
        ).values_list("difficulty", flat=True)
    )
    if tank.quiz_difficulty_mode == "fixed":
        return [tank.quiz_fixed_difficulty] if tank.quiz_fixed_difficulty else []
    if tank.quiz_difficulty_mode == "all":
        return [key for key in DIFFICULTY_KEYS if key in available]

    stage = getattr(fish, "stage", 0) or 0
    preferred = STAGE_DIFFICULTY.get(stage, "hard")
    nearest = _nearest_difficulty(preferred, [key for key in DIFFICULTY_KEYS if key in available])
    return [nearest] if nearest else []


def custom_pool_size(tank: Tank, fish=None) -> int:
    """How many questions the tank's current config can draw from (0 = warn)."""
    if tank.quiz_source != "custom" or tank.quiz_set_id is None:
        return 0
    return Question.objects.filter(
        quiz_set_id=tank.quiz_set_id,
        active=True,
        difficulty__in=custom_allowed_difficulties(tank, fish),
    ).count()


def _pick_custom(
    user, tank: Tank, fish, rng: random.Random
) -> PickedQuestion:
    """Uniform random question from the allowed bands, cycling the pool."""
    if tank.quiz_set_id is None:
        raise NoQuestionsAvailable("This tank has no custom quiz attached.")

    allowed = custom_allowed_difficulties(tank, fish)
    pool = list(
        Question.objects.select_related("quiz_set").filter(
            quiz_set_id=tank.quiz_set_id,
            active=True,
            difficulty__in=allowed,
        )
    )
    if not pool:
        raise NoQuestionsAvailable("This quiz has no active questions for the current band.")

    # Cycle the pool: exclude the most recent attempts from this set, but never
    # exclude the whole pool (a one-question quiz must still be playable).
    recent_limit = min(
        int(settings.GAME_SETTINGS["QUIZ_RECENT_EXCLUDE"]), max(0, len(pool) - 1)
    )
    recent_ids = []
    if recent_limit:
        recent_ids = list(
            QuestionAttempt.objects.filter(
                user=user, question__quiz_set_id=tank.quiz_set_id
            )
            .order_by("-issued_at")
            .values_list("question_id", flat=True)[:recent_limit]
        )
    pool_ids = {question.pk for question in pool}
    excluded = {pk for pk in recent_ids if pk in pool_ids}
    candidates = [question for question in pool if question.pk not in excluded]
    if not candidates:
        candidates = pool

    question = rng.choice(candidates)
    correct_text = question.choices[question.correct_index]
    choices, correct_index = _shuffle(question.choices, correct_text, rng)
    return PickedQuestion(
        subject="custom",
        grade=0,
        prompt=question.prompt,
        choices=choices,
        correct_index=correct_index,
        explanation=question.explanation,
        question=question,
        difficulty=question.difficulty,
        quiz_set_name=question.quiz_set.name,
    )


def pick_question(
    user, tank: Tank, rng: random.Random | None = None, fish=None
) -> PickedQuestion:
    """Return a question for *tank*, or raise :class:`NoQuestionsAvailable`.

    A tank with a custom quiz draws from that set's allowed difficulty bands.
    Built-in tanks try their subjects in a shuffled order, so a tank that asks
    for science and math does not always get the same subject first. If a
    subject has no active question at the tank's grade, the next subject is
    tried; math is always available because it is generated.
    """
    rng = rng or random.Random()
    if tank.quiz_source == "custom":
        return _pick_custom(user, tank, fish, rng)
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
