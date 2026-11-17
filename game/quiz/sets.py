"""Quiz-set management services (Phase 8).

Creating drafts, editing bands, activating, deleting and attaching a set to a
tank all live here so the views stay thin.  Uploaded files never reach this
module: it only receives validated :class:`ParsedItem` rows.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from game.models import (
    DIFFICULTIES,
    DIFFICULTY_KEYS,
    QUIZ_DIFFICULTY_MODE_KEYS,
    QUIZ_SOURCE_KEYS,
    Question,
    QuizBand,
    QuizSet,
    Tank,
)
from game.quiz.importers.base import clean_text

MAX_NAME = QuizSet._meta.get_field("name").max_length


def owned_set_or_404(owner, quiz_set_id) -> QuizSet:
    """Another user's set is indistinguishable from a missing one."""
    quiz_set = QuizSet.objects.filter(pk=quiz_set_id, owner=owner).first()
    if quiz_set is None:
        raise QuizSet.DoesNotExist
    return quiz_set


# ------------------------------------------------------------------ creating


def create_draft_set(owner, name: str, filename: str, fmt: str, items) -> QuizSet:
    """Create a draft set plus its parsed questions.

    Enforces the per-user quota and the maximum question count.  Raises
    :class:`ValidationError` with a message a teacher can act on.
    """
    name = clean_text(name)
    if not name:
        raise ValidationError("Give the quiz a name.")
    if len(name) > MAX_NAME:
        raise ValidationError(f"The quiz name cannot exceed {MAX_NAME} characters.")
    if not items:
        raise ValidationError("That file contained no usable questions.")

    per_user = int(settings.GAME_SETTINGS["QUIZ_SETS_PER_USER"])
    if QuizSet.objects.filter(owner=owner).count() >= per_user:
        raise ValidationError(
            f"You already have {per_user} quizzes. Delete one before uploading another."
        )

    maximum = int(settings.GAME_SETTINGS["QUIZ_SET_MAX_QUESTIONS"])
    if len(items) > maximum:
        raise ValidationError(
            f"That file has {len(items)} items; a quiz can have at most {maximum}."
        )

    with transaction.atomic():
        quiz_set = QuizSet.objects.create(
            owner=owner,
            name=name,
            status="draft",
            source_filename=filename[:100],
            source_format=fmt,
        )
        Question.objects.bulk_create(
            [
                Question(
                    subject="custom",
                    grade=0,
                    prompt=item.prompt,
                    choices=list(item.choices),
                    correct_index=item.correct_index,
                    explanation=item.explanation,
                    active=True,
                    quiz_set=quiz_set,
                    item_number=item.number,
                    difficulty="",
                )
                for item in items
            ]
        )
    return quiz_set


def purge_expired_drafts(now=None) -> int:
    """Delete draft sets older than ``QUIZ_DRAFT_TTL_HOURS``; return the count."""
    now = now or timezone.now()
    hours = int(settings.GAME_SETTINGS["QUIZ_DRAFT_TTL_HOURS"])
    cutoff = now - timedelta(hours=hours)
    drafts = QuizSet.objects.filter(status="draft", created_at__lt=cutoff)
    count = drafts.count()
    drafts.delete()
    return count


# --------------------------------------------------------------------- bands


def parse_band_input(rows) -> list[tuple[str, int, int]]:
    """Clean three rows of ``(difficulty, start, end)`` into validated ranges.

    Empty rows are skipped; anything else must be complete and in order.
    Overlap is checked across every row, including rows of the same difficulty.
    """
    bands: list[tuple[str, int, int]] = []
    for difficulty, start, end in rows:
        if difficulty not in DIFFICULTY_KEYS:
            raise ValidationError("Pick Easy, Medium or Hard for every band.")
        has_start = start not in (None, "")
        has_end = end not in (None, "")
        if not has_start and not has_end:
            continue
        if not (has_start and has_end):
            raise ValidationError(
                "A band needs both a first and a last item number."
            )
        try:
            first, last = int(start), int(end)
        except (TypeError, ValueError):
            raise ValidationError("Band item numbers must be whole numbers.")
        if first < 1:
            raise ValidationError("The first item number must be 1 or more.")
        if last < first:
            raise ValidationError(
                "The last item number must not be smaller than the first."
            )
        if any(key == difficulty for key, _s, _e in bands):
            raise ValidationError(
                f"There is more than one {dict(DIFFICULTIES)[difficulty]} band."
            )
        for key, other_start, other_end in bands:
            if first <= other_end and last >= other_start:
                raise ValidationError(
                    f"The {dict(DIFFICULTIES)[difficulty]} band overlaps the "
                    f"{dict(DIFFICULTIES)[key]} band."
                )
        bands.append((difficulty, first, last))
    if not bands:
        raise ValidationError("Set at least one difficulty band.")
    return bands


def save_bands(quiz_set: QuizSet, bands: list[tuple[str, int, int]]) -> QuizSet:
    """Replace the set's bands and recompute every question's difficulty."""
    with transaction.atomic():
        QuizBand.objects.filter(quiz_set=quiz_set).delete()
        QuizBand.objects.bulk_create(
            [
                QuizBand(quiz_set=quiz_set, difficulty=key, start=start, end=end)
                for key, start, end in bands
            ]
        )
        recompute_difficulties(quiz_set)
    return quiz_set


def recompute_difficulties(quiz_set: QuizSet) -> int:
    """Clear then set ``Question.difficulty`` from the bands (one query per band)."""
    Question.objects.filter(quiz_set=quiz_set).update(difficulty="")
    updated = 0
    for band in quiz_set.bands.all():
        updated += Question.objects.filter(
            quiz_set=quiz_set, item_number__range=(band.start, band.end)
        ).update(difficulty=band.difficulty)
    return updated


def suggested_bands(item_numbers: list[int]) -> list[dict]:
    """Split the valid item numbers into three contiguous thirds."""
    numbers = sorted(item_numbers)
    if not numbers:
        return []
    size = max(1, -(-len(numbers) // 3))  # ceil division
    chunks = [numbers[0:size], numbers[size : 2 * size], numbers[2 * size :]]
    suggestions = []
    for (key, _label), chunk in zip(DIFFICULTIES, chunks):
        if chunk:
            suggestions.append({"difficulty": key, "start": chunk[0], "end": chunk[-1]})
    return suggestions


def band_summaries(quiz_set: QuizSet) -> list[dict]:
    """Bands with their active-question counts, for the preview page."""
    rows = []
    for band in quiz_set.bands.all():
        count = quiz_set.questions.filter(
            item_number__range=(band.start, band.end), active=True
        ).count()
        rows.append(
            {
                "difficulty": band.difficulty,
                "label": band.get_difficulty_display(),
                "start": band.start,
                "end": band.end,
                "count": count,
            }
        )
    return rows


def uncovered_numbers(quiz_set: QuizSet) -> list[int]:
    """Item numbers that fall outside every band (they are never issued)."""
    bands = list(quiz_set.bands.all())
    return [
        number
        for number in quiz_set.questions.order_by("item_number").values_list(
            "item_number", flat=True
        )
        if number is not None and not any(b.start <= number <= b.end for b in bands)
    ]


def activate_set(quiz_set: QuizSet) -> QuizSet:
    """Activate a draft once it has enough banded questions and a band."""
    minimum = int(settings.GAME_SETTINGS["QUIZ_MIN_QUESTIONS_TO_ACTIVATE"])
    if not quiz_set.bands.exists():
        raise ValidationError("Set at least one difficulty band first.")
    usable = quiz_set.questions.filter(active=True).exclude(difficulty="").count()
    if usable < minimum:
        raise ValidationError(
            f"This quiz has {usable} usable question(s); at least {minimum} are "
            "needed before players can use it. Widen a band or add more items."
        )
    quiz_set.status = "active"
    quiz_set.save(update_fields=["status"])
    return quiz_set


def deactivate_set(quiz_set: QuizSet) -> QuizSet:
    """Moderation helper: stop new questions without deleting the set."""
    quiz_set.status = "draft"
    quiz_set.save(update_fields=["status"])
    Tank.objects.filter(quiz_set=quiz_set).update(
        quiz_source="builtin",
        quiz_set=None,
        quiz_difficulty_mode="by_stage",
        quiz_fixed_difficulty="",
    )
    return quiz_set


def tanks_using(quiz_set: QuizSet):
    return Tank.objects.filter(quiz_set=quiz_set).select_related("owner")


def delete_set(quiz_set: QuizSet) -> list[str]:
    """Delete a set and revert every tank using it to built-in questions."""
    with transaction.atomic():
        names = list(tanks_using(quiz_set).values_list("name", flat=True))
        Tank.objects.filter(quiz_set=quiz_set).update(
            quiz_source="builtin",
            quiz_set=None,
            quiz_difficulty_mode="by_stage",
            quiz_fixed_difficulty="",
        )
        quiz_set.delete()
    return names


# --------------------------------------------------------------- tank config


def update_tank_quiz_config(
    tank: Tank,
    actor,
    *,
    source=None,
    quiz_set_id=None,
    difficulty_mode=None,
    fixed_difficulty=None,
) -> Tank:
    """Owner-only: switch a tank between built-in and one custom quiz.

    Only fields that are supplied change, so the existing grade/subject form can
    keep posting just those two.
    """
    if tank.owner_id != getattr(actor, "pk", None):
        raise PermissionDenied("Only the tank owner can change the quiz source.")

    if source is not None:
        if source not in QUIZ_SOURCE_KEYS:
            raise ValidationError("Unknown quiz source.")
        tank.quiz_source = source
    if difficulty_mode is not None:
        if difficulty_mode not in QUIZ_DIFFICULTY_MODE_KEYS:
            raise ValidationError("Unknown difficulty mode.")
        tank.quiz_difficulty_mode = difficulty_mode

    if tank.quiz_source == "builtin":
        tank.quiz_set = None
        tank.quiz_difficulty_mode = "by_stage"
        tank.quiz_fixed_difficulty = ""
    else:
        if quiz_set_id not in (None, ""):
            try:
                quiz_set_id = int(quiz_set_id)
            except (TypeError, ValueError):
                raise ValidationError("Pick one of your quizzes.")
            quiz_set = QuizSet.objects.filter(
                pk=quiz_set_id, owner=tank.owner, status="active"
            ).first()
            if quiz_set is None:
                raise ValidationError("Pick one of your active quizzes.")
            tank.quiz_set = quiz_set
        elif tank.quiz_set_id is None:
            raise ValidationError("Pick one of your quizzes.")
        elif (
            tank.quiz_set.owner_id != tank.owner_id
            or tank.quiz_set.status != "active"
        ):
            raise ValidationError("Pick one of your active quizzes.")

    if fixed_difficulty is not None:
        fixed_difficulty = clean_text(fixed_difficulty)
        if fixed_difficulty and fixed_difficulty not in DIFFICULTY_KEYS:
            raise ValidationError("Pick a difficulty band.")
        tank.quiz_fixed_difficulty = fixed_difficulty

    if tank.quiz_difficulty_mode == "fixed":
        if tank.quiz_fixed_difficulty not in DIFFICULTY_KEYS:
            raise ValidationError("Pick a difficulty band for fixed mode.")
        if tank.quiz_set_id and not tank.quiz_set.bands.filter(
            difficulty=tank.quiz_fixed_difficulty
        ).exists():
            raise ValidationError(
                f"{tank.quiz_set.name} has no "
                f"{dict(DIFFICULTIES)[tank.quiz_fixed_difficulty]} band."
            )

    tank.save(
        update_fields=[
            "quiz_source",
            "quiz_set",
            "quiz_difficulty_mode",
            "quiz_fixed_difficulty",
        ]
    )
    return tank


def quiz_set_question_numbers(quiz_set: QuizSet) -> list[int]:
    return [
        number
        for number in quiz_set.questions.order_by("item_number").values_list(
            "item_number", flat=True
        )
        if number is not None
    ]


__all__ = [
    "activate_set",
    "band_summaries",
    "create_draft_set",
    "deactivate_set",
    "delete_set",
    "owned_set_or_404",
    "parse_band_input",
    "purge_expired_drafts",
    "quiz_set_question_numbers",
    "recompute_difficulties",
    "save_bands",
    "suggested_bands",
    "tanks_using",
    "uncovered_numbers",
    "update_tank_quiz_config",
]
