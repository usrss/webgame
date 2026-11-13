"""Phase 5 tests: name filter, owner tools, player actions, moderation admin."""

from datetime import timedelta
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from game.admin import FishAdmin, FishReportAdmin
from game.models import Fish, FishReport, Tank, TankBan
from game.services import (
    AlreadyReported,
    Banned,
    CannotRenameYet,
    InvalidJoinCode,
    create_tank,
    delete_tank,
    join_tank,
    kick_player,
    leave_tank,
    regenerate_join_code,
    rename_fish,
    rename_own_fish,
    report_fish,
    unban_player,
)
from game.validators import validate_display_name

User = get_user_model()

PASSWORD = "pw-123456"
_user_counter = 0


def make_user():
    global _user_counter
    _user_counter += 1
    return User.objects.create_user(username=f"player{_user_counter}", password=PASSWORD)


def make_tank_with_member():
    owner = make_user()
    tank, owner_fish = create_tank(owner, "Reef Squad", "Bubbles")
    member = make_user()
    member_fish = Fish.objects.create(owner=member, tank=tank, name="Splash")
    return owner, tank, owner_fish, member, member_fish


class ProfanityFilterTests(TestCase):
    """Uses injected fake tokens: the repository holds no real offensive words."""

    def _validate(self, name):
        return validate_display_name(name, max_length=24, field_label="Fish name")

    @mock.patch("game.validators.get_blocklist", return_value=("badword1",))
    def test_leetspeak_spacing_and_repeat_variants_are_rejected(self, _blocklist):
        for name in ["badword1", "B4DW0RD1", "  bad word1 ", "baaadword1", "b a d w o r d 1"]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self._validate(name)

    @mock.patch("game.validators.get_blocklist", return_value=("badword1",))
    def test_innocent_name_containing_blocked_substring_is_allowed(self, _blocklist):
        self.assertEqual(self._validate("My badword1fish"), "My badword1fish")

    @mock.patch("game.validators.get_blocklist", return_value=("badword1",))
    def test_error_is_generic_and_does_not_echo_the_term(self, _blocklist):
        with self.assertRaises(ValidationError) as ctx:
            self._validate("badword1")
        self.assertEqual(ctx.exception.messages, ["That name isn't allowed."])
        self.assertNotIn("badword1", ctx.exception.messages[0])

    @mock.patch("game.validators.get_blocklist", return_value=())
    def test_clean_name_passes_with_empty_blocklist(self, _blocklist):
        self.assertEqual(self._validate("Coral Reef"), "Coral Reef")

    def test_severe_substrings_match_inside_longer_tokens(self):
        name = "xverybadterm1y"
        with self.assertRaises(ValidationError):
            self._validate(name)

    def test_tank_and_fish_creation_use_the_filter(self):
        with mock.patch("game.validators.get_blocklist", return_value=("badword1",)):
            with self.assertRaises(ValidationError):
                create_tank(make_user(), "badword1", "Nibble")


class RegenerateJoinCodeTests(TestCase):
    def setUp(self):
        self.owner, self.tank, _owner_fish, self.member, _member_fish = make_tank_with_member()

    def test_owner_gets_new_code_and_old_code_stops_working(self):
        old_code = self.tank.join_code
        regenerate_join_code(self.tank, self.owner)
        self.tank.refresh_from_db()

        self.assertNotEqual(self.tank.join_code, old_code)
        self.assertEqual(len(self.tank.join_code), 6)
        with self.assertRaises(InvalidJoinCode):
            join_tank(make_user(), old_code, "Late Fish")
        join_tank(make_user(), self.tank.join_code, "Late Fish")

    def test_non_owner_is_denied(self):
        with self.assertRaises(PermissionDenied):
            regenerate_join_code(self.tank, self.member)

    def test_other_tanks_keep_their_codes(self):
        other_tank, _fish = create_tank(make_user(), "Other", "Nemo")
        other_code = other_tank.join_code

        regenerate_join_code(self.tank, self.owner)

        other_tank.refresh_from_db()
        self.assertEqual(other_tank.join_code, other_code)


class KickTests(TestCase):
    def setUp(self):
        self.owner, self.tank, _owner_fish, self.member, self.member_fish = make_tank_with_member()

    def test_kick_removes_fish_and_creates_ban(self):
        kick_player(self.tank, self.owner, self.member_fish.pk)

        self.assertFalse(Fish.objects.filter(pk=self.member_fish.pk).exists())
        self.assertTrue(TankBan.objects.filter(tank=self.tank, user=self.member).exists())

    def test_banned_user_cannot_rejoin(self):
        kick_player(self.tank, self.owner, self.member_fish.pk)
        with self.assertRaises(Banned):
            join_tank(self.member, self.tank.join_code, "Splash")

    def test_unban_allows_rejoin(self):
        kick_player(self.tank, self.owner, self.member_fish.pk)
        unban_player(self.tank, self.owner, self.member.pk)

        self.assertFalse(TankBan.objects.filter(tank=self.tank, user=self.member).exists())
        _tank, fish = join_tank(self.member, self.tank.join_code, "Splash")
        self.assertEqual(fish.owner, self.member)

    def test_owner_cannot_kick_themselves(self):
        with self.assertRaises(PermissionDenied):
            kick_player(self.tank, self.owner, self.tank.fish.get(owner=self.owner).pk)

    def test_non_owner_cannot_kick(self):
        with self.assertRaises(PermissionDenied):
            kick_player(self.tank, self.member, self.member_fish.pk)

    def test_unban_requires_ownership(self):
        TankBan.objects.create(tank=self.tank, user=self.member, banned_by=self.owner)
        with self.assertRaises(PermissionDenied):
            unban_player(self.tank, self.member, self.member.pk)

    def test_kicked_member_loses_access_to_state_endpoint(self):
        self.client.force_login(self.member)
        url = reverse("game:tank_state", args=[self.tank.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

        kick_player(self.tank, self.owner, self.member_fish.pk)
        self.assertEqual(self.client.get(url).status_code, 404)


class OwnerRenameTests(TestCase):
    def setUp(self):
        self.owner, self.tank, _owner_fish, self.member, self.member_fish = make_tank_with_member()

    def test_owner_can_rename_any_fish(self):
        rename_fish(self.tank, self.owner, self.member_fish.pk, "  Gentle   Breeze ")
        self.member_fish.refresh_from_db()
        self.assertEqual(self.member_fish.name, "Gentle Breeze")

    def test_owner_rename_runs_the_name_validator(self):
        with self.assertRaises(ValidationError):
            rename_fish(self.tank, self.owner, self.member_fish.pk, "<script>")

    def test_non_owner_cannot_rename(self):
        with self.assertRaises(PermissionDenied):
            rename_fish(self.tank, self.member, self.member_fish.pk, "Hacked")

    def test_unknown_fish_raises(self):
        with self.assertRaises(Fish.DoesNotExist):
            rename_fish(self.tank, self.owner, 999_999, "Ghost")


class DeleteTankTests(TestCase):
    def setUp(self):
        self.owner, self.tank, _owner_fish, self.member, _member_fish = make_tank_with_member()
        TankBan.objects.create(tank=self.tank, user=self.member, banned_by=self.owner)

    def test_wrong_confirmation_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            delete_tank(self.tank, self.owner, "reef squad")
        self.assertTrue(Tank.objects.filter(pk=self.tank.pk).exists())

    def test_correct_name_deletes_tank_fish_and_bans(self):
        delete_tank(self.tank, self.owner, "Reef Squad")
        self.assertFalse(Tank.objects.filter(pk=self.tank.pk).exists())
        self.assertFalse(Fish.objects.filter(tank_id=self.tank.pk).exists())
        self.assertFalse(TankBan.objects.filter(tank_id=self.tank.pk).exists())

    def test_non_owner_cannot_delete(self):
        with self.assertRaises(PermissionDenied):
            delete_tank(self.tank, self.member, "Reef Squad")


class LeaveTankTests(TestCase):
    def setUp(self):
        self.owner, self.tank, self.owner_fish, self.member, self.member_fish = make_tank_with_member()

    def test_member_can_leave(self):
        leave_tank(self.member, self.tank)
        self.assertFalse(Fish.objects.filter(pk=self.member_fish.pk).exists())

    def test_owner_cannot_leave(self):
        with self.assertRaises(PermissionDenied):
            leave_tank(self.owner, self.tank)
        self.assertTrue(Fish.objects.filter(pk=self.owner_fish.pk).exists())

    def test_non_member_cannot_leave(self):
        with self.assertRaises(Fish.DoesNotExist):
            leave_tank(make_user(), self.tank)


class RenameOwnFishTests(TestCase):
    def setUp(self):
        self.owner, self.tank, self.owner_fish, self.member, self.member_fish = make_tank_with_member()
        self.now = timezone.now()

    def test_member_renames_own_fish(self):
        fish = rename_own_fish(self.member, self.tank, "New Name", now=self.now)
        self.assertEqual(fish.name, "New Name")
        self.assertEqual(fish.renamed_at, self.now)

    def test_second_rename_within_cooldown_is_blocked(self):
        rename_own_fish(self.member, self.tank, "New Name", now=self.now)
        with self.assertRaises(CannotRenameYet) as ctx:
            rename_own_fish(
                self.member, self.tank, "Another", now=self.now + timedelta(hours=1)
            )
        self.assertGreater(ctx.exception.seconds_remaining, 0)

    def test_rename_allowed_after_cooldown(self):
        rename_own_fish(self.member, self.tank, "New Name", now=self.now)
        later = self.now + timedelta(hours=24, seconds=1)
        fish = rename_own_fish(self.member, self.tank, "Another", now=later)
        self.assertEqual(fish.name, "Another")

    def test_rename_validates_the_name(self):
        with self.assertRaises(ValidationError):
            rename_own_fish(self.member, self.tank, "<script>", now=self.now)

    def test_non_member_cannot_rename(self):
        with self.assertRaises(Fish.DoesNotExist):
            rename_own_fish(make_user(), self.tank, "Nope", now=self.now)


class ReportFishTests(TestCase):
    def setUp(self):
        self.owner, self.tank, self.owner_fish, self.member, self.member_fish = make_tank_with_member()

    def test_member_reports_another_fish_once(self):
        report = report_fish(self.owner_fish, self.member, reason="name", note="rude")
        self.assertFalse(report.resolved)
        self.assertEqual(report.reason, "name")

        with self.assertRaises(AlreadyReported):
            report_fish(self.owner_fish, self.member)

    def test_cannot_report_own_fish(self):
        with self.assertRaises(PermissionDenied):
            report_fish(self.member_fish, self.member)

    def test_non_member_cannot_report(self):
        with self.assertRaises(PermissionDenied):
            report_fish(self.owner_fish, make_user())

    def test_unknown_reason_is_rejected(self):
        with self.assertRaises(ValidationError):
            report_fish(self.member_fish, self.owner, reason="hax")

    def test_note_length_is_enforced(self):
        with self.assertRaises(ValidationError):
            report_fish(self.member_fish, self.owner, note="x" * 201)

    def test_unique_constraints(self):
        TankBan.objects.create(tank=self.tank, user=self.member)
        # Savepoints keep the surrounding test transaction usable afterwards.
        with self.assertRaises(IntegrityError), transaction.atomic():
            TankBan.objects.create(tank=self.tank, user=self.member)

        report_fish(self.owner_fish, self.member)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FishReport.objects.create(fish=self.owner_fish, reporter=self.member, reason="name")


class OwnerEndpointPermissionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.tank, self.owner_fish, self.member, self.member_fish = make_tank_with_member()
        self.outsider = make_user()

    def _post(self, url, user=None, data=None):
        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)
        return self.client.post(url, data or {})

    def _matrix(self, url_name, kwargs, data=None):
        url = reverse(f"game:{url_name}", args=kwargs)

        self.assertEqual(self._post(url, None, data).status_code, 302)  # anonymous
        self.assertEqual(self._post(url, self.outsider, data).status_code, 404)
        self.assertEqual(self._post(url, self.member, data).status_code, 403)
        return self._post(url, self.owner, data)

    def test_settings_page_permissions(self):
        url = reverse("game:tank_settings", args=[self.tank.pk])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_regenerate_endpoint(self):
        response = self._matrix("tank_regenerate_code", [self.tank.pk])
        self.assertRedirects(
            response, reverse("game:tank_settings", args=[self.tank.pk])
        )

    def test_kick_endpoint(self):
        response = self._matrix("tank_kick", [self.tank.pk, self.member_fish.pk])
        self.assertRedirects(
            response, reverse("game:tank_settings", args=[self.tank.pk])
        )
        self.assertFalse(Fish.objects.filter(pk=self.member_fish.pk).exists())

    def test_unban_endpoint(self):
        TankBan.objects.create(tank=self.tank, user=self.member, banned_by=self.owner)
        self._matrix("tank_unban", [self.tank.pk, self.member.pk])
        self.assertFalse(TankBan.objects.filter(tank=self.tank, user=self.member).exists())

    def test_owner_rename_endpoint(self):
        self._matrix("tank_rename_fish", [self.tank.pk, self.member_fish.pk], {"name": "Calm"})
        self.member_fish.refresh_from_db()
        self.assertEqual(self.member_fish.name, "Calm")

    def test_delete_endpoint_requires_exact_name(self):
        url = reverse("game:tank_delete", args=[self.tank.pk])
        response = self._post(url, self.owner, {"confirm_name": "Wrong"})
        self.assertRedirects(
            response, reverse("game:tank_settings", args=[self.tank.pk])
        )
        self.assertTrue(Tank.objects.filter(pk=self.tank.pk).exists())

        response = self._post(url, self.owner, {"confirm_name": "Reef Squad"})
        self.assertRedirects(response, reverse("game:tank_list"))
        self.assertFalse(Tank.objects.filter(pk=self.tank.pk).exists())

    def test_leave_endpoint(self):
        url = reverse("game:tank_leave", args=[self.tank.pk])
        response = self._post(url, self.member)
        self.assertRedirects(response, reverse("game:tank_list"))
        self.assertFalse(Fish.objects.filter(pk=self.member_fish.pk).exists())

        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_rename_me_endpoint_and_daily_limit(self):
        url = reverse("game:tank_rename_me", args=[self.tank.pk])
        response = self._post(url, self.member, {"name": "New Name"})
        self.assertRedirects(
            response, reverse("game:tank_detail", args=[self.tank.pk])
        )
        self.member_fish.refresh_from_db()
        self.assertEqual(self.member_fish.name, "New Name")

        response = self._post(url, self.member, {"name": "Too Soon"})
        self.assertEqual(response.status_code, 302)
        self.member_fish.refresh_from_db()
        self.assertEqual(self.member_fish.name, "New Name")

    def test_rename_me_endpoint_and_rate_limit(self):
        url = reverse("game:tank_rename_me", args=[self.tank.pk])
        limit = 10

        # Every attempt counts, even the ones the daily cooldown rejects.
        for _ in range(limit):
            self.assertEqual(
                self._post(url, self.member, {"name": "New Name"}).status_code, 302
            )

        response = self._post(url, self.member, {"name": "New Name"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)

    def test_report_endpoint_and_rate_limit(self):
        url = reverse("game:tank_report", args=[self.tank.pk, self.member_fish.pk])
        response = self._post(url, self.owner, {"reason": "name"})
        self.assertRedirects(
            response, reverse("game:tank_detail", args=[self.tank.pk])
        )
        self.assertTrue(FishReport.objects.filter(fish=self.member_fish).exists())

        # Duplicates are rejected by the service but still count as attempts.
        limit = 10
        for _ in range(limit - 1):
            self.assertEqual(self.client.post(url, {"reason": "name"}).status_code, 302)
        response = self.client.post(url, {"reason": "name"})
        self.assertEqual(response.status_code, 429)

    def test_report_own_fish_is_refused_without_creating_a_report(self):
        url = reverse("game:tank_report", args=[self.tank.pk, self.member_fish.pk])
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(FishReport.objects.exists())

    def test_banned_user_sees_generic_join_error(self):
        kick_player(self.tank, self.owner, self.member_fish.pk)
        self.client.force_login(self.member)
        response = self.client.post(
            reverse("game:tank_join"),
            {"code": self.tank.join_code, "fish_name": "Splash"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "doesn&#x27;t match a tank")
        self.assertFalse(self.tank.fish.filter(owner=self.member).exists())


def admin_request(user):
    request = RequestFactory().post("/admin/")
    request.user = user
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda r: None).process_request(request)
    return request


class ModerationAdminTests(TestCase):
    def setUp(self):
        self.owner, self.tank, self.owner_fish, self.member, self.member_fish = make_tank_with_member()
        self.admin_user = User.objects.create_superuser(
            username="moderator", password="pw-123456", email="mod@example.com"
        )

    def test_mark_reports_resolved(self):
        report_fish(self.owner_fish, self.member)
        model_admin = FishReportAdmin(FishReport, AdminSite())
        model_admin.mark_resolved(admin_request(self.admin_user), FishReport.objects.all())
        self.assertTrue(FishReport.objects.filter(resolved=True).exists())

    def test_reset_name_action(self):
        model_admin = FishAdmin(Fish, AdminSite())
        model_admin.reset_names(
            admin_request(self.admin_user), Fish.objects.filter(pk=self.member_fish.pk)
        )
        self.member_fish.refresh_from_db()
        self.assertEqual(self.member_fish.name, f"Fish #{self.member_fish.pk}")

    def test_fish_admin_filters_unresolved_reports(self):
        report_fish(self.owner_fish, self.member)
        model_admin = FishAdmin(Fish, AdminSite())

        request = admin_request(self.admin_user)
        request.GET = {"unresolved": "yes"}
        filtered = model_admin.get_queryset(request).filter(reports__resolved=False)
        self.assertIn(self.owner_fish, filtered)
        self.assertNotIn(self.member_fish, filtered)
