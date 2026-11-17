"""Delete abandoned quiz drafts (Phase 8).

A draft is a set created by an upload that was never confirmed.  They are
useless after ``QUIZ_DRAFT_TTL_HOURS`` (default 24), so schedule this command
daily, e.g.::

    python manage.py purge_draft_quizzes

Windows Task Scheduler / cron both work; the command is idempotent.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from game.quiz.sets import purge_expired_drafts


class Command(BaseCommand):
    help = "Delete quiz drafts older than QUIZ_DRAFT_TTL_HOURS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without deleting anything.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            from datetime import timedelta

            from django.conf import settings

            from game.models import QuizSet

            hours = settings.GAME_SETTINGS["QUIZ_DRAFT_TTL_HOURS"]
            cutoff = timezone.now() - timedelta(hours=hours)
            count = QuizSet.objects.filter(
                status="draft", created_at__lt=cutoff
            ).count()
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {count} draft(s) older than {hours}h would be deleted."
                )
            )
            return

        count = purge_expired_drafts()
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {count} expired quiz draft(s).")
        )
