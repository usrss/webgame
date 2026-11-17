"""Seed the 15 species and 24 accessories (Phase 9).

Idempotent: running it again changes nothing and never deletes player
inventory.  It also runs automatically after ``migrate`` via a post_migrate
handler, so a fresh database is playable without an extra command.

    python manage.py seed_game_content
"""

from django.core.management.base import BaseCommand

from game.seeding import seed_content


class Command(BaseCommand):
    help = "Load species and accessories from game/data/*.json (idempotent)."

    def handle(self, *args, **options):
        summary = seed_content()
        species = summary["species"]
        accessories = summary["accessories"]
        self.stdout.write(
            self.style.SUCCESS(
                f"Species: {species['total']} total "
                f"({species['created']} created, {species['updated']} updated)."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Accessories: {accessories['total']} total "
                f"({accessories['created']} created, {accessories['updated']} updated)."
            )
        )
