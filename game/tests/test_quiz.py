"""Tests for Phase 7: quiz-based feeding.

Covers the generators, bank selection, the service rules (cap, TTL, daily reset,
no double feeds) and the three JSON endpoints.
"""

import json
import random
import re
import threading
from datetime import timedelta
from fractions import Fraction

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from game.models import Question, QuestionAttempt, Tank
from game.quiz.bank import pick_question
from game.quiz.exceptions import (
    AttemptAlreadyAnswered,
    AttemptExpired,
    AttemptNotFound,
    DailyCapReached,
    IssueTooFast,
    NoQuestionsAvailable,
    NotAMember,
    QuizInvalid,
)
from game.quiz.generators import generate_math
from game.quiz.services import (
    answer_question,
    correct_answers_today,
    issue_question,
    quiz_day_end,
    quiz_day_start,
    remaining_today,
    seconds_until_reset,
    update_quiz_settings,
)
from game.services import create_tank, feed

User = get_user_model()

BASE_SETTINGS = dict(settings.GAME_SETTINGS)
COOLDOWN_OVERRIDE = override_settings(
    GAME_SETTINGS={**BASE_SETTINGS, "QUIZ_ONLY_FEEDING": False}
)
QUIZ_ONLY = override_settings(
    GAME_SETTINGS={**BASE_SETTINGS, "QUIZ_ENABLED": True, "QUIZ_ONLY_FEEDING": True}
)

_user_counter = 0


def make_user():
    global _user_counter
    _user_counter += 1
    return User.objects.create_user(
        username=f"quizzer{_user_counter}", password="pw-123456"
    )


def make_bank_question(subject="science", grade=3, correct="", active=True):
    choices = ["alpha", "beta", "gamma", "delta"]
    if correct:
        choices[0] = correct
    return Question.objects.create(
        subject=subject,
        grade=grade,
        prompt=f"{subject} grade {grade} question {Question.objects.count()}",
        choices=choices,
        correct_index=0,
        explanation="Because it is.",
        active=active,
    )


def make_attempt(
    user, fish, correct_index=0, issued_at=None, answered_at=None, correct=None
):
    return QuestionAttempt.objects.create(
        user=user,
        fish=fish,
        subject="math",
        grade=3,
        prompt="1 + 1 = ?",
        choices=["1", "2", "3", "4"],
        correct_index=correct_index,
        explanation="One plus one is two.",
        issued_at=issued_at or timezone.now(),
        answered_at=answered_at,
        correct=correct,
    )


class QuizServiceTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Quiz Tank", "Nibble")

    def test_issue_creates_a_four_choice_attempt_at_the_tank_grade(self):
        attempt = issue_question(self.owner, self.tank)

        self.assertEqual(attempt.user, self.owner)
        self.assertEqual(attempt.fish, self.fish)
        self.assertEqual(len(attempt.choices), 4)
        self.assertEqual(len(set(attempt.choices)), 4)
        self.assertEqual(attempt.grade, self.tank.quiz_grade)
        self.assertIsNone(attempt.answered_at)
        self.assertIsNotNone(attempt.issued_at)

    def test_issue_returns_the_same_open_attempt(self):
        first = issue_question(self.owner, self.tank)
        second = issue_question(self.owner, self.tank)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(QuestionAttempt.objects.count(), 1)

    def test_expired_attempt_is_replaced(self):
        ttl = settings.GAME_SETTINGS["QUIZ_ATTEMPT_TTL_SECONDS"]
        stale = make_attempt(
            self.owner, self.fish, issued_at=timezone.now() - timedelta(seconds=ttl + 5)
        )

        fresh = issue_question(self.owner, self.tank)

        self.assertNotEqual(stale.pk, fresh.pk)
        self.assertEqual(QuestionAttempt.objects.count(), 2)

    def test_issue_too_fast_after_answering(self):
        attempt = make_attempt(self.owner, self.fish)
        answer_question(self.owner, attempt.pk, 0)

        with self.assertRaises(IssueTooFast) as caught:
            issue_question(self.owner, self.tank, now=timezone.now() + timedelta(seconds=1))
        self.assertGreaterEqual(caught.exception.retry_after, 1)

    def test_daily_cap_blocks_issue_with_reset_hint(self):
        cap = settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"]
        for _ in range(cap):
            make_attempt(
                self.owner, self.fish, answered_at=timezone.now(), correct=True
            )

        with self.assertRaises(DailyCapReached) as caught:
            issue_question(self.owner, self.tank)
        self.assertGreater(caught.exception.seconds_until_reset, 0)
        self.assertLessEqual(caught.exception.seconds_until_reset, 86400)

    def test_answers_before_local_midnight_do_not_count_today(self):
        make_attempt(
            self.owner,
            self.fish,
            answered_at=quiz_day_start() - timedelta(seconds=1),
        )

        self.assertEqual(correct_answers_today(self.fish), 0)
        self.assertEqual(remaining_today(self.fish), settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"])

    def test_correct_answer_feeds_without_the_timed_cooldown(self):
        feed(self.fish)  # starts the 5-minute cooldown
        attempt = make_attempt(self.owner, self.fish)
        before = self.fish.xp

        result = answer_question(self.owner, attempt.pk, attempt.correct_index)

        self.fish.refresh_from_db()
        self.assertTrue(result.correct)
        self.assertIsNotNone(result.feed)
        self.assertGreater(self.fish.xp, before)

    def test_wrong_answer_does_not_feed(self):
        attempt = make_attempt(self.owner, self.fish)
        wrong = 1 if attempt.correct_index != 1 else 2
        before = self.fish.xp

        result = answer_question(self.owner, attempt.pk, wrong)

        self.fish.refresh_from_db()
        self.assertFalse(result.correct)
        self.assertIsNone(result.feed)
        self.assertEqual(self.fish.xp, before)

    def test_remaining_today_decrements_only_on_correct(self):
        attempt = make_attempt(self.owner, self.fish)
        cap = settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"]

        result = answer_question(self.owner, attempt.pk, attempt.correct_index)
        self.assertEqual(result.remaining_today, cap - 1)

        second = make_attempt(self.owner, self.fish)
        wrong = 1 if second.correct_index != 1 else 2
        self.assertEqual(answer_question(self.owner, second.pk, wrong).remaining_today, cap - 1)

    def test_answering_twice_does_not_feed_twice(self):
        attempt = make_attempt(self.owner, self.fish)
        answer_question(self.owner, attempt.pk, attempt.correct_index)
        self.fish.refresh_from_db()
        xp_after_one = self.fish.xp

        with self.assertRaises(AttemptAlreadyAnswered):
            answer_question(self.owner, attempt.pk, attempt.correct_index)

        self.fish.refresh_from_db()
        self.assertEqual(self.fish.xp, xp_after_one)

    def test_expired_attempt_cannot_be_answered(self):
        ttl = settings.GAME_SETTINGS["QUIZ_ATTEMPT_TTL_SECONDS"]
        attempt = make_attempt(
            self.owner, self.fish, issued_at=timezone.now() - timedelta(seconds=ttl + 5)
        )

        with self.assertRaises(AttemptExpired):
            answer_question(self.owner, attempt.pk, 0)

        attempt.refresh_from_db()
        self.assertIsNone(attempt.answered_at)

    def test_other_users_attempt_looks_missing(self):
        stranger = make_user()
        attempt = make_attempt(stranger, self.fish)

        with self.assertRaises(AttemptNotFound):
            answer_question(self.owner, attempt.pk, 0)

    def test_invalid_selection_is_rejected(self):
        attempt = make_attempt(self.owner, self.fish)

        for value in (-1, 4, 99, "1", 1.0, None, True):
            with self.subTest(value=value):
                with self.assertRaises(QuizInvalid):
                    answer_question(self.owner, attempt.pk, value)

    def test_cap_is_rechecked_when_answering(self):
        cap = settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"]
        for _ in range(cap):
            make_attempt(
                self.owner, self.fish, answered_at=timezone.now(), correct=True
            )
        attempt = make_attempt(self.owner, self.fish)

        with self.assertRaises(DailyCapReached):
            answer_question(self.owner, attempt.pk, attempt.correct_index)

    def test_non_member_cannot_issue(self):
        stranger = make_user()

        with self.assertRaises(NotAMember):
            issue_question(stranger, self.tank)

    def test_day_boundaries_use_local_midnight(self):
        start = quiz_day_start()
        end = quiz_day_end()

        local_start = timezone.localtime(start)
        self.assertEqual((local_start.hour, local_start.minute, local_start.second), (0, 0, 0))
        self.assertEqual(end - start, timedelta(days=1))
        self.assertGreater(seconds_until_reset(), 0)
        self.assertLessEqual(seconds_until_reset(), 86400)


class QuizBankTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Bank Tank", "Nibble")

    def test_bank_question_is_used_for_the_configured_grade(self):
        self.tank.quiz_grade = 4
        self.tank.quiz_subjects = ["science"]
        self.tank.save()
        wanted = make_bank_question(grade=4)
        make_bank_question(grade=3)

        picked = pick_question(self.owner, self.tank, rng=random.Random(1))

        self.assertEqual(picked.question, wanted)
        self.assertEqual(picked.subject, "science")
        self.assertEqual(picked.choices[picked.correct_index], wanted.choices[wanted.correct_index])
        self.assertEqual(len(picked.choices), 4)

    def test_inactive_questions_are_never_used(self):
        self.tank.quiz_subjects = ["science"]
        self.tank.save()
        make_bank_question(active=False)

        with self.assertRaises(NoQuestionsAvailable):
            pick_question(self.owner, self.tank, rng=random.Random(2))

    def test_recent_questions_are_avoided_until_the_pool_runs_out(self):
        self.tank.quiz_subjects = ["science"]
        self.tank.save()
        first = make_bank_question()
        second = make_bank_question()
        for _ in range(5):
            make_attempt(self.owner, self.fish)
            QuestionAttempt.objects.filter(fish=self.fish).update(question=first)

        picked = pick_question(self.owner, self.tank, rng=random.Random(3))
        self.assertEqual(picked.question, second)

        # Only one question left in the pool: repeats are allowed rather than
        # failing the player outright.
        second.active = False
        second.save()
        self.assertEqual(
            pick_question(self.owner, self.tank, rng=random.Random(4)).question, first
        )

    def test_no_bank_questions_and_no_math_raises(self):
        self.tank.quiz_subjects = ["reading"]
        self.tank.save()

        with self.assertRaises(NoQuestionsAvailable):
            pick_question(self.owner, self.tank, rng=random.Random(5))

    def test_math_is_generated_when_configured(self):
        self.tank.quiz_subjects = ["math"]
        self.tank.quiz_grade = 2
        self.tank.save()

        self.assertIsNone(pick_question(self.owner, self.tank).question)


class MathGeneratorTests(TestCase):
    """300 draws per grade: no duplicates, no negatives, and correct answers."""

    def test_every_generated_question_is_well_formed(self):
        for grade in range(1, 7):
            rng = random.Random(500 + grade)
            for _ in range(300):
                with self.subTest(grade=grade):
                    question = generate_math(grade, rng=rng)
                    choices = [question.correct, *question.distractors]
                    self.assertEqual(len(choices), 4)
                    self.assertEqual(len(set(choices)), 4)
                    self.assertFalse(any(choice.startswith("-") for choice in choices))
                    self.assertLessEqual(len(question.prompt), 200)
                    self.assertLessEqual(max(len(choice) for choice in choices), 200)

    def test_generated_arithmetic_is_correct(self):
        for grade in range(1, 7):
            rng = random.Random(900 + grade)
            for _ in range(120):
                question = generate_math(grade, rng=rng)
                prompt, correct = question.prompt, question.correct
                try:
                    if " ÷ " in prompt:
                        dividend, divisor = re.findall(r"\d+", prompt)[:2]
                        self.assertEqual(int(dividend) % int(divisor), 0)
                        self.assertEqual(int(dividend) // int(divisor), int(correct))
                    elif " × " in prompt and " + " not in prompt and " - " not in prompt:
                        left, right = re.findall(r"\d+", prompt)[:2]
                        self.assertEqual(int(left) * int(right), int(correct))
                    elif "% of" in prompt:
                        percent, base = re.findall(r"\d+", prompt)[:2]
                        self.assertEqual(int(percent) * int(base) % 100, 0)
                        self.assertEqual(int(base) * int(percent) // 100, int(correct))
                    elif re.fullmatch(r"\d+/\d+ [+\-] \d+/\d+ = \?", prompt):
                        values = re.findall(r"(\d+)/(\d+)", prompt)
                        left = Fraction(int(values[0][0]), int(values[0][1]))
                        right = Fraction(int(values[1][0]), int(values[1][1]))
                        expected = left + right if " + " in prompt else left - right
                        self.assertEqual(Fraction(correct), expected)
                    elif re.fullmatch(r"\d+\.\d [+\-] \d+\.\d = \?", prompt):
                        left, right = [Fraction(x) for x in re.findall(r"\d+\.\d", prompt)]
                        expected = left + right if " + " in prompt else left - right
                        self.assertEqual(Fraction(correct), expected)
                except ValueError:
                    self.fail(f"unexpected prompt shape: {prompt}")


class QuizEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Quiz Tank", "Nibble")
        self.client.force_login(self.owner)
        self.next_url = reverse("game:tank_quiz_next", args=[self.tank.pk])
        self.answer_url = reverse("game:tank_quiz_answer", args=[self.tank.pk])
        self.settings_url = reverse("game:tank_quiz_settings", args=[self.tank.pk])

    def post_json(self, url, payload=None):
        return self.client.post(
            url,
            data=json.dumps(payload or {}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

    def test_next_hides_the_answer(self):
        response = self.client.post(self.next_url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("correct_index", payload)
        self.assertEqual(
            set(payload),
            {
                "attempt_id",
                "subject",
                "grade",
                "prompt",
                "choices",
                "difficulty",
                "expires_in",
                "remaining_today",
                "cap",
            },
        )
        self.assertEqual(len(payload["choices"]), 4)
        self.assertGreater(payload["expires_in"], 0)
        self.assertEqual(payload["cap"], settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"])
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_next_is_idempotent_while_the_attempt_is_open(self):
        first = self.client.post(self.next_url).json()
        second = self.client.post(self.next_url).json()

        self.assertEqual(first["attempt_id"], second["attempt_id"])

    def test_next_reports_the_daily_cap(self):
        cap = settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"]
        for _ in range(cap):
            make_attempt(
                self.owner, self.fish, answered_at=timezone.now(), correct=True
            )

        response = self.client.post(self.next_url)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "daily_cap")
        self.assertIn("seconds_until_reset", response.json())

    def test_next_reports_too_fast(self):
        attempt = make_attempt(self.owner, self.fish)
        answer_question(self.owner, attempt.pk, 0)

        response = self.client.post(self.next_url)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "too_fast")
        self.assertIn("retry_after", response.json())

    def test_next_reports_no_questions(self):
        self.tank.quiz_subjects = ["reading"]
        self.tank.quiz_grade = 2
        self.tank.save()

        response = self.client.post(self.next_url)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "no_questions")

    def test_answer_correct_feeds_without_leaking_the_key(self):
        attempt = make_attempt(self.owner, self.fish)

        response = self.post_json(
            self.answer_url,
            {"attempt_id": attempt.pk, "selected_index": attempt.correct_index},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["correct"])
        self.assertNotIn("correct_index", payload)
        self.assertEqual(payload["explanation"], "One plus one is two.")
        self.assertIsNotNone(payload["feed"])
        self.assertGreater(payload["feed"]["xp_gained"], 0)
        self.assertEqual(payload["feed"]["fish"]["id"], self.fish.pk)
        self.assertEqual(payload["remaining_today"], payload["cap"] - 1)
        self.fish.refresh_from_db()
        self.assertGreater(self.fish.xp, 0)

    def test_answer_wrong_does_not_reveal_the_answer_or_feed(self):
        attempt_id = self.client.post(self.next_url).json()["attempt_id"]
        attempt = QuestionAttempt.objects.get(pk=attempt_id)
        wrong = (attempt.correct_index + 1) % len(attempt.choices)

        response = self.post_json(
            self.answer_url, {"attempt_id": attempt_id, "selected_index": wrong}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["correct"])
        self.assertIsNone(payload["feed"])
        # Wrong answers say only "wrong": no answer key, and no explanation
        # that would give the answer away.
        self.assertNotIn("correct_index", payload)
        self.assertEqual(payload["explanation"], "")
        self.fish.refresh_from_db()
        self.assertEqual(self.fish.xp, 0)

    def test_answer_twice_is_409(self):
        attempt_id = self.client.post(self.next_url).json()["attempt_id"]
        attempt = QuestionAttempt.objects.get(pk=attempt_id)
        body = {"attempt_id": attempt_id, "selected_index": attempt.correct_index}
        self.assertEqual(self.post_json(self.answer_url, body).status_code, 200)

        response = self.post_json(self.answer_url, body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "already_answered")

    def test_answer_expired_is_410(self):
        ttl = settings.GAME_SETTINGS["QUIZ_ATTEMPT_TTL_SECONDS"]
        attempt = make_attempt(
            self.owner, self.fish, issued_at=timezone.now() - timedelta(seconds=ttl + 5)
        )

        response = self.post_json(
            self.answer_url, {"attempt_id": attempt.pk, "selected_index": 0}
        )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error"], "expired")

    def test_answer_invalid_selection_is_400(self):
        attempt_id = self.client.post(self.next_url).json()["attempt_id"]

        for value in (4, -1, "1", None, 1.5):
            with self.subTest(value=value):
                response = self.post_json(
                    self.answer_url, {"attempt_id": attempt_id, "selected_index": value}
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "invalid")

    def test_answer_unknown_attempt_is_404(self):
        response = self.post_json(
            self.answer_url, {"attempt_id": 999999, "selected_index": 0}
        )
        self.assertEqual(response.status_code, 404)

    def test_answer_without_attempt_id_is_400(self):
        response = self.post_json(self.answer_url, {"selected_index": 0})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid")

    def test_other_users_attempt_is_404(self):
        member = make_user()
        member_fish = Tank.objects.get(pk=self.tank.pk).fish.create(
            owner=member, name="Splash"
        )
        attempt = make_attempt(member, member_fish)

        response = self.post_json(
            self.answer_url, {"attempt_id": attempt.pk, "selected_index": 0}
        )
        self.assertEqual(response.status_code, 404)

    def test_answer_respects_the_daily_cap(self):
        cap = settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"]
        for _ in range(cap):
            make_attempt(
                self.owner, self.fish, answered_at=timezone.now(), correct=True
            )
        attempt = make_attempt(self.owner, self.fish)

        response = self.post_json(
            self.answer_url,
            {"attempt_id": attempt.pk, "selected_index": attempt.correct_index},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "daily_cap")

    def test_non_member_gets_404_everywhere(self):
        stranger = make_user()
        self.client.force_login(stranger)

        self.assertEqual(self.client.post(self.next_url).status_code, 404)
        self.assertEqual(
            self.post_json(
                self.answer_url, {"attempt_id": 1, "selected_index": 0}
            ).status_code,
            404,
        )
        self.assertEqual(self.post_json(self.settings_url, {}).status_code, 404)

    def test_methods_other_than_post_are_rejected(self):
        self.assertEqual(self.client.get(self.next_url).status_code, 405)
        self.assertEqual(self.client.get(self.answer_url).status_code, 405)
        self.assertEqual(self.client.get(self.settings_url).status_code, 405)

    def test_next_is_rate_limited(self):
        limit = settings.GAME_SETTINGS["QUIZ_NEXT_RATE_LIMIT_ATTEMPTS"]
        for _ in range(limit):
            self.assertEqual(self.client.post(self.next_url).status_code, 200)

        response = self.client.post(self.next_url)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)


class QuizStateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "State Tank", "Nibble")
        self.client.force_login(self.owner)
        self.url = reverse("game:tank_state", args=[self.tank.pk])

    def test_state_includes_my_quiz_block(self):
        quiz = self.client.get(self.url).json()["quiz"]

        self.assertEqual(
            set(quiz),
            {
                "enabled",
                "only_feeding",
                "remaining_today",
                "cap",
                "grade",
                "subjects",
                "source",
                "set_name",
                "difficulty_mode",
            },
        )
        self.assertIs(quiz["enabled"], True)
        self.assertEqual(quiz["cap"], settings.GAME_SETTINGS["QUIZ_DAILY_CORRECT_CAP"])
        self.assertEqual(quiz["grade"], self.tank.quiz_grade)
        self.assertEqual(quiz["subjects"], self.tank.quiz_subjects)

    def test_state_remaining_drops_after_a_correct_answer(self):
        attempt = make_attempt(self.owner, self.fish)
        answer_question(self.owner, attempt.pk, attempt.correct_index)

        quiz = self.client.get(self.url).json()["quiz"]
        self.assertEqual(quiz["remaining_today"], quiz["cap"] - 1)

    def test_other_players_fish_do_not_leak_attempts(self):
        member = make_user()
        Tank.objects.get(pk=self.tank.pk).fish.create(owner=member, name="Splash")
        self.client.force_login(member)

        quiz = self.client.get(self.url).json()["quiz"]
        self.assertEqual(quiz["remaining_today"], quiz["cap"])


class QuizSettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Settings Tank", "Nibble")
        self.url = reverse("game:tank_quiz_settings", args=[self.tank.pk])

    def test_owner_can_save_grade_and_subjects(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            self.url,
            data=json.dumps({"grade": 5, "subjects": ["science", "math"]}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        # Subjects come back in the canonical order, not the request's order.
        self.assertEqual(response.json(), {"grade": 5, "subjects": ["math", "science"]})
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_grade, 5)
        self.assertEqual(self.tank.quiz_subjects, ["math", "science"])

    def test_invalid_grade_is_rejected(self):
        self.client.force_login(self.owner)
        for grade in (0, 7, "x", None):
            with self.subTest(grade=grade):
                response = self.client.post(
                    self.url,
                    data=json.dumps({"grade": grade, "subjects": ["math"]}),
                    content_type="application/json",
                    HTTP_ACCEPT="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "invalid")

        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_grade, 3)

    def test_empty_or_unknown_subjects_are_rejected(self):
        self.client.force_login(self.owner)
        for subjects in ([], ["math", "lunch"], None):
            with self.subTest(subjects=subjects):
                response = self.client.post(
                    self.url,
                    data=json.dumps({"grade": 3, "subjects": subjects}),
                    content_type="application/json",
                    HTTP_ACCEPT="application/json",
                )
                self.assertEqual(response.status_code, 400)

    def test_subjects_are_deduplicated_in_canonical_order(self):
        self.client.force_login(self.owner)
        self.client.post(
            self.url,
            data=json.dumps({"grade": 2, "subjects": ["general", "math", "general"]}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_subjects, ["math", "general"])

    def test_members_cannot_change_the_settings(self):
        member = make_user()
        Tank.objects.get(pk=self.tank.pk).fish.create(owner=member, name="Splash")
        self.client.force_login(member)

        response = self.client.post(self.url, {"grade": 1, "subjects": ["math"]})

        self.assertEqual(response.status_code, 403)
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_grade, 3)

    def test_plain_form_post_redirects_with_messages(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            self.url, {"grade": "4", "subjects": ["spelling"]}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_grade, 4)
        self.assertEqual(self.tank.quiz_subjects, ["spelling"])
        self.assertContains(response, "Quiz settings saved")

    def test_invalid_plain_form_post_redirects_with_an_error(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {"grade": "9", "subjects": ["math"]}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Grade must be between 1 and 6")
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.quiz_grade, 3)

    def test_page_renders_the_quiz_form(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("game:tank_settings", args=[self.tank.pk]))

        self.assertContains(response, "quiz-grade")
        self.assertContains(response, "subjects")


@COOLDOWN_OVERRIDE
class TimedFeedStillAvailableTests(TestCase):
    """With QUIZ_ONLY_FEEDING off, the Phase 1 feed endpoint keeps working."""

    def test_timed_feed_returns_200(self):
        owner = make_user()
        tank, _fish = create_tank(owner, "Old Tank", "Nibble")
        self.client.force_login(owner)

        response = self.client.post(reverse("game:tank_feed", args=[tank.pk]))
        self.assertEqual(response.status_code, 200)


@QUIZ_ONLY
class QuizOnlyFeedingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Quiz Only", "Nibble")
        self.client.force_login(self.owner)

    def test_timed_feed_is_closed_off(self):
        response = self.client.post(reverse("game:tank_feed", args=[self.tank.pk]))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "quiz_required"})

    def test_quiz_feeding_still_works(self):
        attempt = make_attempt(self.owner, self.fish)
        result = answer_question(self.owner, attempt.pk, attempt.correct_index)

        self.assertIsNotNone(result.feed)
        self.fish.refresh_from_db()
        self.assertEqual(self.fish.xp, 10)

    def test_tank_page_has_the_quiz_dialog(self):
        response = self.client.get(reverse("game:tank_detail", args=[self.tank.pk]))

        for element_id in ("quiz-dialog", "quiz-choices", "quiz-result"):
            self.assertContains(response, f'id="{element_id}"')
        self.assertContains(response, reverse("game:tank_quiz_next", args=[self.tank.pk]))
        self.assertContains(response, reverse("game:tank_quiz_answer", args=[self.tank.pk]))
        # tank.js imports quiz.js, so the dialog module ships with the page.
        self.assertContains(response, "game/js/tank.js")


class QuizConcurrencyTests(TransactionTestCase):
    """Two simultaneous answers to one attempt must feed exactly once."""

    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Race Tank", "Nibble")
        self.attempt = make_attempt(self.owner, self.fish)

    def test_concurrent_answers_feed_once(self):
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=10)
                results.append(
                    answer_question(
                        self.owner, self.attempt.pk, self.attempt.correct_index
                    )
                )
            except Exception as exc:  # noqa: BLE001 - collected for the assertion
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.fish.refresh_from_db()
        self.assertEqual(self.fish.xp, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], AttemptAlreadyAnswered)
