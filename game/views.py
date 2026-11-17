"""Views for Phase 2: accounts, tank list, create/join, tank stub.

Views stay thin: validate input with a form, call a service, redirect or
render. All authorization goes through ``services.get_membership`` - a tank id
from the client is never trusted on its own.
"""

import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import CreateTankForm, JoinTankForm, SignupForm
from .models import (
    DIFFICULTIES,
    QUIZ_DIFFICULTY_MODES,
    QUIZ_GRADE_MAX,
    QUIZ_SOURCES,
    SLOT_KEYS,
    SUBJECTS,
    EvolutionStage,
    Fish,
    FishReport,
    FishEquipment,
    FishSpecies,
    QuizSet,
    SpeciesStageName,
    Tank,
)
from .quiz.services import (
    answer_question,
    issue_question,
    quiz_state,
    remaining_today,
    update_quiz_settings,
)
from .quiz.bank import custom_pool_size
from .quiz.sets import update_tank_quiz_config
from .quiz.exceptions import (
    AttemptAlreadyAnswered,
    AttemptExpired,
    AttemptNotFound,
    DailyCapReached,
    IssueTooFast,
    NoQuestionsAvailable,
    QuizInvalid,
)
from .ratelimit import ratelimit
from .services import (
    AlreadyInTank,
    AlreadyReported,
    Banned,
    CannotRenameYet,
    FeedOnCooldown,
    InvalidJoinCode,
    InvalidSpecies,
    TankFull,
    get_profile,
    create_tank,
    delete_tank,
    feed,
    get_hunger,
    get_membership,
    join_tank,
    kick_player,
    leave_tank,
    regenerate_join_code,
    rename_fish,
    rename_own_fish,
    report_fish,
    seconds_until_can_feed,
    unban_player,
    xp_to_next_level,
)

MAX_LEVEL = settings.GAME_SETTINGS["MAX_LEVEL"]
logger = logging.getLogger(__name__)


def _species_options():
    """The species radio grid shown on create/join (active species only)."""
    return [
        {
            "key": species.key,
            "name": species.name,
            "description": species.description,
            "sprite_url": static(f"game/sprites/fish_{species.key}.png"),
        }
        for species in FishSpecies.objects.filter(active=True).order_by("order", "name")
    ]


def signup(request):
    """Create an account and sign the user in (Phase 0 gap)."""
    if request.user.is_authenticated:
        return redirect("game:tank_list")

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Account created. Welcome aboard!")
        return redirect("game:tank_list")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def tank_list(request):
    """List every tank the user is a member of, with their fish and fill level."""
    memberships = (
        Fish.objects.filter(owner=request.user)
        .select_related("tank")
        .order_by("-tank__created_at")
    )
    rows = [
        {
            "tank": membership.tank,
            "fish": membership,
            "member_count": membership.tank.fish.count(),
        }
        for membership in memberships
    ]
    return render(request, "game/tank_list.html", {"rows": rows})


@login_required
def tank_create(request):
    """Create a tank plus the owner's fish (PRG on success)."""
    form = CreateTankForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tank, _fish = create_tank(
            request.user,
            form.cleaned_data["tank_name"],
            form.cleaned_data["fish_name"],
            form.cleaned_data["species"],
        )
        messages.success(
            request,
            f"Tank “{tank.name}” created. Share the code {tank.join_code} to invite players.",
        )
        return redirect("game:tank_detail", tank_id=tank.pk)
    return render(
        request,
        "game/tank_form.html",
        {
            "form": form,
            "form_title": "Create a tank",
            "submit_label": "Create tank",
            "show_code_hint": True,
            "species_options": _species_options(),
        },
    )


@login_required
@ratelimit(
    scope="join",
    limit=settings.GAME_SETTINGS["JOIN_RATE_LIMIT_ATTEMPTS"],
    window_seconds=settings.GAME_SETTINGS["JOIN_RATE_LIMIT_WINDOW_SECONDS"],
)
def tank_join(request):
    """Join a tank by code (PRG on success), rate limited per user."""
    form = JoinTankForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            tank, _fish = join_tank(
                request.user,
                form.cleaned_data["code"],
                form.cleaned_data["fish_name"],
                form.cleaned_data["species"],
            )
        except (InvalidJoinCode, Banned, InvalidSpecies):
            # Deliberately generic: a failed join must not reveal whether the
            # code exists, or that the user is banned from it.
            form.add_error(None, "That join code doesn't match a tank.")
        except TankFull:
            form.add_error(None, "That tank is full. Ask the owner to make room.")
        except AlreadyInTank:
            form.add_error(None, "You already have a fish in that tank.")
        else:
            messages.success(request, f"You joined “{tank.name}”.")
            return redirect("game:tank_detail", tank_id=tank.pk)
    return render(
        request,
        "game/tank_form.html",
        {
            "form": form,
            "form_title": "Join a tank",
            "submit_label": "Join tank",
            "show_code_hint": False,
            "species_options": _species_options(),
        },
    )


@login_required
def tank_detail(request, tank_id):
    """Tank page stub: membership required, else 404 (existence is not revealed)."""
    membership = get_membership(request.user, tank_id)
    if membership is None:
        raise Http404("Tank not found")

    tank = membership.tank
    fish_list = tank.fish.select_related("owner").order_by("name")
    return render(
        request,
        "game/tank_detail.html",
        {
            "tank": tank,
            "my_fish": membership,
            "fish_list": fish_list,
            "is_owner": tank.owner_id == request.user.pk,
        },
    )


def _iso_z(moment):
    """Format an aware datetime as an ISO-8601 string ending in ``Z``."""
    return moment.isoformat().replace("+00:00", "Z")


def _fish_metadata(fish_ids):
    """Stage names and equipped keys for *fish_ids*, in two fixed queries."""
    fish_qs = Fish.objects.filter(pk__in=list(fish_ids))
    species_ids = set(fish_qs.values_list("species_id", flat=True))
    stage_names = {
        (species_id, stage_number): name
        for species_id, stage_number, name in SpeciesStageName.objects.filter(
            species_id__in=species_ids
        ).values_list("species_id", "stage_number", "name")
    }
    equipment: dict[int, dict[str, str]] = {}
    for fish_id, slot, key in FishEquipment.objects.filter(
        fish_id__in=list(fish_ids)
    ).values_list("fish_id", "slot", "accessory__key"):
        equipment.setdefault(fish_id, {})[slot] = key
    return stage_names, equipment


def _serialize_fish(fish, now, stage_names=None, equipment=None):
    """One fish entry for the state/feed endpoints."""
    if stage_names is None or equipment is None:
        stage_names, equipment = _fish_metadata([fish.pk])
    stage_name = stage_names.get((fish.species_id, fish.stage), "")
    cooldown_remaining = seconds_until_can_feed(fish, now=now)
    xp_needed = 0 if fish.level >= MAX_LEVEL else xp_to_next_level(fish.level)
    worn = equipment.get(fish.pk, {})
    return {
        "id": fish.pk,
        "name": fish.name,
        "owner": fish.owner.username,
        "species": fish.species.key,
        "level": fish.level,
        "stage": fish.stage,
        "stage_name": stage_name,
        "xp": fish.xp,
        "xp_needed": xp_needed,
        "hunger": get_hunger(fish, now=now),
        "can_feed": cooldown_remaining == 0,
        "cooldown_remaining": cooldown_remaining,
        "equipped": {slot: worn.get(slot) for slot in SLOT_KEYS},
    }


def _json_no_store(payload, status=200):
    """JSON response that browsers and proxies must not cache."""
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def tank_state(request, tank_id):
    """Return the live state of one tank (members only, 404 otherwise)."""
    membership = get_membership(request.user, tank_id)
    if membership is None:
        raise Http404("Tank not found")

    tank = membership.tank
    now = timezone.now()
    # select_related keeps this independent of the fish count; stage names and
    # equipment are two more fixed queries, whatever the fish count.
    fish_qs = list(tank.fish.select_related("owner", "species").order_by("id"))
    stage_names, equipment = _fish_metadata([fish.pk for fish in fish_qs])

    return _json_no_store(
        {
            "tank": {"id": tank.pk, "name": tank.name, "capacity": tank.capacity},
            "me": {"fish_id": membership.pk},
            "server_time": _iso_z(now),
            "fish": [
                _serialize_fish(fish, now, stage_names, equipment)
                for fish in fish_qs
            ],
            "quiz": quiz_state(tank, membership, now=now),
        }
    )


@login_required
@require_POST
def tank_feed(request, tank_id):
    """Feed the requesting user's own fish; the fish id is never taken from input."""
    membership = get_membership(request.user, tank_id)
    if membership is None:
        raise Http404("Tank not found")

    # Phase 7: when feeding must be earned with a quiz, the timed endpoint is
    # closed off so XP cannot be gained without a correct answer.
    if (
        settings.GAME_SETTINGS["QUIZ_ENABLED"]
        and settings.GAME_SETTINGS["QUIZ_ONLY_FEEDING"]
    ):
        return _json_no_store({"error": "quiz_required"}, status=409)

    try:
        result = feed(membership)
    except FeedOnCooldown as exc:
        return _json_no_store(
            {"error": "cooldown", "seconds_remaining": exc.seconds_remaining},
            status=429,
        )

    now = timezone.now()
    return _json_no_store(
        {
            "server_time": _iso_z(now),
            "xp_gained": result.xp_gained,
            "leveled_up": result.leveled_up,
            "levels_gained": result.levels_gained,
            "evolved": result.evolved,
            "old_stage": result.old_stage,
            "new_stage": result.new_stage,
            "pearls_gained": result.pearls_gained,
            "gifts": [
                {"key": gift.key, "name": gift.name, "slot": gift.slot}
                for gift in result.gifts
            ],
            "fish": _serialize_fish(result.fish, now),
        }
    )


# ---------------------------------------------------------------- owner tools


def _membership_or_404(request, tank_id):
    """Shared membership gate: non-members are told nothing (404)."""
    membership = get_membership(request.user, tank_id)
    if membership is None:
        raise Http404("Tank not found")
    return membership


def _fish_in_tank_or_404(membership, fish_id):
    fish = Fish.objects.filter(pk=fish_id, tank=membership.tank).first()
    if fish is None:
        raise Http404("Fish not found")
    return fish


def _owner_tank_or_403(request, membership):
    if membership.tank.owner_id != request.user.pk:
        raise PermissionDenied("Only the tank owner can do that.")
    return membership.tank


@login_required
@require_GET
def tank_settings(request, tank_id):
    """Owner control panel: code, members, bans and the danger zone."""
    membership = _membership_or_404(request, tank_id)
    tank = _owner_tank_or_403(request, membership)
    return render(
        request,
        "game/tank_settings.html",
        {
            "tank": tank,
            "fish_list": tank.fish.select_related("owner").order_by("name"),
            "bans": tank.bans.select_related("user", "banned_by"),
            "quiz_grades": range(1, QUIZ_GRADE_MAX + 1),
            "quiz_subjects": SUBJECTS,
            "quiz_sources": QUIZ_SOURCES,
            "quiz_modes": QUIZ_DIFFICULTY_MODES,
            "difficulties": DIFFICULTIES,
            "active_sets": QuizSet.objects.filter(
                owner=request.user, status="active"
            ).order_by("name"),
            "quiz_pool_warning": (
                tank.quiz_source == "custom" and custom_pool_size(tank, membership) == 0
            ),
        },
    )


@login_required
@require_POST
def tank_regenerate_code(request, tank_id):
    membership = _membership_or_404(request, tank_id)
    tank = _owner_tank_or_403(request, membership)
    regenerate_join_code(tank, request.user)
    messages.success(request, "New join code issued. The old code no longer works.")
    return redirect("game:tank_settings", tank_id=tank.pk)


@login_required
@require_POST
def tank_kick(request, tank_id, fish_id):
    membership = _membership_or_404(request, tank_id)
    tank = _owner_tank_or_403(request, membership)
    fish = _fish_in_tank_or_404(membership, fish_id)
    kick_player(tank, request.user, fish.pk)
    messages.success(request, f"Kicked {fish.owner.username} and banned them from this tank.")
    return redirect("game:tank_settings", tank_id=tank.pk)


@login_required
@require_POST
def tank_unban(request, tank_id, user_id):
    membership = _membership_or_404(request, tank_id)
    tank = _owner_tank_or_403(request, membership)
    unban_player(tank, request.user, user_id)
    messages.success(request, "Player unbanned; they can rejoin with the join code.")
    return redirect("game:tank_settings", tank_id=tank.pk)


@login_required
@require_POST
def tank_rename_fish(request, tank_id, fish_id):
    membership = _membership_or_404(request, tank_id)
    tank = _owner_tank_or_403(request, membership)
    fish = _fish_in_tank_or_404(membership, fish_id)
    try:
        rename_fish(tank, request.user, fish.pk, request.POST.get("name", ""))
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
    else:
        messages.success(request, "Fish renamed.")
    return redirect("game:tank_settings", tank_id=tank.pk)


@login_required
@require_POST
def tank_delete(request, tank_id):
    membership = _membership_or_404(request, tank_id)
    tank = _owner_tank_or_403(request, membership)
    try:
        delete_tank(tank, request.user, request.POST.get("confirm_name", ""))
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
        return redirect("game:tank_settings", tank_id=tank.pk)
    messages.success(request, "Tank deleted.")
    return redirect("game:tank_list")


@login_required
@require_POST
def tank_leave(request, tank_id):
    membership = _membership_or_404(request, tank_id)
    leave_tank(request.user, membership.tank)
    messages.success(request, "You left the tank.")
    return redirect("game:tank_list")


@login_required
@require_POST
@ratelimit(
    scope="rename",
    limit=settings.GAME_SETTINGS["RENAME_RATE_LIMIT_ATTEMPTS"],
    window_seconds=settings.GAME_SETTINGS["RENAME_RATE_LIMIT_WINDOW_SECONDS"],
)
def tank_rename_me(request, tank_id):
    membership = _membership_or_404(request, tank_id)
    try:
        rename_own_fish(request.user, membership.tank, request.POST.get("name", ""))
    except CannotRenameYet as exc:
        messages.error(request, "You can rename your fish once per day.")
        logger.info("Rename cooldown hit by %s: %s seconds", request.user.pk, exc.seconds_remaining)
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
    else:
        messages.success(request, "Your fish has a new name.")
    return redirect("game:tank_detail", tank_id=membership.tank.pk)


def _json_body(request):
    """Parse a JSON body, falling back to the form body (never raising)."""
    if request.content_type and "json" in request.content_type:
        try:
            payload = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return request.POST


def _wants_json(request) -> bool:
    """True for fetch/XHR callers, False for a plain HTML form post."""
    if request.content_type and "json" in request.content_type:
        return True
    return "application/json" in (request.headers.get("Accept") or "")


@login_required
@require_POST
@ratelimit(
    scope="quiz_next",
    limit=settings.GAME_SETTINGS["QUIZ_NEXT_RATE_LIMIT_ATTEMPTS"],
    window_seconds=settings.GAME_SETTINGS["QUIZ_NEXT_RATE_LIMIT_WINDOW_SECONDS"],
)
def tank_quiz_next(request, tank_id):
    """Issue or re-return the user's open question (never reveals the answer)."""
    membership = _membership_or_404(request, tank_id)
    now = timezone.now()
    try:
        attempt = issue_question(request.user, membership.tank, now=now)
    except DailyCapReached as exc:
        return _json_no_store(
            {"error": "daily_cap", "seconds_until_reset": exc.seconds_until_reset},
            status=429,
        )
    except IssueTooFast as exc:
        return _json_no_store(
            {"error": "too_fast", "retry_after": exc.retry_after}, status=429
        )
    except NoQuestionsAvailable:
        return _json_no_store({"error": "no_questions"}, status=503)

    ttl = settings.GAME_SETTINGS["QUIZ_ATTEMPT_TTL_SECONDS"]
    expires_in = max(0, int((attempt.issued_at.timestamp() + ttl) - now.timestamp()))
    return _json_no_store(
        {
            "attempt_id": attempt.pk,
            "subject": attempt.subject,
            "grade": attempt.grade,
            "prompt": attempt.prompt,
            "choices": attempt.choices,
            "difficulty": attempt.difficulty,
            "expires_in": expires_in,
            "remaining_today": remaining_today(membership, now=now),
            "cap": settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"],
        }
    )


@login_required
@require_POST
@ratelimit(
    scope="quiz_answer",
    limit=settings.GAME_SETTINGS["QUIZ_ANSWER_RATE_LIMIT_ATTEMPTS"],
    window_seconds=settings.GAME_SETTINGS["QUIZ_ANSWER_RATE_LIMIT_WINDOW_SECONDS"],
)
def tank_quiz_answer(request, tank_id):
    """Close an attempt; a correct answer feeds the fish exactly once."""
    _membership_or_404(request, tank_id)
    data = _json_body(request)
    attempt_id = data.get("attempt_id")
    selected_index = data.get("selected_index")

    if isinstance(attempt_id, bool) or not isinstance(attempt_id, int):
        return _json_no_store({"error": "invalid"}, status=400)

    now = timezone.now()
    try:
        result = answer_question(
            request.user, attempt_id, selected_index, now=now
        )
    except AttemptNotFound:
        raise Http404("Question not found")
    except AttemptAlreadyAnswered:
        return _json_no_store({"error": "already_answered"}, status=409)
    except AttemptExpired:
        return _json_no_store({"error": "expired"}, status=410)
    except QuizInvalid:
        return _json_no_store({"error": "invalid"}, status=400)
    except DailyCapReached as exc:
        return _json_no_store(
            {"error": "daily_cap", "seconds_until_reset": exc.seconds_until_reset},
            status=429,
        )

    # No correct answer, and no explanation on a wrong attempt: a player must
    # not be able to learn the key by answering wrong on purpose.
    payload = {
        "correct": result.correct,
        "explanation": result.explanation,
        "remaining_today": result.remaining_today,
        "cap": settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"],
        "server_time": _iso_z(now),
        "feed": None,
    }
    if result.feed is not None:
        payload["feed"] = {
            "xp_gained": result.feed.xp_gained,
            "leveled_up": result.feed.leveled_up,
            "levels_gained": result.feed.levels_gained,
            "evolved": result.feed.evolved,
            "old_stage": result.feed.old_stage,
            "new_stage": result.feed.new_stage,
            "pearls_gained": result.feed.pearls_gained,
            "gifts": [
                {"key": gift.key, "name": gift.name, "slot": gift.slot}
                for gift in result.feed.gifts
            ],
            "fish": _serialize_fish(result.feed.fish, now),
        }
    return _json_no_store(payload)


@login_required
@require_POST
def tank_quiz_settings(request, tank_id):
    """Owner-only: set the tank's quiz grade, subjects and source."""
    membership = _membership_or_404(request, tank_id)
    tank = _owner_tank_or_403(request, membership)
    data = _json_body(request)
    grade = data.get("grade")
    subjects = data.getlist("subjects") if hasattr(data, "getlist") else data.get("subjects")

    config_keys = ("source", "quiz_set", "difficulty_mode", "fixed_difficulty")
    has_config = any(key in data for key in config_keys)
    has_basic = "grade" in data or "subjects" in data

    try:
        with transaction.atomic():
            if has_config:
                update_tank_quiz_config(
                    tank,
                    request.user,
                    source=data.get("source") if "source" in data else None,
                    quiz_set_id=(
                        data.get("quiz_set") if "quiz_set" in data else None
                    ),
                    difficulty_mode=(
                        data.get("difficulty_mode")
                        if "difficulty_mode" in data
                        else None
                    ),
                    fixed_difficulty=(
                        data.get("fixed_difficulty")
                        if "fixed_difficulty" in data
                        else None
                    ),
                )
            if has_basic or not has_config:
                update_quiz_settings(tank, request.user, grade, subjects)
    except ValidationError as exc:
        if _wants_json(request):
            return _json_no_store(
                {"error": "invalid", "messages": exc.messages}, status=400
            )
        for message in exc.messages:
            messages.error(request, message)
        return redirect("game:tank_settings", tank_id=tank.pk)

    if _wants_json(request):
        payload = {
            "grade": tank.quiz_grade,
            "subjects": list(tank.quiz_subjects),
        }
        if has_config:
            payload.update(
                {
                    "source": tank.quiz_source,
                    "quiz_set_id": tank.quiz_set_id,
                    "difficulty_mode": tank.quiz_difficulty_mode,
                    "fixed_difficulty": tank.quiz_fixed_difficulty,
                }
            )
        return _json_no_store(payload, status=200)
    messages.success(request, "Quiz settings saved. New questions use them.")
    return redirect("game:tank_settings", tank_id=tank.pk)


@login_required
@require_POST
@ratelimit(
    scope="report",
    limit=settings.GAME_SETTINGS["REPORT_RATE_LIMIT_ATTEMPTS"],
    window_seconds=settings.GAME_SETTINGS["REPORT_RATE_LIMIT_WINDOW_SECONDS"],
)
def tank_report(request, tank_id, fish_id):
    membership = _membership_or_404(request, tank_id)
    fish = _fish_in_tank_or_404(membership, fish_id)
    reason = request.POST.get("reason", FishReport.REASON_NAME)
    note = request.POST.get("note", "")
    try:
        report_fish(fish, request.user, reason=reason, note=note)
    except PermissionDenied:
        messages.error(request, "You can't report your own fish.")
    except AlreadyReported:
        messages.error(request, "You already reported that fish.")
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
    else:
        messages.success(request, "Thanks — a moderator will take a look.")
    return redirect("game:tank_detail", tank_id=membership.tank.pk)
