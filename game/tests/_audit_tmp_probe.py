"""Temporary audit probes. Deleted before the audit report is finished."""

import json
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from game import services
from game import views as game_views
from game.models import QuestionAttempt
from game.services import TankFull, create_tank, get_profile, join_tank
from game.quiz.services import issue_question

User = get_user_model()


class AuditProbe(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="audit_owner", password="pw-123456")
        self.member = User.objects.create_user(username="audit_member", password="pw-123456")
        self.stranger = User.objects.create_user(username="audit_stranger", password="pw-123456")
        self.tank, self.fish = create_tank(self.owner, "Audit Reef", "OwnerFish")
        create_tank(self.stranger, "Other Reef", "OtherFish")
        self.member_fish = self.fish.__class__.objects.create(
            owner=self.member, tank=self.tank, name="MemberFish"
        )
        get_profile(self.owner)
        self.client = Client(raise_request_exception=False)

    def post_json(self, url, payload):
        self.client.force_login(self.owner)
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

    def test_probe_malformed_json_types(self):
        cases = [
            ("wardrobe_buy", reverse("game:wardrobe_buy"), {"accessory_key": 123}),
            ("wardrobe_buy_dict", reverse("game:wardrobe_buy"), {"accessory_key": {"x": 1}}),
            (
                "wardrobe_equip_dict_slot",
                reverse("game:wardrobe_equip", args=[self.tank.pk]),
                {"slot": {"x": 1}, "accessory_key": "party_hat"},
            ),
            (
                "quiz_settings_subjects_int",
                reverse("game:tank_quiz_settings", args=[self.tank.pk]),
                {"grade": 3, "subjects": 5},
            ),
            (
                "quiz_answer_bad_types",
                reverse("game:tank_quiz_answer", args=[self.tank.pk]),
                {"attempt_id": "x", "selected_index": "0"},
            ),
        ]
        for label, url, payload in cases:
            response = self.post_json(url, payload)
            print(f"PROBE {label}: {response.status_code} {response.content[:120]!r}")

    def test_probe_settings_drift(self):
        config = dict(settings.GAME_SETTINGS)
        config["XP_PER_LEVEL_STEP"] = 10
        config["MAX_LEVEL"] = 75
        config["FEED_COOLDOWN_SECONDS"] = 1
        with override_settings(GAME_SETTINGS=config):
            print(
                "PROBE drift:",
                "xp_to_next_level(1)=", services.xp_to_next_level(1),
                "services._XP_PER_LEVEL_STEP=", services._XP_PER_LEVEL_STEP,
                "services._MAX_LEVEL=", services._MAX_LEVEL,
                "views.MAX_LEVEL=", game_views.MAX_LEVEL,
            )

    def test_probe_quiz_disabled(self):
        config = dict(settings.GAME_SETTINGS)
        config["QUIZ_ENABLED"] = False
        config["QUIZ_ONLY_FEEDING"] = True
        with override_settings(GAME_SETTINGS=config):
            self.client.force_login(self.owner)
            next_response = self.client.post(reverse("game:tank_quiz_next", args=[self.tank.pk]))
            print("PROBE quiz disabled next:", next_response.status_code, next_response.content[:160])
            if next_response.status_code == 200:
                data = next_response.json()
                attempt = QuestionAttempt.objects.get(pk=data["attempt_id"])
                answer = self.client.post(
                    reverse("game:tank_quiz_answer", args=[self.tank.pk]),
                    data=json.dumps(
                        {"attempt_id": attempt.pk, "selected_index": attempt.correct_index}
                    ),
                    content_type="application/json",
                    HTTP_ACCEPT="application/json",
                )
                print("PROBE quiz disabled answer:", answer.status_code, answer.content[:300])

    def test_probe_csrf_and_staff_debug(self):
        enforcing = Client(enforce_csrf_checks=True)
        enforcing.force_login(self.owner)
        for label, url in (
            ("quiz_next", reverse("game:tank_quiz_next", args=[self.tank.pk])),
            ("wardrobe_buy", reverse("game:wardrobe_buy")),
            ("quiz_settings", reverse("game:tank_quiz_settings", args=[self.tank.pk])),
        ):
            response = enforcing.post(url, data="{}", content_type="application/json")
            print(f"PROBE csrf {label}: {response.status_code}")

        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        staff_client = Client(raise_request_exception=False)
        staff_client.force_login(self.owner)
        response = staff_client.get(reverse("game:art_debug"))
        print("PROBE staff art_debug:", response.status_code)

    def test_probe_permissions_matrix(self):
        urls = [
            ("state", reverse("game:tank_state", args=[self.tank.pk])),
            ("feed", reverse("game:tank_feed", args=[self.tank.pk])),
            ("quiz_next", reverse("game:tank_quiz_next", args=[self.tank.pk])),
            ("quiz_answer", reverse("game:tank_quiz_answer", args=[self.tank.pk])),
            ("wardrobe_state", reverse("game:wardrobe_state", args=[self.tank.pk])),
            ("wardrobe_equip", reverse("game:wardrobe_equip", args=[self.tank.pk])),
            ("settings", reverse("game:tank_settings", args=[self.tank.pk])),
            ("detail", reverse("game:tank_detail", args=[self.tank.pk])),
            ("art_debug", reverse("game:art_debug")),
        ]
        for label, url in urls:
            statuses = {}
            for who, user in (("anon", None), ("owner", self.owner), ("member", self.member), ("stranger", self.stranger)):
                client = Client(raise_request_exception=False)
                if user is not None:
                    client.force_login(user)
                method = "get" if label in {"state", "wardrobe_state", "settings", "detail", "art_debug"} else "post"
                response = getattr(client, method)(url)
                statuses[who] = response.status_code
            print(f"PROBE perms {label}: {statuses}")


class AuditCapacityRaceProbe(TransactionTestCase):
    def test_probe_capacity_race(self):
        owner = User.objects.create_user(username="race_owner", password="pw-123456")
        tank, _fish = create_tank(owner, "Race Reef", "OwnerFish")
        tank.capacity = 2
        tank.save(update_fields=["capacity"])
        users = [
            User.objects.create_user(username=f"race_{i}", password="pw-123456")
            for i in range(2)
        ]
        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def worker(user):
            try:
                barrier.wait(timeout=10)
                join_tank(user, tank.join_code, f"Fish {user.pk}")
                outcomes.append("joined")
            except Exception as exc:  # noqa: BLE001
                errors.append(type(exc).__name__)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(user,)) for user in users]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        print("PROBE capacity race:", outcomes, errors, "count", tank.fish.count())
