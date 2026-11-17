"""Wardrobe endpoints (Phase 9).

Pearls and equipment are server-owned: the client never sends a price, a
stage, or an ownership claim.  Every balance change is audit-logged in
``PearlTransaction``.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import SLOT_KEYS, Accessory, FishEquipment, SpeciesStageName
from .ratelimit import ratelimit
from .services import (
    AccessoryNotFound,
    AlreadyOwned,
    InvalidSlot,
    NotEnoughPearls,
    NotForSale,
    NotOwned,
    buy_accessory,
    equip,
    get_membership,
    get_profile,
)
from .views import _json_no_store, _iso_z

LIMIT = settings.GAME_SETTINGS["WARDROBE_RATE_LIMIT_ATTEMPTS"]
WINDOW = settings.GAME_SETTINGS["WARDROBE_RATE_LIMIT_WINDOW_SECONDS"]


def _body(request):
    if request.content_type and "json" in request.content_type:
        try:
            data = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST


def _equipped(fish_id: int) -> dict:
    worn = {
        slot: key
        for slot, key in FishEquipment.objects.filter(fish_id=fish_id).values_list(
            "slot", "accessory__key"
        )
    }
    return {slot: worn.get(slot) for slot in SLOT_KEYS}


def _catalog(user, stage: int, pearls: int) -> list[dict]:
    owned_ids = set(user.accessories.values_list("accessory_id", flat=True))
    rows = []
    for item in Accessory.objects.filter(active=True):
        owned = item.pk in owned_ids
        if owned:
            reason = None
        elif item.unlock_type == "evolution" and item.unlock_stage is not None:
            reason = (
                "reach_stage"
                if stage < item.unlock_stage
                else "evolution_gift_pending"
            )
        elif item.unlock_type == "shop":
            reason = "not_enough_pearls" if pearls < item.price else "for_sale"
        else:
            reason = "locked"
        rows.append(
            {
                "key": item.key,
                "name": item.name,
                "slot": item.slot,
                "rarity": item.rarity,
                "price": item.price,
                "unlock_type": item.unlock_type,
                "unlock_stage": item.unlock_stage,
                "owned": owned,
                "locked_reason": reason,
            }
        )
    return rows


@login_required
@require_GET
def wardrobe_state(request, tank_id):
    """For my fish only: pearls, current look and the full item catalog."""
    membership = get_membership(request.user, tank_id)
    if membership is None:
        raise Http404("Tank not found")

    profile = get_profile(request.user)
    stage_name = (
        SpeciesStageName.objects.filter(
            species_id=membership.species_id, stage_number=membership.stage
        )
        .values_list("name", flat=True)
        .first()
        or ""
    )
    return _json_no_store(
        {
            "pearls": profile.pearls,
            "species": membership.species.key,
            "species_name": membership.species.name,
            "stage": membership.stage,
            "stage_name": stage_name,
            "stage_names": list(
                SpeciesStageName.objects.filter(species_id=membership.species_id)
                .order_by("stage_number")
                .values_list("name", flat=True)
            ),
            "equipped": _equipped(membership.pk),
            "catalog": _catalog(request.user, membership.stage, profile.pearls),
            "server_time": _iso_z(timezone.now()),
        }
    )


@login_required
@require_POST
@ratelimit(scope="wardrobe_equip", limit=LIMIT, window_seconds=WINDOW)
def wardrobe_equip(request, tank_id):
    membership = get_membership(request.user, tank_id)
    if membership is None:
        raise Http404("Tank not found")

    data = _body(request)
    slot = data.get("slot")
    key = data.get("accessory_key")
    try:
        equip(request.user, membership, slot, key)
    except PermissionDenied:
        return _json_no_store({"error": "forbidden"}, status=403)
    except InvalidSlot as exc:
        return _json_no_store({"error": "invalid_slot", "message": str(exc)}, status=400)
    except AccessoryNotFound:
        return _json_no_store({"error": "not_found"}, status=400)
    except NotOwned:
        return _json_no_store({"error": "not_owned"}, status=400)

    return _json_no_store(
        {"equipped": _equipped(membership.pk), "slot": slot}, status=200
    )


@login_required
@require_POST
@ratelimit(scope="wardrobe_buy", limit=LIMIT, window_seconds=WINDOW)
def wardrobe_buy(request):
    data = _body(request)
    key = data.get("accessory_key")
    try:
        owned = buy_accessory(request.user, key)
    except NotForSale:
        return _json_no_store({"error": "not_for_sale"}, status=400)
    except AlreadyOwned:
        return _json_no_store({"error": "already_owned"}, status=409)
    except NotEnoughPearls as exc:
        return _json_no_store(
            {"error": "not_enough_pearls", "missing": exc.missing}, status=400
        )

    profile = get_profile(request.user)
    return _json_no_store(
        {"owned": owned.accessory.key, "pearls": profile.pearls}, status=200
    )


__all__ = ["wardrobe_buy", "wardrobe_equip", "wardrobe_state"]
