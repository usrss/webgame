"""Staff-only art debugging (Phase 9)."""

import json

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from .models import FishSpecies


@staff_member_required
def art_debug(request):
    """Render every species x stage x accessory combination for inspection."""
    species = []
    for row in FishSpecies.objects.prefetch_related("stage_names").order_by("order"):
        names = [
            stage.name
            for stage in sorted(row.stage_names.all(), key=lambda stage: stage.stage_number)
        ]
        species.append({"key": row.key, "name": row.name, "stages": names})
    return render(
        request,
        "game/art_debug.html",
        {"species_json": json.dumps(species)},
    )
