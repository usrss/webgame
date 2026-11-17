"""Quiz services: issuing questions and turning correct answers into feeds.

All quiz rules live here (Phase 7); views only parse input and shape JSON.
Tunable numbers come from ``GAME_SETTINGS``, read at call time so tests and
per-deployment overrides take effect immediately.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from game.models import (
    QUIZ_GRADE_MAX,
    QUIZ_GRADE_MIN,
    SUBJECT_KEYS,
    Fish,
    QuestionAttempt,
    Tank,
)
from game.services import FeedResult, feed

from .bank import pick_question
from .exceptions import (
    AttemptAlreadyAnswered,
    AttemptExpired,
    AttemptNotFound,
    DailyCapReached,
    IssueTooFast,
    NoQuestionsAvailable,
    NotAMember,
    QuizError,
    QuizInvalid,
)

__all__ = [
    "AnswerResult",
    "AttemptAlreadyAnswered",
    "AttemptExpired",
    "AttemptNotFound",
    "DailyCapReached",
    "IssueTooFast",
    "NoQuestionsAvailable",
    "NotAMember",
    "QuizError",
    "QuizInvalid",
    "answer_question",
    "correct_answers_today",
    "issue_question",
    "quiz_day_end",
    "quiz_day_start",
    "quiz_state",
    "remaining_today",
    "seconds_until_reset",
    "update_quiz_settings",
]


@dataclass
class AnswerResult:
    """Outcome of one quiz answer, safe to serialize after the attempt closes."""

    attempt: QuestionAttempt
    correct: bool
    explanation: str
    remaining_today: int
    feed: FeedResult | None = None


# --------------------------------------------------------------- day boundary


def _local_midnight(day: date) -> datetime:
    """Midnight at the start of *day* in Django's configured ``TIME_ZONE``."""
    naive = datetime.combine(day, time.min)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def quiz_day_start(now: datetime | None = None) -> datetime:
    """Start of the player's local day (local midnight), as an aware datetime."""
    now = now or timezone.now()
    return _local_midnight(timezone.localtime(now).date())


def quiz_day_end(now: datetime | None = None) -> datetime:
    """Start of the next local day.

    Computed from the *next date* rather than ``start + 24h`` so a DST change
    cannot shift the boundary away from local midnight.
    """
    now = now or timezone.now()
    tomorrow = timezone.localtime(now).date() + timedelta(days=1)
    return _local_midnight(tomorrow)


def seconds_until_reset(now: datetime | None = None) -> int:
    """Whole seconds until the daily cap resets at local midnight."""
    now = now or timezone.now()
    return max(1, math.ceil((quiz_day_end(now) - now).total_seconds()))


# ---------------------------------------------------------------------- counts


def correct_answers_today(fish: Fish, now: datetime | None = None) -> int:
    """Correct answers (i.e. earned feeds) for *fish* in the current local day."""
    now = now or timezone.now()
    return QuestionAttempt.objects.filter(
        fish=fish,
        correct=True,
        answered_at__gte=quiz_day_start(now),
        answered_at__lt=quiz_day_end(now),
    ).count()


def remaining_today(fish: Fish, now: datetime | None = None) -> int:
    """Correct answers still available today (never negative)."""
    cap = settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"]
    return max(0, cap - correct_answers_today(fish, now=now))


def quiz_state(tank: Tank, fish: Fish, now: datetime | None = None) -> dict:
    """The ``quiz`` block of the tank state payload (my fish only)."""
    now = now or timezone.now()
    return {
        "enabled": bool(settings.GAME_SETTINGS["QUIZ_ENABLED"]),
        "only_feeding": bool(settings.GAME_SETTINGS["QUIZ_ONLY_FEEDING"]),
        "remaining_today": remaining_today(fish, now=now),
        "cap": settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"],
        "grade": tank.quiz_grade,
        "subjects": list(tank.quiz_subjects or []),
        "source": tank.quiz_source,
        "set_name": tank.quiz_set.name if tank.quiz_source == "custom" and tank.quiz_set else "",
        "difficulty_mode": tank.quiz_difficulty_mode,
    }


# --------------------------------------------------------------------- issuing


def _fish_for(user, tank: Tank) -> Fish:
    fish = Fish.objects.filter(tank=tank, owner=user).first()
    if fish is None:
        raise NotAMember("You are not a member of this tank.")
    return fish


def issue_question(user, tank: Tank, now: datetime | None = None) -> QuestionAttempt:
    """Return the open question, or issue a new one.

    Re-returning the same unanswered, unexpired attempt is deliberate: otherwise
    a player could re-roll until an easy question appeared. Expired attempts are
    ignored (never deleted here; ``purge_old_attempts`` handles retention).
    """
    now = now or timezone.now()
    fish = _fish_for(user, tank)

    if remaining_today(fish, now=now) <= 0:
        raise DailyCapReached(seconds_until_reset(now))

    ttl_seconds = settings.GAME_SETTINGS["QUIZ_ATTEMPT_TTL_SECONDS"]
    unexpired_after = now - timedelta(seconds=ttl_seconds)
    open_attempt = (
        QuestionAttempt.objects.filter(
            fish=fish,
            answered_at__isnull=True,
            issued_at__gt=unexpired_after,
        )
        .order_by("-issued_at")
        .first()
    )
    if open_attempt is not None:
        return open_attempt

    minimum_gap = settings.GAME_SETTINGS["QUIZ_MIN_SECONDS_BETWEEN_ISSUES"]
    last_attempt = (
        QuestionAttempt.objects.filter(user=user, fish=fish)
        .order_by("-issued_at")
        .first()
    )
    if last_attempt is not None:
        elapsed = (now - last_attempt.issued_at).total_seconds()
        if elapsed < minimum_gap:
            raise IssueTooFast(max(1, math.ceil(minimum_gap - elapsed)))

    picked = pick_question(user, tank, fish=fish)
    return QuestionAttempt.objects.create(
        user=user,
        fish=fish,
        question=picked.question,
        subject=picked.subject,
        grade=picked.grade,
        prompt=picked.prompt,
        choices=picked.choices,
        correct_index=picked.correct_index,
        explanation=picked.explanation,
        difficulty=picked.difficulty,
        quiz_set_name=picked.quiz_set_name,
        issued_at=now,
    )


# -------------------------------------------------------------------- answering


def _valid_selected_index(selected_index, choices) -> bool:
    # ``bool`` is an ``int`` subclass, and JSON floats like 2.0 are not "integer".
    if isinstance(selected_index, bool) or not isinstance(selected_index, int):
        return False
    return 0 <= selected_index < len(choices)


def answer_question(
    user, attempt_id: int, selected_index: int, now: datetime | None = None
) -> AnswerResult:
    """Close one attempt and, if it was correct, feed the fish exactly once.

    Locks the attempt first and the fish second (always that order, so
    concurrent answers cannot deadlock), then re-checks the daily cap inside the
    lock. Answering an already-answered attempt raises
    :class:`AttemptAlreadyAnswered` and never feeds again.
    """
    now = now or timezone.now()

    with transaction.atomic():
        attempt = (
            QuestionAttempt.objects.select_for_update()
            .filter(pk=attempt_id, user=user)
            .first()
        )
        if attempt is None:
            # Other users' attempt ids are indistinguishable from missing ones.
            raise AttemptNotFound("That question is no longer available.")

        fish = Fish.objects.select_for_update().get(pk=attempt.fish_id)

        if attempt.answered_at is not None:
            raise AttemptAlreadyAnswered("That question was already answered.")

        ttl_seconds = settings.GAME_SETTINGS["QUIZ_ATTEMPT_TTL_SECONDS"]
        if attempt.issued_at + timedelta(seconds=ttl_seconds) <= now:
            raise AttemptExpired("That question expired; fetch a new one.")

        if not _valid_selected_index(selected_index, attempt.choices):
            raise QuizInvalid("Pick one of the answer choices.")

        remaining = remaining_today(fish, now=now)
        if remaining <= 0:
            raise DailyCapReached(seconds_until_reset(now))

        correct = selected_index == attempt.correct_index
        attempt.answered_at = now
        attempt.selected_index = selected_index
        attempt.correct = correct
        attempt.save(update_fields=["answered_at", "selected_index", "correct"])

        feed_result = None
        if correct:
            feed_result = feed(fish, now=now, enforce_cooldown=False)

        # Deliberately no correct index in the result: the answer is never sent
        # to the client, not even for a wrong attempt (players could otherwise
        # answer wrong on purpose to harvest the key).
        return AnswerResult(
            attempt=attempt,
            correct=correct,
            explanation=attempt.explanation if correct else "",
            remaining_today=max(0, remaining - (1 if correct else 0)),
            feed=feed_result,
        )


# ------------------------------------------------------------ owner settings


def update_quiz_settings(tank: Tank, actor, grade, subjects) -> Tank:
    """Owner-only: set the tank's grade (1-6) and subject list.

    Validation happens here so neither a crafted request nor a form can store an
    invalid grade or an empty subject list.
    """
    if tank.owner_id != getattr(actor, "pk", None):
        raise PermissionDenied("Only the tank owner can change the quiz settings.")

    try:
        grade = int(grade)
    except (TypeError, ValueError):
        raise ValidationError("Grade must be a whole number from 1 to 6.")
    if not QUIZ_GRADE_MIN <= grade <= QUIZ_GRADE_MAX:
        raise ValidationError("Grade must be between 1 and 6.")

    if isinstance(subjects, str):
        subjects = [subjects]
    cleaned = [value for value in (subjects or []) if value]
    unknown = [value for value in cleaned if value not in SUBJECT_KEYS]
    if unknown:
        raise ValidationError(f"Unknown subject: {unknown[0]}.")
    # De-duplicate while keeping the canonical order.
    cleaned = [key for key in SUBJECT_KEYS if key in set(cleaned)]
    if not cleaned:
        raise ValidationError("Pick at least one subject.")

    tank.quiz_grade = grade
    tank.quiz_subjects = cleaned
    tank.save(update_fields=["quiz_grade", "quiz_subjects"])
    return tank
