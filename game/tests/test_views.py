"""View-level tests for Phase 2: auth, tank flows, authorization, rate limit."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from game.models import Tank
from game.services import create_tank

User = get_user_model()

PASSWORD = "pw-123456"
_user_counter = 0


def make_user():
    global _user_counter
    _user_counter += 1
    return User.objects.create_user(username=f"player{_user_counter}", password=PASSWORD)


class AuthRequiredTests(TestCase):
    def test_locked_pages_redirect_to_login(self):
        tank = Tank.objects.create(name="Someone Else's", owner=make_user())
        protected = [
            reverse("game:tank_list"),
            reverse("game:tank_create"),
            reverse("game:tank_join"),
            reverse("game:tank_detail", args=[tank.pk]),
        ]
        for url in protected:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])
                self.assertIn(url, response["Location"])

    def test_root_redirects_to_tank_list(self):
        response = self.client.get("/")
        # Anonymous visitors then bounce on to the login page, so don't follow.
        self.assertRedirects(
            response, reverse("game:tank_list"), fetch_redirect_response=False
        )


class SignupTests(TestCase):
    def test_signup_creates_and_logs_in_user(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "newplayer",
                "password1": "a-very-long-password-1",
                "password2": "a-very-long-password-1",
            },
        )
        self.assertRedirects(response, reverse("game:tank_list"))
        self.assertTrue(User.objects.filter(username="newplayer").exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]),
                         User.objects.get(username="newplayer").pk)


class TankListTests(TestCase):
    def test_lists_only_my_tanks(self):
        me = make_user()
        mine, _fish = create_tank(me, "My Reef", "Nibble")
        other, _other_fish = create_tank(make_user(), "Their Reef", "Bubbles")

        self.client.force_login(me)
        response = self.client.get(reverse("game:tank_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Reef")
        self.assertNotContains(response, "Their Reef")
        self.assertContains(response, "1 / %d fish" % mine.capacity)
        self.assertEqual(response.context["rows"][0]["tank"], mine)
        self.assertNotEqual(mine, other)


class TankCreateViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_get_renders_form(self):
        response = self.client.get(reverse("game:tank_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create a tank")

    def test_post_creates_tank_and_fish_then_redirects(self):
        response = self.client.post(
            reverse("game:tank_create"),
            {"tank_name": "Coral Reef", "fish_name": "Nibble"},
        )
        tank = Tank.objects.get(name="Coral Reef")
        self.assertRedirects(response, reverse("game:tank_detail", args=[tank.pk]))
        self.assertEqual(tank.owner, self.user)
        self.assertEqual(tank.fish.get().name, "Nibble")

    def test_post_rejects_html_name(self):
        response = self.client.post(
            reverse("game:tank_create"),
            {"tank_name": "<script>alert(1)</script>", "fish_name": "Nibble"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Tank.objects.exists())
        self.assertIn("tank_name", response.context["form"].errors)


class TankJoinViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, _owner_fish = create_tank(self.owner, "Coral Reef", "Nibble")
        self.joiner = make_user()
        self.client.force_login(self.joiner)

    def _join(self, code, fish_name="Bubbles"):
        return self.client.post(
            reverse("game:tank_join"), {"code": code, "fish_name": fish_name}
        )

    def test_join_with_code_redirects_and_creates_fish(self):
        response = self._join(self.tank.join_code)
        self.assertRedirects(
            response, reverse("game:tank_detail", args=[self.tank.pk])
        )
        self.assertTrue(self.tank.fish.filter(owner=self.joiner).exists())

    def test_lowercase_padded_code_works(self):
        code = f"  {self.tank.join_code.lower()} "
        response = self._join(code)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.tank.fish.filter(owner=self.joiner).exists())

    def test_wrong_code_shows_generic_error(self):
        response = self._join("ZZZZZZ")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "doesn&#x27;t match a tank")
        self.assertEqual(self.tank.fish.count(), 1)

    def test_joining_twice_shows_error(self):
        self._join(self.tank.join_code)
        response = self._join(self.tank.join_code, fish_name="Second")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already have a fish")
        self.assertEqual(self.tank.fish.count(), 2)

    def test_full_tank_shows_friendly_error(self):
        self.tank.capacity = 1
        self.tank.save()
        response = self._join(self.tank.join_code)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "That tank is full")
        self.assertEqual(self.tank.fish.count(), 1)

    def test_invalid_fish_name_blocks_join(self):
        response = self._join(self.tank.join_code, fish_name="<b>")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.tank.fish.filter(owner=self.joiner).exists())


class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, _owner_fish = create_tank(self.owner, "Coral Reef", "Nibble")
        self.client.force_login(make_user())

    def _attempt(self):
        return self.client.post(
            reverse("game:tank_join"), {"code": "ZZZZZZ", "fish_name": "Bubbles"}
        )

    def test_eleventh_attempt_is_limited(self):
        limit = settings.GAME_SETTINGS["JOIN_RATE_LIMIT_ATTEMPTS"]
        for _ in range(limit):
            self.assertEqual(self._attempt().status_code, 200)

        response = self._attempt()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many tries", status_code=429)
        retry_after = int(response["Retry-After"])
        self.assertGreaterEqual(retry_after, 1)
        self.assertLessEqual(
            retry_after, settings.GAME_SETTINGS["JOIN_RATE_LIMIT_WINDOW_SECONDS"]
        )

    def test_successful_joins_count_towards_the_limit(self):
        limit = settings.GAME_SETTINGS["JOIN_RATE_LIMIT_ATTEMPTS"]
        for _ in range(limit):
            self.client.post(
                reverse("game:tank_join"),
                {"code": self.tank.join_code, "fish_name": "Bubbles"},
            )
        self.assertEqual(self._attempt().status_code, 429)

    def test_counter_resets_when_the_window_expires(self):
        limit = settings.GAME_SETTINGS["JOIN_RATE_LIMIT_ATTEMPTS"]
        for _ in range(limit):
            self._attempt()
        self.assertEqual(self._attempt().status_code, 429)

        # Clearing the cache is the test double for the window's TTL expiring.
        cache.clear()
        self.assertEqual(self._attempt().status_code, 200)

    def test_get_page_is_not_counted(self):
        limit = settings.GAME_SETTINGS["JOIN_RATE_LIMIT_ATTEMPTS"]
        for _ in range(limit + 1):
            response = self.client.get(reverse("game:tank_join"))
            self.assertEqual(response.status_code, 200)


class TankDetailAuthorizationTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, _owner_fish = create_tank(self.owner, "Coral Reef", "Nibble")
        self.member = make_user()
        self.tank.fish.create(owner=self.member, name="Bubbles")
        self.outsider = make_user()
        self.url = reverse("game:tank_detail", args=[self.tank.pk])

    def test_non_member_gets_404(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_owner_sees_join_code(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.tank.join_code)

    def test_member_sees_fish_but_not_join_code(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.tank.join_code)
        self.assertContains(response, "Nibble")
        self.assertContains(response, "Bubbles")

    def test_stub_has_canvas_placeholder(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertContains(response, 'id="tank-canvas"')
        self.assertContains(response, f'data-tank-id="{self.tank.pk}"')
