"""Delete old quiz attempts (Phase 7).

Attempt rows are only needed for the daily cap, short-term duplicate avoidance
and debugging, so retention is a deployment choice: 90 days by default.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from game.models import QuestionAttempt


class Command(BaseCommand):
    help = "Delete quiz attempts older than N days (default 90)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Keep attempts newer than this many days (default 90).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many rows would be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1:
            raise CommandError("--days must be 1 or more.")

        cutoff = timezone.now() - timedelta(days=days)
        queryset = QuestionAttempt.objects.filter(issued_at__lt=cutoff)
        count = queryset.count()

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {count} attempt(s) older than {days} day(s) would be deleted."
                )
            )
            return

        queryset.delete()
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {count} attempt(s) older than {days} day(s).")
        )
