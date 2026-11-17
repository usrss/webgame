"""Report on quiz balance (Phase 7).

Answers "is the bank big enough and is the daily cap sensible?" from real data.
Read-only: safe to run on production at any time.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from game.models import (
    QUIZ_GRADE_MAX,
    QUIZ_GRADE_MIN,
    SUBJECT_KEYS,
    Question,
    QuestionAttempt,
    Tank,
)

RECOMMENDED_PER_SUBJECT = 3


class Command(BaseCommand):
    help = "Report question-bank coverage, accuracy and daily feed totals."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Window for attempt statistics (default 7).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1:
            raise CommandError("--days must be 1 or more.")

        config = settings.GAME_SETTINGS
        now = timezone.now()
        window_start = now - timedelta(days=days)

        self._bank()
        self._tanks()
        self._attempts(window_start, days)
        self._settings(config)
        self._evolution_curve(config)
        self._warnings()

    # -------------------------------------------------------------------- parts

    def _bank(self) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Question bank (active)"))
        counts = Counter(
            Question.objects.filter(active=True).values_list("subject", "grade")
        )
        for grade in range(QUIZ_GRADE_MIN, QUIZ_GRADE_MAX + 1):
            parts = []
            for subject in SUBJECT_KEYS:
                count = counts.get((subject, grade), 0)
                if subject == "math":
                    parts.append(f"math generated ({count} extra)")
                else:
                    parts.append(f"{subject} {count}")
            self.stdout.write(f"  grade {grade}: " + ", ".join(parts))
        total = sum(counts.values())
        self.stdout.write(f"  total active bank questions: {total}")

    def _tanks(self) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Tanks"))
        tanks = list(Tank.objects.values_list("quiz_grade", "quiz_subjects"))
        if not tanks:
            self.stdout.write("  no tanks yet")
            return
        grades = Counter(grade for grade, _ in tanks)
        subjects = Counter()
        for _, chosen in tanks:
            for key in chosen or []:
                subjects[key] += 1
        self.stdout.write(
            f"  {len(tanks)} tank(s); grades: "
            + ", ".join(f"{grade}: {count}" for grade, count in sorted(grades.items()))
        )
        self.stdout.write(
            "  subjects: " + ", ".join(f"{key}: {subjects[key]}" for key in SUBJECT_KEYS)
        )

    def _attempts(self, window_start, days: int) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"Attempts (last {days} day(s))"))

        attempts = QuestionAttempt.objects.filter(issued_at__gte=window_start)
        issued = attempts.count()
        answered = attempts.filter(answered_at__isnull=False).count()
        correct = attempts.filter(correct=True).count()

        if issued:
            self.stdout.write(
                f"  issued: {issued}, answered: {answered} "
                f"({answered / issued:.0%}), correct: {correct} "
                f"({correct / max(1, answered):.0%} of answered)"
            )
        else:
            self.stdout.write("  no attempts in this window")

        per_day: dict[tuple[int, object], int] = defaultdict(int)
        for fish_id, answered_at in attempts.filter(correct=True).values_list(
            "fish_id", "answered_at"
        ):
            if answered_at is not None:
                per_day[(fish_id, timezone.localtime(answered_at).date())] += 1

        cap = settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"]
        if per_day:
            totals = sorted(per_day.values(), reverse=True)
            at_cap = sum(1 for value in totals if value >= cap)
            self.stdout.write(
                f"  feeds per fish per active day: max {totals[0]}, "
                f"median {totals[len(totals) // 2]}, "
                f"{at_cap} fish-day(s) at the cap of {cap}"
            )
        else:
            self.stdout.write("  no feeds earned in this window")

        ttl = settings.GAME_SETTINGS["QUIZ_ATTEMPT_TTL_SECONDS"]
        unanswered_open = QuestionAttempt.objects.filter(
            answered_at__isnull=True,
            issued_at__gte=timezone.now() - timedelta(seconds=ttl),
        ).count()
        self.stdout.write(f"  open (unexpired) attempts right now: {unanswered_open}")

    def _settings(self, config) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Quiz settings"))
        for key in (
            "QUIZ_ENABLED",
            "QUIZ_ONLY_FEEDING",
            "QUIZ_DAILY_CORRECT_CAP",
            "QUIZ_ATTEMPT_TTL_SECONDS",
            "QUIZ_MIN_SECONDS_BETWEEN_ISSUES",
            "QUIZ_RECENT_EXCLUDE",
            "QUIZ_CHOICES",
            "QUIZ_DEFAULT_GRADE",
            "QUIZ_DEFAULT_SUBJECTS",
        ):
            self.stdout.write(f"  {key} = {config[key]}")

    def _evolution_curve(self, config) -> None:
        """Days to each evolution at the Phase 7 daily XP cap, per XP step."""
        self.stdout.write(self.style.MIGRATE_HEADING("Evolution pace"))
        levels = list(config["EVOLUTION_LEVELS"])[1:]
        cap = int(config["QUIZ_DAILY_CORRECT_CAP"]) * int(config["XP_PER_FEED"])
        steps = [int(config["XP_PER_LEVEL_STEP"]), 10, 20, 50]
        steps = list(dict.fromkeys(steps))  # keep order, drop duplicates

        header = "  step | " + " | ".join(f"Lvl {level}" for level in levels) + " | Lvl 75"
        self.stdout.write(header)
        self.stdout.write("  " + "-" * (len(header) - 2))
        for step in steps:
            cells = []
            for level in [*levels, int(config["MAX_LEVEL"])]:
                xp = step * (level - 1) * level // 2
                cells.append(f"{xp / cap:.1f} d" if cap else "n/a")
            marker = " (current)" if step == int(config["XP_PER_LEVEL_STEP"]) else ""
            self.stdout.write(f"  {step:>4}{marker:<10} | " + " | ".join(cells))

        max_level = int(config["MAX_LEVEL"])
        current_xp = int(config["XP_PER_LEVEL_STEP"]) * (max_level - 1) * max_level // 2
        self.stdout.write(
            f"  at {cap} XP/day, level 75 needs {current_xp:,} XP "
            f"({current_xp / cap:.0f} days) with the current step."
        )
        self.stdout.write(
            "  recommended XP_PER_LEVEL_STEP = 20: ~4.5 days to Lv 10, "
            "~242 days to Lv 70, ~278 days to Lv 75."
        )

    def _warnings(self) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Warnings"))
        counts = Counter(
            Question.objects.filter(active=True).values_list("subject", "grade")
        )
        thin = [
            f"grade {grade} {subject} ({counts.get((subject, grade), 0)})"
            for grade in range(QUIZ_GRADE_MIN, QUIZ_GRADE_MAX + 1)
            for subject in SUBJECT_KEYS
            if subject != "math" and counts.get((subject, grade), 0) < RECOMMENDED_PER_SUBJECT
        ]
        if thin:
            self.stdout.write(
                f"  fewer than {RECOMMENDED_PER_SUBJECT} active questions: "
                + ", ".join(thin)
            )
        else:
            self.stdout.write("  bank coverage looks fine for every grade and subject")
