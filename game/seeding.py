"""Idempotent seeding of species and accessories (Phase 9).

``game/data/species.json`` and ``game/data/accessories.json`` are the single
source of truth.  Seeding never deletes anything and never resets a player's
inventory or an admin's ``active`` toggle.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import CommandError

from .models import (
    RARITY_KEYS,
    SLOT_KEYS,
    UNLOCK_KEYS,
    Accessory,
    FishSpecies,
    SpeciesStageName,
)
from .validators import validate_display_name

DATA_DIR = Path(__file__).resolve().parent / "data"
SPECIES_PATH = DATA_DIR / "species.json"
ACCESSORIES_PATH = DATA_DIR / "accessories.json"
STAGE_COUNT = 6


def _read(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CommandError(f"Could not read {path.name}: {exc}")
    if not isinstance(data, list):
        raise CommandError(f"{path.name} must contain a list.")
    return data


def _name(value, max_length: int, label: str) -> str:
    try:
        return validate_display_name(value, max_length=max_length, field_label=label)
    except ValidationError as exc:
        raise CommandError(f"{label} {value!r}: {exc.messages[0]}")


def seed_species() -> dict:
    created = updated = 0
    entries = _read(SPECIES_PATH)
    for entry in entries:
        key = (entry.get("key") or "").strip()
        if not key:
            raise CommandError("A species entry is missing its key.")
        name = _name(entry.get("name"), 30, "Species name")
        description = (entry.get("description") or "").strip()
        if not description or len(description) > 120:
            raise CommandError(f"Species {key}: description must be 1-120 characters.")
        stage_names = entry.get("stage_names") or []
        if len(stage_names) != STAGE_COUNT:
            raise CommandError(f"Species {key}: exactly {STAGE_COUNT} stage names are required.")
        cleaned_stages = [_name(value, 14, "Stage name") for value in stage_names]
        if len(set(value.casefold() for value in cleaned_stages)) != STAGE_COUNT:
            raise CommandError(f"Species {key}: stage names must be unique.")

        species, was_created = FishSpecies.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "description": description,
                "order": int(entry.get("order") or 0),
            },
        )
        created += int(was_created)
        updated += int(not was_created)
        for stage_number, stage_name in enumerate(cleaned_stages):
            SpeciesStageName.objects.update_or_create(
                species=species,
                stage_number=stage_number,
                defaults={"name": stage_name},
            )
    return {"created": created, "updated": updated, "total": FishSpecies.objects.count()}


def seed_accessories() -> dict:
    created = updated = 0
    entries = _read(ACCESSORIES_PATH)
    for entry in entries:
        key = (entry.get("key") or "").strip()
        if not key:
            raise CommandError("An accessory entry is missing its key.")
        name = _name(entry.get("name"), 30, "Accessory name")
        slot = entry.get("slot")
        rarity = entry.get("rarity")
        unlock_type = entry.get("unlock_type")
        if slot not in SLOT_KEYS:
            raise CommandError(f"Accessory {key}: unknown slot {slot!r}.")
        if rarity not in RARITY_KEYS:
            raise CommandError(f"Accessory {key}: unknown rarity {rarity!r}.")
        if unlock_type not in UNLOCK_KEYS:
            raise CommandError(f"Accessory {key}: unknown unlock type {unlock_type!r}.")
        price = int(entry.get("price") or 0)
        unlock_stage = entry.get("unlock_stage")
        if unlock_type == "shop":
            if price < 1:
                raise CommandError(f"Accessory {key}: shop items need a price.")
            if unlock_stage is not None:
                raise CommandError(f"Accessory {key}: shop items have no unlock stage.")
        elif price != 0:
            raise CommandError(f"Accessory {key}: only shop items may cost pearls.")
        if unlock_type == "evolution":
            if unlock_stage not in range(1, STAGE_COUNT):
                raise CommandError(f"Accessory {key}: unlock_stage must be 1-5.")
        elif unlock_stage is not None:
            raise CommandError(f"Accessory {key}: only evolution gifts have a stage.")

        _accessory, was_created = Accessory.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "slot": slot,
                "rarity": rarity,
                "unlock_type": unlock_type,
                "price": price,
                "unlock_stage": unlock_stage,
            },
        )
        created += int(was_created)
        updated += int(not was_created)
    return {"created": created, "updated": updated, "total": Accessory.objects.count()}


def seed_content() -> dict:
    """Seed both data files; safe to run any number of times."""
    return {"species": seed_species(), "accessories": seed_accessories()}


__all__ = ["seed_accessories", "seed_content", "seed_species"]
