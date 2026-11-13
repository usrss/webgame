# Data migration: seeds the four canonical EvolutionStage rows.
#
# It is idempotent (update_or_create) and reversible (deletes the rows).

from django.db import migrations

# stage_number, name, min_level, sprite_key
#
# ``sprite_key`` is the key the Phase 4 client maps to (sprite sheet, row). The
# v1 species is "goldie" (static/game/sprites/fish_goldie.png), whose rows are
# the evolution stages: row 0 = Fry ... row 3 = Elder. Keys are therefore
# species-scoped, so adding a species later is a matter of seeding new rows
# rather than changing existing ones.
STAGES = [
    (0, "Fry", 1, "goldie_fry"),
    (1, "Juvenile", 5, "goldie_juvenile"),
    (2, "Adult", 15, "goldie_adult"),
    (3, "Elder", 30, "goldie_elder"),
]


def seed_evolutionstages(apps, schema_editor):
    EvolutionStage = apps.get_model("game", "EvolutionStage")
    for stage_number, name, min_level, sprite_key in STAGES:
        EvolutionStage.objects.update_or_create(
            stage_number=stage_number,
            defaults={"name": name, "min_level": min_level, "sprite_key": sprite_key},
        )


def reverse_seed_evolutionstages(apps, schema_editor):
    EvolutionStage = apps.get_model("game", "EvolutionStage")
    EvolutionStage.objects.filter(stage_number__in=[s[0] for s in STAGES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_evolutionstages, reverse_code=reverse_seed_evolutionstages),
    ]
