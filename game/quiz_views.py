"""Owner-facing quiz upload and management views (Phase 8).

Every view is owner-scoped: another user's quiz set returns 404 exactly like a
missing one.  Parsing, validation and band rules live in ``game.quiz``; these
views only read the request, call a service and render.
"""

from __future__ import annotations

import io

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .forms import QuizUploadForm
from .models import DIFFICULTIES, QuizSet
from .quiz.importers import UploadRejected, parse_upload
from .quiz.importers.safety import sanitize_filename
from .quiz.sets import (
    activate_set,
    band_summaries,
    create_draft_set,
    delete_set,
    owned_set_or_404,
    parse_band_input,
    quiz_set_question_numbers,
    save_bands,
    suggested_bands,
    tanks_using,
    uncovered_numbers,
)
from .quiz.template_files import build_template
from .ratelimit import ratelimit

UPLOAD_LIMIT = settings.GAME_SETTINGS["QUIZ_UPLOADS_PER_HOUR"]

SESSION_ERRORS = "quiz_upload_errors"
SESSION_WARNINGS = "quiz_upload_warnings"
SESSION_ENCODING = "quiz_upload_encoding"


def _set_or_404(request, quiz_set_id) -> QuizSet:
    try:
        quiz_set = owned_set_or_404(request.user, quiz_set_id)
    except QuizSet.DoesNotExist:
        raise Http404("Quiz not found")
    return quiz_set


@login_required
@require_GET
def quiz_set_list(request):
    """All of the user's quizzes, with bands and the tanks that use them."""
    quiz_sets = (
        QuizSet.objects.filter(owner=request.user)
        .annotate(
            total=Count("questions"),
            active_total=Count("questions", filter=Q(questions__active=True)),
        )
        .order_by("-created_at")
    )
    rows = []
    for quiz_set in quiz_sets:
        bands = quiz_set.bands.all()
        rows.append(
            {
                "quiz_set": quiz_set,
                "total": quiz_set.total,
                "active_total": quiz_set.active_total,
                "bands": ", ".join(str(band) for band in bands) or "No bands yet",
                "tanks": list(tanks_using(quiz_set)),
            }
        )
    return render(
        request,
        "game/quiz_list.html",
        {
            "rows": rows,
            "max_sets": settings.GAME_SETTINGS["QUIZ_SETS_PER_USER"],
        },
    )


@login_required
@ratelimit(scope="quiz_upload", limit=UPLOAD_LIMIT, window_seconds=3600)
def quiz_upload(request):
    """Upload a file, parse it, and open the preview (never stores the file)."""
    form = QuizUploadForm(request.POST or None, request.FILES or None)
    parsed = None
    if request.method == "POST" and form.is_valid():
        try:
            parsed = parse_upload(request.FILES["file"])
        except UploadRejected as exc:
            form.add_error("file", str(exc))
        else:
            if not parsed.items:
                form.add_error(
                    None,
                    "No usable questions were found. Fix the problems below and "
                    "upload the file again.",
                )
            else:
                try:
                    quiz_set = create_draft_set(
                        request.user,
                        form.cleaned_data["name"],
                        sanitize_filename(form.cleaned_data["file"].name),
                        parsed.format,
                        parsed.items,
                    )
                except ValidationError as exc:
                    for message in exc.messages:
                        form.add_error(None, message)
                else:
                    request.session[SESSION_ERRORS] = parsed.errors[:200]
                    request.session[SESSION_WARNINGS] = parsed.warnings[:200]
                    request.session[SESSION_ENCODING] = parsed.encoding
                    return redirect("game:quiz_set_detail", quiz_set_id=quiz_set.pk)

    return render(
        request,
        "game/quiz_upload.html",
        {"form": form, "parsed": parsed},
    )


@login_required
@require_GET
def quiz_set_detail(request, quiz_set_id):
    """Preview a draft (errors, warnings, first items) or inspect an active set."""
    quiz_set = _set_or_404(request, quiz_set_id)
    questions = quiz_set.questions.order_by("item_number", "id")
    bands = list(quiz_set.bands.all())
    numbers = quiz_set_question_numbers(quiz_set)
    minimum = settings.GAME_SETTINGS["QUIZ_MIN_QUESTIONS_TO_ACTIVATE"]

    band_rows = band_summaries(quiz_set)
    by_difficulty = {row["difficulty"]: row for row in band_rows}
    editor = [
        {
            "key": key,
            "label": label,
            "start": by_difficulty.get(key, {}).get("start", ""),
            "end": by_difficulty.get(key, {}).get("end", ""),
            "count": by_difficulty.get(key, {}).get("count", 0),
        }
        for key, label in DIFFICULTIES
    ]
    if not bands:
        suggestions = {row["difficulty"]: row for row in suggested_bands(numbers)}
        for row in editor:
            suggestion = suggestions.get(row["key"], {})
            row["start"] = suggestion.get("start", "")
            row["end"] = suggestion.get("end", "")

    usable = sum(row["count"] for row in band_rows)
    return render(
        request,
        "game/quiz_detail.html",
        {
            "quiz_set": quiz_set,
            "questions": questions,
            "total": quiz_set.questions.count(),
            "active_total": quiz_set.questions.filter(active=True).count(),
            "usable": usable,
            "minimum": minimum,
            "editor": editor,
            "uncovered": uncovered_numbers(quiz_set),
            "warn_size": settings.GAME_SETTINGS["QUIZ_MIN_BAND_SIZE_WARN"],
            "item_numbers": numbers,
            "tanks": list(tanks_using(quiz_set)),
            "errors": request.session.pop(SESSION_ERRORS, []),
            "warnings": request.session.pop(SESSION_WARNINGS, []),
            "encoding": request.session.pop(SESSION_ENCODING, ""),
            # Drafts preview the first ten items; active sets list them all so
            # a bad item can be disabled without re-uploading.
            "display_items": (
                list(questions[:10]) if quiz_set.status == "draft" else list(questions)
            ),
            "can_activate": quiz_set.status == "draft" and usable >= minimum,
        },
    )


@login_required
@require_POST
@ratelimit(scope="quiz_confirm", limit=UPLOAD_LIMIT, window_seconds=3600)
def quiz_set_confirm(request, quiz_set_id):
    quiz_set = _set_or_404(request, quiz_set_id)
    try:
        activate_set(quiz_set)
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
    else:
        messages.success(request, "Quiz activated. Tanks can now use it.")
    return redirect("game:quiz_set_detail", quiz_set_id=quiz_set.pk)


@login_required
@require_POST
def quiz_set_bands(request, quiz_set_id):
    """Save the three difficulty bands and recompute question difficulties."""
    quiz_set = _set_or_404(request, quiz_set_id)
    rows = [
        (
            key,
            request.POST.get(f"{key}_start"),
            request.POST.get(f"{key}_end"),
        )
        for key, _label in DIFFICULTIES
    ]
    try:
        bands = parse_band_input(rows)
        save_bands(quiz_set, bands)
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
    else:
        messages.success(request, "Bands saved and item difficulties updated.")
    return redirect("game:quiz_set_detail", quiz_set_id=quiz_set.pk)


@login_required
@require_POST
def quiz_set_rename(request, quiz_set_id):
    quiz_set = _set_or_404(request, quiz_set_id)
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "Give the quiz a name.")
    elif len(name) > QuizSet._meta.get_field("name").max_length:
        messages.error(request, "That name is too long.")
    else:
        quiz_set.name = name
        quiz_set.save(update_fields=["name"])
        messages.success(request, "Quiz renamed.")
    return redirect("game:quiz_set_detail", quiz_set_id=quiz_set.pk)


@login_required
@require_POST
def quiz_question_toggle(request, quiz_set_id, question_id):
    quiz_set = _set_or_404(request, quiz_set_id)
    question = quiz_set.questions.filter(pk=question_id).first()
    if question is None:
        raise Http404("Question not found")
    question.active = not question.active
    question.save(update_fields=["active"])
    messages.success(
        request,
        "Question enabled." if question.active else "Question disabled.",
    )
    return redirect("game:quiz_set_detail", quiz_set_id=quiz_set.pk)


@login_required
@require_POST
def quiz_set_delete(request, quiz_set_id):
    quiz_set = _set_or_404(request, quiz_set_id)
    name = quiz_set.name
    reverted = delete_set(quiz_set)
    message = f"Quiz “{name}” deleted."
    if reverted:
        message += " These tanks are back on built-in questions: " + ", ".join(reverted)
    messages.success(request, message)
    return redirect("game:quiz_set_list")


@login_required
@require_GET
def quiz_template(request, fmt):
    """Download a ready-to-fill template in one of the four formats."""
    try:
        filename, content_type, data = build_template(fmt)
    except KeyError:
        raise Http404("Unknown template")
    response = FileResponse(
        io.BytesIO(data), as_attachment=True, filename=filename, content_type=content_type
    )
    return response
