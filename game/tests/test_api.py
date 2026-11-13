"""Tests for the Phase 3 JSON endpoints and the live tank page wiring."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from game.models import Fish
from game.services import create_tank, feed

User = get_user_model()

PASSWORD = "pw-123456"
_user_counter = 0


def make_user():
    global _user_counter
    _user_counter += 1
    return User.objects.create_user(username=f"player{_user_counter}", password=PASSWORD)


class StateEndpointTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Reef Squad", "Bubbles")
        self.url = reverse("game:tank_state", args=[self.tank.pk])

    def test_member_gets_state_schema(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["tank"],
            {"id": self.tank.pk, "name": "Reef Squad", "capacity": 12},
        )
        self.assertEqual(payload["me"], {"fish_id": self.fish.pk})
        self.assertTrue(payload["server_time"].endswith("Z"))

        entry = payload["fish"][0]
        self.assertEqual(
            set(entry),
            {
                "id",
                "name",
                "owner",
                "level",
                "stage",
                "stage_name",
                "sprite_key",
                "xp",
                "xp_needed",
                "hunger",
                "can_feed",
                "cooldown_remaining",
            },
        )
        self.assertEqual(entry["id"], self.fish.pk)
        self.assertEqual(entry["name"], "Bubbles")
        self.assertEqual(entry["owner"], self.owner.username)
        self.assertEqual(entry["level"], 1)
        self.assertEqual(entry["stage"], 0)
        self.assertEqual(entry["stage_name"], "Fry")
        self.assertEqual(entry["sprite_key"], "goldie_fry")
        self.assertEqual(entry["xp"], 0)
        self.assertEqual(entry["xp_needed"], 50)
        self.assertEqual(entry["hunger"], 0)
        self.assertIs(entry["can_feed"], True)
        self.assertEqual(entry["cooldown_remaining"], 0)

    def test_hunger_and_cooldown_come_from_services(self):
        feed(self.fish)
        self.client.force_login(self.owner)

        entry = self.client.get(self.url).json()["fish"][0]
        self.assertEqual(entry["hunger"], 0)
        self.assertIs(entry["can_feed"], False)
        self.assertGreater(entry["cooldown_remaining"], 0)
        self.assertLessEqual(entry["cooldown_remaining"], 300)

    def test_stage_metadata_follows_evolution(self):
        self.fish.level = 15
        self.fish.stage = 2
        self.fish.save()
        self.client.force_login(self.owner)

        entry = self.client.get(self.url).json()["fish"][0]
        self.assertEqual(entry["stage_name"], "Adult")
        self.assertEqual(entry["sprite_key"], "goldie_adult")

    def test_xp_needed_is_zero_at_max_level(self):
        self.fish.level = 50
        self.fish.xp = 0
        self.fish.stage = 3
        self.fish.save()
        self.client.force_login(self.owner)

        entry = self.client.get(self.url).json()["fish"][0]
        self.assertEqual(entry["xp_needed"], 0)

    def test_non_member_gets_404(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_response_is_not_cacheable(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_query_count_is_constant_as_fish_are_added(self):
        self.client.force_login(self.owner)

        with CaptureQueriesContext(connection) as baseline:
            self.client.get(self.url)

        for index in range(10):
            Fish.objects.create(
                owner=make_user(), tank=self.tank, name=f"Fish {index}"
            )

        with CaptureQueriesContext(connection) as with_many:
            response = self.client.get(self.url)

        self.assertEqual(len(response.json()["fish"]), 11)
        self.assertEqual(len(baseline), len(with_many))
        self.assertLessEqual(len(with_many), 5)


class FeedEndpointTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Reef Squad", "Bubbles")
        self.url = reverse("game:tank_feed", args=[self.tank.pk])
        self.client.force_login(self.owner)

    def test_feed_returns_updated_fish_and_persists(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["xp_gained"], 10)
        self.assertIs(payload["leveled_up"], False)
        self.assertIs(payload["evolved"], False)
        self.assertEqual(payload["old_stage"], 0)
        self.assertEqual(payload["new_stage"], 0)
        self.assertEqual(payload["fish"]["xp"], 10)
        self.assertIs(payload["fish"]["can_feed"], False)
        self.assertTrue(payload["server_time"].endswith("Z"))
        self.assertEqual(response["Cache-Control"], "no-store")

        self.fish.refresh_from_db()
        self.assertEqual(self.fish.xp, 10)
        self.assertIsNotNone(self.fish.last_fed_at)

    def test_level_up_and_evolution_flags(self):
        self.fish.level = 4
        self.fish.xp = 199
        self.fish.save()

        payload = self.client.post(self.url).json()
        self.assertIs(payload["evolved"], True)
        self.assertIs(payload["leveled_up"], True)
        self.assertEqual(payload["levels_gained"], 1)
        self.assertEqual(payload["old_stage"], 0)
        self.assertEqual(payload["new_stage"], 1)
        self.assertEqual(payload["fish"]["stage"], 1)
        self.assertEqual(payload["fish"]["stage_name"], "Juvenile")
        self.assertEqual(payload["fish"]["sprite_key"], "goldie_juvenile")

    def test_second_feed_within_cooldown_is_429(self):
        self.assertEqual(self.client.post(self.url).status_code, 200)

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 429)
        payload = response.json()
        self.assertEqual(payload["error"], "cooldown")
        self.assertGreater(payload["seconds_remaining"], 0)
        self.assertLessEqual(payload["seconds_remaining"], 300)

    def test_feeds_only_the_requesting_users_fish(self):
        member = make_user()
        member_fish = Fish.objects.create(owner=member, tank=self.tank, name="Splash")
        self.client.force_login(member)

        self.client.post(self.url)

        self.fish.refresh_from_db()
        member_fish.refresh_from_db()
        self.assertEqual(self.fish.xp, 0)
        self.assertEqual(member_fish.xp, 10)

    def test_get_is_method_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_non_member_gets_404(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_csrf_token_is_required(self):
        enforcing = Client(enforce_csrf_checks=True)
        enforcing.force_login(self.owner)

        self.assertEqual(enforcing.post(self.url).status_code, 403)

        # The page renders the token, which also sets the CSRF cookie.
        enforcing.get(reverse("game:tank_detail", args=[self.tank.pk]))
        token = enforcing.cookies["csrftoken"].value
        response = enforcing.post(self.url, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)


class TankPageWiringTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, _fish = create_tank(self.owner, "Reef Squad", "Bubbles")
        self.client.force_login(self.owner)

    def test_canvas_has_endpoint_wiring_and_internal_resolution(self):
        response = self.client.get(
            reverse("game:tank_detail", args=[self.tank.pk])
        )
        self.assertContains(response, 'width="320"')
        self.assertContains(response, 'height="180"')
        self.assertContains(
            response, reverse("game:tank_state", args=[self.tank.pk])
        )
        self.assertContains(
            response, reverse("game:tank_feed", args=[self.tank.pk])
        )
        self.assertContains(response, "game/js/tank.js")
        self.assertContains(response, 'name="csrf-token"')
        self.assertContains(response, "data-sprite-base")
        self.assertContains(response, "game/sprites/")

    def test_page_has_fish_panel_controls(self):
        response = self.client.get(
            reverse("game:tank_detail", args=[self.tank.pk])
        )
        for element_id in ("feed-button", "xp-bar", "hunger-bar", "fish-list"):
            self.assertContains(response, f'id="{element_id}"')
