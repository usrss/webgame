"""Import quiz questions from a CSV file (Phase 7).

The import is all-or-nothing: every row is validated first, and the rows are
written in a single transaction. A bad row aborts the whole file and reports the
line number, so a half-imported bank is impossible.

CSV layout (header required)::

    grade,subject,prompt,choice1,choice2,choice3,choice4,correct_index,explanation

``correct_index`` is 0-based. ``explanation`` may be empty.
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from game.models import QUIZ_GRADE_MAX, QUIZ_GRADE_MIN, SUBJECT_KEYS, Question

REQUIRED_COLUMNS = [
    "grade",
    "subject",
    "prompt",
    "choice1",
    "choice2",
    "choice3",
    "choice4",
    "correct_index",
    "explanation",
]


class Command(BaseCommand):
    help = "Import quiz questions from a CSV file (all-or-nothing)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV file.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report without writing anything.",
        )

    def handle(self, *args, **options):
        path = Path(options["csv_path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = [name.strip() for name in (reader.fieldnames or [])]
            missing = [name for name in REQUIRED_COLUMNS if name not in fieldnames]
            if missing:
                raise CommandError(
                    "Missing column(s): " + ", ".join(missing) + " (line 1)."
                )
            reader.fieldnames = fieldnames

            rows = []
            for line_number, raw in enumerate(reader, start=2):
                rows.append(self._parse_row(raw, line_number))

        if not rows:
            raise CommandError("No question rows found.")

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(f"Dry run: {len(rows)} row(s) valid, nothing written.")
            )
            self._summary(rows)
            return

        with transaction.atomic():
            created = Question.objects.bulk_create([Question(**row) for row in rows])

        self.stdout.write(self.style.SUCCESS(f"Imported {len(created)} question(s)."))
        self._summary(rows)
        self.stdout.write(
            "Review these questions by hand before players see them: "
            "use the admin or `active` to hide any that are wrong."
        )

    # ------------------------------------------------------------------ parsing

    def _parse_row(self, raw, line_number: int) -> dict:
        def text(name: str) -> str:
            return (raw.get(name) or "").strip()

        grade_text = text("grade")
        try:
            grade = int(grade_text)
        except ValueError:
            raise CommandError(f"Line {line_number}: grade must be a number.")
        if not QUIZ_GRADE_MIN <= grade <= QUIZ_GRADE_MAX:
            raise CommandError(
                f"Line {line_number}: grade must be {QUIZ_GRADE_MIN}-{QUIZ_GRADE_MAX}."
            )

        subject = text("subject").lower()
        if subject not in SUBJECT_KEYS:
            raise CommandError(
                f"Line {line_number}: unknown subject {subject!r} "
                f"(use {', '.join(SUBJECT_KEYS)})."
            )

        prompt = text("prompt")
        if not prompt:
            raise CommandError(f"Line {line_number}: prompt is empty.")
        if len(prompt) > 200:
            raise CommandError(f"Line {line_number}: prompt is longer than 200 characters.")

        choices = [text(f"choice{index}") for index in range(1, 5)]
        if any(not choice for choice in choices):
            raise CommandError(f"Line {line_number}: all four choices are required.")
        if len(set(choices)) != 4:
            raise CommandError(f"Line {line_number}: choices must be distinct.")
        if any(len(choice) > 200 for choice in choices):
            raise CommandError(f"Line {line_number}: a choice is longer than 200 characters.")

        try:
            correct_index = int(text("correct_index"))
        except ValueError:
            raise CommandError(
                f"Line {line_number}: correct_index must be 0, 1, 2 or 3."
            )
        if correct_index not in range(4):
            raise CommandError(
                f"Line {line_number}: correct_index must be 0, 1, 2 or 3."
            )

        explanation = text("explanation")
        if len(explanation) > 200:
            raise CommandError(
                f"Line {line_number}: explanation is longer than 200 characters."
            )

        return {
            "subject": subject,
            "grade": grade,
            "prompt": prompt,
            "choices": choices,
            "correct_index": correct_index,
            "explanation": explanation,
            "active": True,
        }

    def _summary(self, rows) -> None:
        counts: dict[tuple[str, int], int] = {}
        for row in rows:
            key = (row["subject"], row["grade"])
            counts[key] = counts.get(key, 0) + 1
        for (subject, grade), count in sorted(counts.items()):
            self.stdout.write(f"  grade {grade} {subject}: {count}")
