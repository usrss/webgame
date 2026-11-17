"""Tests for Phase 8: custom quiz uploads with difficulty bands."""

from __future__ import annotations

import csv
import io
import json
import random
import tempfile
import zipfile
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from game.models import QuizBand, QuizSet, Question, QuestionAttempt, Tank
from game.quiz.bank import pick_question
from game.quiz.importers import ParsedItem, UploadRejected, parse_bytes, parse_upload
from game.quiz.importers.safety import read_upload
from game.quiz.importers.text_layout import parse_text
from game.quiz.sets import (
    activate_set,
    create_draft_set,
    delete_set,
    parse_band_input,
    save_bands,
    suggested_bands,
    update_tank_quiz_config,
)
from game.quiz.services import issue_question, remaining_today
from game.services import create_tank

User = get_user_model()
BASE_SETTINGS = dict(settings.GAME_SETTINGS)

_user_counter = 0


def make_user():
    global _user_counter
    _user_counter += 1
    return User.objects.create_user(username=f"teacher{_user_counter}", password="pw-123456")


def items(count=12, start=1):
    return [
        {
            "number": start + offset,
            "prompt": f"Question {start + offset}?",
            "choices": ["one", "two", "three"],
            "correct_index": 0,
            "explanation": "Because.",
        }
        for offset in range(count)
    ]


def make_csv(rows) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["no", "question", "a", "b", "c", "d", "answer", "explanation"])
    for row in rows:
        writer.writerow(
            [
                row["number"],
                row["prompt"],
                *row["choices"],
                *([""] * (4 - len(row["choices"]))),
                "ABCD"[row["correct_index"]],
                row.get("explanation", ""),
            ]
        )
    return buffer.getvalue().encode("utf-8")


def make_txt(rows) -> bytes:
    lines = []
    for row in rows:
        lines.append(f"{row['number']}. {row['prompt']}")
        for position, choice in enumerate(row["choices"]):
            lines.append(f"{'ABCD'[position]}. {choice}")
        lines.append(f"Answer: {'ABCD'[row['correct_index']]}")
        if row.get("explanation"):
            lines.append(f"Explanation: {row['explanation']}")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def make_xlsx(rows) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["no", "question", "a", "b", "c", "d", "answer", "explanation"])
    for row in rows:
        sheet.append(
            [
                row["number"],
                row["prompt"],
                *row["choices"],
                *([""] * (4 - len(row["choices"]))),
                "ABCD"[row["correct_index"]],
                row.get("explanation", ""),
            ]
        )
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def make_docx(rows) -> bytes:
    from docx import Document

    document = Document()
    for row in rows:
        document.add_paragraph(f"{row['number']}. {row['prompt']}")
        for position, choice in enumerate(row["choices"]):
            document.add_paragraph(f"{'ABCD'[position]}. {choice}")
        document.add_paragraph(f"Answer: {'ABCD'[row['correct_index']]}")
        if row.get("explanation"):
            document.add_paragraph(f"Explanation: {row['explanation']}")
        document.add_paragraph("")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_quiz_set(owner, count=12, status="active", bands=None, name=None):
    quiz_set = QuizSet.objects.create(
        owner=owner, name=name or f"Quiz {QuizSet.objects.count() + 1}", status=status
    )
    Question.objects.bulk_create(
        [
            Question(
                subject="custom",
                grade=0,
                prompt=f"Q{number}?",
                choices=[f"{number}a", f"{number}b", f"{number}c"],
                correct_index=0,
                explanation="",
                quiz_set=quiz_set,
                item_number=number,
                difficulty="",
            )
            for number in range(1, count + 1)
        ]
    )
    if bands is None:
        bands = [("easy", 1, max(1, count // 3)), ("medium", count // 3 + 1, count)]
        bands = [band for band in bands if band[1] <= band[2]]
    if bands:
        save_bands(quiz_set, bands)
    return quiz_set


def attach(tank, quiz_set, mode="all", fixed=""):
    tank.quiz_source = "custom"
    tank.quiz_set = quiz_set
    tank.quiz_difficulty_mode = mode
    tank.quiz_fixed_difficulty = fixed
    tank.save(
        update_fields=[
            "quiz_source",
            "quiz_set",
            "quiz_difficulty_mode",
            "quiz_fixed_difficulty",
        ]
    )
    return tank


# --------------------------------------------------------------------- parsers


class CsvParserTests(TestCase):
    def test_bom_semicolon_crlf_and_numeric_answer(self):
        data = (
            "\ufeffno;question;a;b;c;d;answer;explanation\r\n"
            '1;"What is 2 + 2, really?";3;4;5;6;2;Because\r\n'
        ).encode("utf-8")
        result = parse_bytes("csv", data)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.valid_count, 1)
        item = result.items[0]
        self.assertEqual(item.prompt, "What is 2 + 2, really?")
        self.assertEqual(item.choices, ["3", "4", "5", "6"])
        self.assertEqual(item.correct_index, 1)
        self.assertEqual(item.explanation, "Because")

    def test_cp1252_fallback_is_reported(self):
        data = "no,question,a,b,c,answer\n1,Caf\u00e9?,x,y,z,A\n".encode("cp1252")
        result = parse_bytes("csv", data)

        self.assertEqual(result.encoding, "cp1252")
        self.assertEqual(result.items[0].prompt, "Caf\u00e9?")

    def test_missing_optional_columns_and_three_choices(self):
        data = b"question,a,b,c,answer\nPick one,1,2,3,C\n"
        result = parse_bytes("csv", data)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.items[0].number, 1)
        self.assertEqual(result.items[0].correct_index, 2)

    def test_errors_keep_other_valid_rows_and_line_numbers(self):
        data = (
            "no,question,a,b,c,answer\n"
            "1,Good?,x,y,z,A\n"
            "2,Bad?,x,y,z,E\n"
            "3,,x,y,z,A\n"
        ).encode("utf-8")
        result = parse_bytes("csv", data)

        self.assertEqual(result.valid_count, 1)
        self.assertEqual(result.items[0].number, 1)
        self.assertTrue(any("Row 3" in error and "answer" in error for error in result.errors))
        self.assertTrue(any("Row 4" in error and "empty" in error for error in result.errors))

    def test_missing_header_is_reported(self):
        result = parse_bytes("csv", b"1,What?,a,b,c,A\n")
        self.assertEqual(result.valid_count, 0)
        self.assertTrue(any("header" in error for error in result.errors))


class XlsxParserTests(TestCase):
    def test_xlsx_parses_like_csv(self):
        result = parse_bytes("xlsx", make_xlsx(items(3)))

        self.assertEqual(result.errors, [])
        self.assertEqual([item.prompt for item in result.items], [f"Question {n}?" for n in (1, 2, 3)])
        self.assertEqual(result.items[0].choices, ["one", "two", "three"])


class TextParserTests(TestCase):
    def test_marker_styles_three_choices_and_sequential_numbers(self):
        data = (
            "Question one with a wrap\nthat continues here?\n"
            "A) alpha\nB) beta\n(c) gamma\nAnswer: B\n"
            "Explanation: second line\n\n"
            "2. Second question?\n(A) one\n(B) two\n(C) three\n(D) four\nAnswer: D\n"
        )
        result = parse_bytes("txt", data.encode("utf-8"))

        self.assertEqual(result.errors, [])
        self.assertEqual(result.valid_count, 2)
        first, second = result.items
        self.assertEqual(first.number, 1)
        self.assertEqual(first.prompt, "Question one with a wrap that continues here?")
        self.assertEqual(first.choices, ["alpha", "beta", "gamma"])
        self.assertEqual(first.correct_index, 1)
        self.assertEqual(first.explanation, "second line")
        self.assertEqual(second.number, 2)
        self.assertEqual(second.correct_index, 3)

    def test_answer_without_choices_says_how_to_fix_word_lists(self):
        data = "1. What is 2 + 2?\n3\n4\n5\nAnswer: B\n"
        result = parse_bytes("txt", data.encode("utf-8"))

        self.assertEqual(result.valid_count, 0)
        self.assertTrue(any("typed as A. B. C. D." in error for error in result.errors))
        self.assertTrue(any("automatic lists" in error for error in result.errors))

    def test_missing_answer_line_is_an_error(self):
        data = "1. What is 2 + 2?\nA. 3\nB. 4\nC. 5\n"
        result = parse_bytes("txt", data.encode("utf-8"))

        self.assertEqual(result.valid_count, 0)
        self.assertTrue(any("no Answer: line" in error for error in result.errors))

    def test_non_consecutive_choice_letters_are_rejected(self):
        data = "1. What?\nA. one\nC. three\nD. four\nAnswer: A\n"
        result = parse_bytes("txt", data.encode("utf-8"))

        self.assertEqual(result.valid_count, 0)
        self.assertTrue(any("in order" in error for error in result.errors))

    def test_duplicate_item_numbers_skip_the_later_item(self):
        data = (
            "1. First?\nA. a\nB. b\nC. c\nAnswer: A\n"
            "1. Second?\nA. a\nB. b\nC. c\nAnswer: A\n"
        )
        result = parse_bytes("txt", data.encode("utf-8"))

        self.assertEqual(result.valid_count, 1)
        self.assertEqual(result.items[0].prompt, "First?")
        self.assertTrue(any("used twice" in error for error in result.errors))


class DocxParserTests(TestCase):
    def test_docx_parses_paragraphs(self):
        result = parse_bytes("docx", make_docx(items(2)))

        self.assertEqual(result.errors, [])
        self.assertEqual(result.valid_count, 2)
        self.assertEqual(result.items[1].prompt, "Question 2?")

    def test_auto_numbered_choices_produce_the_specific_error(self):
        from docx import Document

        document = Document()
        document.add_paragraph("1. What is 2 + 2?")
        for choice in ("3", "4", "5"):
            document.add_paragraph(choice)
        document.add_paragraph("Answer: B")
        buffer = io.BytesIO()
        document.save(buffer)

        result = parse_bytes("docx", buffer.getvalue())

        self.assertEqual(result.valid_count, 0)
        self.assertTrue(any("typed as A. B. C. D." in error for error in result.errors))


class CrossFormatTests(TestCase):
    def test_all_formats_produce_identical_items(self):
        rows = items(3)
        expected = [
            (row["number"], row["prompt"], tuple(row["choices"]), row["correct_index"], "Because.")
            for row in rows
        ]
        for fmt, builder in (
            ("csv", make_csv),
            ("txt", make_txt),
            ("xlsx", make_xlsx),
            ("docx", make_docx),
        ):
            with self.subTest(fmt=fmt):
                result = parse_bytes(fmt, builder(rows))
                self.assertEqual(result.errors, [])
                actual = [
                    (item.number, item.prompt, tuple(item.choices), item.correct_index, item.explanation)
                    for item in result.items
                ]
                self.assertEqual(actual, expected)


class ItemValidationTests(TestCase):
    def make(self, text):
        return parse_bytes("txt", text.encode("utf-8"))

    def test_too_few_choices(self):
        result = self.make("1. Q?\nA. a\nB. b\nAnswer: A\n")
        self.assertTrue(any("Provide 3 or 4 choices" in error for error in result.errors))

    def test_duplicate_choices_case_insensitive(self):
        result = self.make("1. Q?\nA. Same\nB. same\nC. other\nAnswer: A\n")
        self.assertTrue(any("must be different" in error for error in result.errors))

    def test_answer_beyond_choices(self):
        result = self.make("1. Q?\nA. a\nB. b\nC. c\nAnswer: D\n")
        self.assertTrue(any("points at a choice that does not exist" in error for error in result.errors))

    def test_overlong_prompt_and_choice(self):
        long_prompt = self.make(f"1. {'x' * 301}\nA. a\nB. b\nC. c\nAnswer: A\n")
        self.assertTrue(any("the limit is 300" in error for error in long_prompt.errors))

        long_choice = self.make(f"1. Q?\nA. {'y' * 101}\nB. b\nC. c\nAnswer: A\n")
        self.assertTrue(any("longer than 100" in error for error in long_choice.errors))

    @override_settings(GAME_SETTINGS={**BASE_SETTINGS, "QUIZ_SET_MAX_QUESTIONS": 2})
    def test_maximum_item_count(self):
        result = parse_bytes("txt", make_txt(items(3)))
        self.assertEqual(result.valid_count, 2)
        self.assertTrue(any("at most 2" in error for error in result.errors))

    def test_whitespace_and_text_are_cleaned_not_escaped(self):
        result = self.make("1.   <b>Bold</b>   question?\nA. <i>a</i>\nB. b\nC. c\nAnswer: A\n")
        self.assertEqual(result.items[0].prompt, "<b>Bold</b> question?")
        # Rendering escapes it; the stored text stays exactly as typed.


class UploadSafetyTests(TestCase):
    def upload(self, name, data):
        return read_upload(SimpleUploadedFile(name, data))

    def test_wrong_extension_and_macros_are_rejected(self):
        for name in ("quiz.pdf", "quiz.xlsm", "quiz.exe"):
            with self.subTest(name=name):
                with self.assertRaises(UploadRejected):
                    self.upload(name, b"data")

    def test_oversized_text_and_nul_bytes(self):
        limit = settings.GAME_SETTINGS["QUIZ_UPLOAD_MAX_BYTES_TEXT"]
        with self.assertRaises(UploadRejected):
            self.upload("quiz.csv", b"a" * (limit + 1))
        with self.assertRaises(UploadRejected):
            self.upload("quiz.csv", b"no,question\n\x00\x01")

    def test_zip_with_too_many_entries(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for index in range(settings.GAME_SETTINGS["QUIZ_ZIP_MAX_ENTRIES"] + 1):
                archive.writestr(f"part{index}.txt", "x")
        with self.assertRaises(UploadRejected):
            self.upload("quiz.docx", buffer.getvalue())

    def test_zip_bomb_and_path_traversal(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", b"\x00" * 2_000_000)
        with self.assertRaises(UploadRejected) as caught:
            self.upload("quiz.docx", buffer.getvalue())
        self.assertIn("bomb", str(caught.exception))

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../evil.txt", "nope")
        with self.assertRaises(UploadRejected):
            self.upload("quiz.docx", buffer.getvalue())

    def test_xxe_xml_is_rejected(self):
        evil = (
            '<?xml version="1.0"?><!DOCTYPE foo ['
            '<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", evil)
        with self.assertRaises(UploadRejected):
            self.upload("quiz.docx", buffer.getvalue())

    def test_upload_is_not_written_to_media_root(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                parsed = parse_upload(SimpleUploadedFile("quiz.csv", make_csv(items(2))))
                self.assertEqual(parsed.valid_count, 2)
                import os

                self.assertEqual(os.listdir(media_root), [])


# ----------------------------------------------------------------------- bands


class BandTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.quiz_set = make_quiz_set(self.owner, count=12, status="draft", bands=[])

    def test_parse_band_input_rejects_overlap_and_bad_ranges(self):
        for rows in (
            [("easy", 1, 10), ("medium", 10, 12)],
            [("easy", 5, 2)],
            [("easy", 1, 10), ("easy", 11, 12)],
            [("easy", 0, 4)],
            [("easy", "x", 4)],
            [("easy", 1, "")],
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(ValidationError):
                    parse_band_input(rows)

    def test_save_bands_sets_and_clears_difficulties(self):
        save_bands(self.quiz_set, [("easy", 1, 5), ("hard", 10, 12)])
        difficulties = dict(
            self.quiz_set.questions.values_list("item_number", "difficulty")
        )

        self.assertEqual(difficulties[1], "easy")
        self.assertEqual(difficulties[5], "easy")
        self.assertEqual(difficulties[6], "")
        self.assertEqual(difficulties[10], "hard")
        self.assertEqual(difficulties[12], "hard")

    def test_suggested_bands_split_into_thirds(self):
        self.assertEqual(
            suggested_bands(list(range(1, 10))),
            [
                {"difficulty": "easy", "start": 1, "end": 3},
                {"difficulty": "medium", "start": 4, "end": 6},
                {"difficulty": "hard", "start": 7, "end": 9},
            ],
        )

    def test_activation_needs_a_band_and_enough_questions(self):
        with self.assertRaises(ValidationError):
            activate_set(self.quiz_set)

        save_bands(self.quiz_set, [("easy", 1, 5)])
        with self.assertRaises(ValidationError):
            activate_set(self.quiz_set)

        save_bands(self.quiz_set, [("easy", 1, 10)])
        activate_set(self.quiz_set)
        self.quiz_set.refresh_from_db()
        self.assertEqual(self.quiz_set.status, "active")

    def test_draft_quota(self):
        limit = settings.GAME_SETTINGS["QUIZ_SETS_PER_USER"]
        for index in range(limit - 1):
            QuizSet.objects.create(owner=self.owner, name=f"Extra {index}")
        item = ParsedItem(
            number=1,
            prompt="Q?",
            choices=["a", "b", "c"],
            correct_index=0,
            explanation="",
            source_ref="Row 2",
        )
        with self.assertRaises(ValidationError):
            create_draft_set(self.owner, "Too many", "q.csv", "csv", [item])


# ------------------------------------------------------------------- selection


class CustomSelectionTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Custom Tank", "Nibble")
        self.quiz_set = make_quiz_set(
            self.owner,
            count=12,
            bands=[("easy", 1, 4), ("medium", 5, 8), ("hard", 9, 12)],
        )

    def draw(self, mode="all", stage=0, fixed="", seed=5):
        self.fish.stage = stage
        self.fish.save(update_fields=["stage"])
        attach(self.tank, self.quiz_set, mode=mode, fixed=fixed)
        return pick_question(self.owner, self.tank, rng=random.Random(seed), fish=self.fish)

    def test_by_stage_maps_stages_to_bands(self):
        for stage, expected in (
            (0, "easy"),
            (1, "easy"),
            (2, "medium"),
            (3, "medium"),
            (4, "hard"),
            (5, "hard"),
        ):
            with self.subTest(stage=stage):
                self.assertEqual(self.draw(stage=stage, mode="by_stage").difficulty, expected)

    def test_by_stage_falls_back_to_nearest_band_preferring_easier(self):
        save_bands(self.quiz_set, [("easy", 1, 4)])
        self.assertEqual(self.draw(stage=5, mode="by_stage").difficulty, "easy")

    def test_fixed_and_all_modes(self):
        self.assertEqual(self.draw(mode="fixed", fixed="medium").difficulty, "medium")
        seen = {self.draw(mode="all", seed=seed).difficulty for seed in range(1, 30)}
        self.assertEqual(seen, {"easy", "medium", "hard"})

    def test_items_outside_bands_are_never_issued(self):
        save_bands(self.quiz_set, [("easy", 1, 4), ("medium", 9, 12)])
        for seed in range(200):
            picked = self.draw(mode="all", seed=seed)
            self.assertIn(picked.question.item_number, {1, 2, 3, 4, 9, 10, 11, 12})

    def test_pool_cycles_before_repeating(self):
        quiz_set = make_quiz_set(
            self.owner, count=3, bands=[("easy", 1, 3)], name="Tiny"
        )
        attach(self.tank, quiz_set, mode="all")
        seen = []
        for seed in range(3):
            picked = pick_question(
                self.owner, self.tank, rng=random.Random(seed), fish=self.fish
            )
            seen.append(picked.question.item_number)
            # The pool exclusion is based on recent attempts; record a snapshot
            # so the next draw sees this question as recently used.
            QuestionAttempt.objects.create(
                user=self.owner,
                fish=self.fish,
                question=picked.question,
                subject="custom",
                grade=0,
                prompt=picked.prompt,
                choices=picked.choices,
                correct_index=picked.correct_index,
                issued_at=timezone.now() + timedelta(seconds=seed),
            )
        self.assertEqual(sorted(seen), [1, 2, 3])

    def test_single_question_pool_still_works(self):
        quiz_set = make_quiz_set(self.owner, count=1, bands=[("easy", 1, 1)], name="One")
        attach(self.tank, quiz_set, mode="all")
        for seed in range(2):
            picked = pick_question(
                self.owner, self.tank, rng=random.Random(seed), fish=self.fish
            )
            self.assertEqual(picked.question.item_number, 1)

    def test_disabled_questions_are_never_issued(self):
        self.quiz_set.questions.exclude(pk=self.quiz_set.questions.first().pk).update(
            active=False
        )
        for seed in range(20):
            picked = self.draw(mode="all", seed=seed)
            self.assertTrue(picked.question.active)

    def test_issue_snapshots_custom_fields(self):
        attach(self.tank, self.quiz_set, mode="by_stage")
        attempt = issue_question(self.owner, self.tank)

        self.assertEqual(attempt.subject, "custom")
        self.assertEqual(attempt.grade, 0)
        self.assertEqual(attempt.difficulty, "easy")
        self.assertEqual(attempt.quiz_set_name, self.quiz_set.name)
        self.assertIsNotNone(attempt.question)

    def test_only_owner_can_attach_a_set(self):
        stranger = make_user()
        with self.assertRaises(PermissionDenied):
            update_tank_quiz_config(
                self.tank, stranger, source="custom", quiz_set_id=self.quiz_set.pk
            )
        with self.assertRaises(ValidationError):
            update_tank_quiz_config(
                self.tank, self.owner, source="custom", quiz_set_id=self.quiz_set.pk + 999
            )

    def test_draft_sets_cannot_be_attached(self):
        self.quiz_set.status = "draft"
        self.quiz_set.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            update_tank_quiz_config(
                self.tank, self.owner, source="custom", quiz_set_id=self.quiz_set.pk
            )

    def test_delete_reverts_tanks_and_attempts_keep_working(self):
        attach(self.tank, self.quiz_set, mode="all")
        attempt = issue_question(self.owner, self.tank)
        QuestionAttempt.objects.filter(pk=attempt.pk).update(
            answered_at=timezone.now(),
            selected_index=attempt.correct_index,
            correct=True,
        )

        reverted = delete_set(self.quiz_set)

        self.assertEqual(reverted, ["Custom Tank"])
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_source, "builtin")
        self.assertIsNone(self.tank.quiz_set_id)
        attempt.refresh_from_db()
        self.assertTrue(attempt.correct)
        self.assertTrue(attempt.prompt.startswith("Q"))

    def test_switching_source_does_not_reset_the_daily_cap(self):
        attach(self.tank, self.quiz_set, mode="all")
        QuestionAttempt.objects.create(
            user=self.owner,
            fish=self.fish,
            subject="custom",
            grade=0,
            prompt="Q?",
            choices=["a", "b", "c"],
            correct_index=0,
            issued_at=timezone.now(),
            answered_at=timezone.now(),
            correct=True,
        )
        before = remaining_today(self.fish)

        update_tank_quiz_config(self.tank, self.owner, source="builtin")

        self.tank.refresh_from_db()
        self.assertEqual(remaining_today(self.fish), before)
        self.assertEqual(before, settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"] - 1)


# ----------------------------------------------------------------------- views


class QuizManagementViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "View Tank", "Nibble")
        self.client.force_login(self.owner)

    def upload(self, rows=None, name="Class quiz"):
        return self.client.post(
            reverse("game:quiz_upload"),
            {"name": name, "file": SimpleUploadedFile("quiz.csv", make_csv(rows or items(12)))},
        )

    def test_list_only_shows_own_sets(self):
        mine = make_quiz_set(self.owner, count=12)
        other = make_quiz_set(make_user(), count=12, name="Theirs")
        response = self.client.get(reverse("game:quiz_set_list"))

        self.assertContains(response, mine.name)
        self.assertNotContains(response, other.name)

    def test_upload_creates_a_draft_and_redirects_to_preview(self):
        response = self.upload()

        self.assertEqual(response.status_code, 302)
        quiz_set = QuizSet.objects.get(owner=self.owner)
        self.assertEqual(quiz_set.status, "draft")
        self.assertEqual(quiz_set.questions.count(), 12)
        self.assertEqual(quiz_set.source_format, "csv")
        self.assertEqual(quiz_set.questions.first().subject, "custom")
        self.assertEqual(quiz_set.questions.first().grade, 0)

    def test_upload_rejects_a_broken_file_without_creating_anything(self):
        response = self.client.post(
            reverse("game:quiz_upload"),
            {"name": "Bad", "file": SimpleUploadedFile("quiz.pdf", b"%PDF-1.4")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unsupported file type")
        self.assertEqual(QuizSet.objects.count(), 0)

    def test_preview_shows_errors_warnings_and_suggested_bands(self):
        response = self.client.post(
            reverse("game:quiz_upload"),
            {
                "name": "Mixed",
                "file": SimpleUploadedFile(
                    "quiz.csv",
                    b"no,question,a,b,c,answer\n1,Good?,x,y,z,A\n2,Bad?,x,y,z,E\n",
                ),
            },
        )
        detail = self.client.get(response.headers["Location"])

        self.assertContains(detail, "Skipped items")
        self.assertContains(detail, "Row 3")
        self.assertContains(detail, "Difficulty bands")
        self.assertContains(detail, "Activate quiz")

    def test_confirm_requires_bands_then_activates(self):
        self.upload()
        quiz_set = QuizSet.objects.get(owner=self.owner)
        confirm = reverse("game:quiz_set_confirm", args=[quiz_set.pk])

        self.client.post(confirm)
        quiz_set.refresh_from_db()
        self.assertEqual(quiz_set.status, "draft")

        self.client.post(
            reverse("game:quiz_set_bands", args=[quiz_set.pk]),
            {"easy_start": "1", "easy_end": "6", "medium_start": "7", "medium_end": "12"},
        )
        self.client.post(confirm)

        quiz_set.refresh_from_db()
        self.assertEqual(quiz_set.status, "active")
        self.assertEqual(quiz_set.questions.get(item_number=3).difficulty, "easy")
        self.assertEqual(quiz_set.questions.get(item_number=8).difficulty, "medium")

    def test_band_edit_recomputes_difficulties(self):
        quiz_set = make_quiz_set(self.owner, count=12)
        self.client.post(
            reverse("game:quiz_set_bands", args=[quiz_set.pk]),
            {"hard_start": "1", "hard_end": "3"},
        )
        self.assertEqual(quiz_set.questions.get(item_number=2).difficulty, "hard")
        self.assertEqual(quiz_set.questions.get(item_number=9).difficulty, "")

    def test_rename_toggle_and_delete(self):
        quiz_set = make_quiz_set(self.owner, count=12)
        question = quiz_set.questions.first()

        self.client.post(
            reverse("game:quiz_set_rename", args=[quiz_set.pk]), {"name": "Renamed"}
        )
        quiz_set.refresh_from_db()
        self.assertEqual(quiz_set.name, "Renamed")

        self.client.post(
            reverse(
                "game:quiz_question_toggle", args=[quiz_set.pk, question.pk]
            )
        )
        question.refresh_from_db()
        self.assertFalse(question.active)

        attach(self.tank, quiz_set, mode="all")
        self.client.post(reverse("game:quiz_set_delete", args=[quiz_set.pk]))
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_source, "builtin")

    def test_other_users_set_is_404_everywhere(self):
        theirs = make_quiz_set(make_user(), count=12)
        detail = reverse("game:quiz_set_detail", args=[theirs.pk])

        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("game:quiz_set_confirm", args=[theirs.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse("game:quiz_set_delete", args=[theirs.pk])).status_code,
            404,
        )

    def test_anonymous_users_are_redirected_to_login(self):
        self.client.logout()
        for name, args in (
            ("game:quiz_set_list", []),
            ("game:quiz_upload", []),
            ("game:quiz_template", ["csv"]),
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 302)

    def test_templates_download_in_all_formats(self):
        for fmt in ("csv", "txt", "xlsx", "docx"):
            with self.subTest(fmt=fmt):
                response = self.client.get(reverse("game:quiz_template", args=[fmt]))
                self.assertEqual(response.status_code, 200)
                self.assertIn("attachment", response.headers["Content-Disposition"])
                self.assertGreater(len(b"".join(response.streaming_content)), 100)

    def test_owner_switches_the_tank_to_a_custom_quiz(self):
        quiz_set = make_quiz_set(self.owner, count=12)
        response = self.client.post(
            reverse("game:tank_quiz_settings", args=[self.tank.pk]),
            data=json.dumps(
                {
                    "source": "custom",
                    "quiz_set": quiz_set.pk,
                    "difficulty_mode": "all",
                }
            ),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "custom")
        self.assertEqual(payload["quiz_set_id"], quiz_set.pk)
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_source, "custom")

        state = self.client.get(
            reverse("game:tank_state", args=[self.tank.pk])
        ).json()["quiz"]
        self.assertEqual(state["source"], "custom")
        self.assertEqual(state["set_name"], quiz_set.name)
        self.assertEqual(state["difficulty_mode"], "all")

    def test_member_cannot_switch_the_source(self):
        quiz_set = make_quiz_set(self.owner, count=12)
        member = make_user()
        Tank.objects.get(pk=self.tank.pk).fish.create(owner=member, name="Splash")
        self.client.force_login(member)

        response = self.client.post(
            reverse("game:tank_quiz_settings", args=[self.tank.pk]),
            data=json.dumps({"source": "custom", "quiz_set": quiz_set.pk}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_upload_is_rate_limited(self):
        for index in range(settings.GAME_SETTINGS["QUIZ_UPLOADS_PER_HOUR"]):
            response = self.upload(rows=items(1), name=f"Quiz {index}")
            self.assertEqual(response.status_code, 302)

        response = self.upload(rows=items(1), name="One too many")
        self.assertEqual(response.status_code, 429)
