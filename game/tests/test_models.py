"""Model-level tests for Phase 1: join codes, constraints, seeded stages."""

from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from game.models import (
    JOIN_CODE_ALPHABET,
    JOIN_CODE_MAX_ATTEMPTS,
    EvolutionStage,
    Fish,
    Tank,
    generate_join_code,
)

User = get_user_model()


def make_user(username="alice"):
    return User.objects.create_user(username=username, password="test-pass-123")


def make_tank(owner=None, name="Test Tank", **kwargs):
    owner = owner or make_user()
    return Tank.objects.create(name=name, owner=owner, **kwargs)


def make_fish(owner=None, tank=None, name="Nibble", **kwargs):
    owner = owner or make_user()
    tank = tank or make_tank(owner=owner)
    return Fish.objects.create(owner=owner, tank=tank, name=name, **kwargs)


class JoinCodeGenerationTests(TestCase):
    def test_code_has_length_from_settings(self):
        tank = make_tank()
        self.assertEqual(
            len(tank.join_code), settings.GAME_SETTINGS["JOIN_CODE_LENGTH"]
        )

    def test_alphabet_excludes_look_alike_characters(self):
        self.assertNotIn("O", JOIN_CODE_ALPHABET)
        self.assertNotIn("I", JOIN_CODE_ALPHABET)
        self.assertNotIn("0", JOIN_CODE_ALPHABET)
        self.assertNotIn("1", JOIN_CODE_ALPHABET)
        self.assertEqual(len(set(JOIN_CODE_ALPHABET)), len(JOIN_CODE_ALPHABET))

    def test_code_uses_allowed_characters_only(self):
        for _ in range(20):
            code = generate_join_code()
            self.assertTrue(set(code).issubset(set(JOIN_CODE_ALPHABET)))

    def test_codes_are_unique_across_many_tanks(self):
        owner = make_user()
        for index in range(20):
            Tank.objects.create(name=f"Tank {index}", owner=owner)

        codes = list(Tank.objects.values_list("join_code", flat=True))
        self.assertEqual(len(codes), len(set(codes)))

    def test_save_regenerates_code_on_collision(self):
        owner = make_user()
        taken = make_tank(owner, name="Occupied")

        with mock.patch(
            "game.models.generate_join_code",
            side_effect=[taken.join_code, "ZZZZZZ"],
        ):
            tank = Tank(name="New Tank", owner=owner, join_code=taken.join_code)
            tank.save()

        self.assertEqual(tank.join_code, "ZZZZZZ")
        self.assertEqual(Tank.objects.filter(join_code=taken.join_code).count(), 1)

    def test_save_raises_after_exhausting_attempts(self):
        owner = make_user()
        taken = make_tank(owner, name="Occupied")

        with mock.patch(
            "game.models.generate_join_code", return_value=taken.join_code
        ):
            with self.assertRaises(RuntimeError):
                Tank(name="Doomed", owner=owner, join_code=taken.join_code).save()

        self.assertEqual(Tank.objects.count(), 1)
        self.assertEqual(JOIN_CODE_MAX_ATTEMPTS, 10)

    def test_update_keeps_existing_join_code(self):
        tank = make_tank()
        code = tank.join_code
        tank.name = "Renamed"
        tank.save()
        tank.refresh_from_db()
        self.assertEqual(tank.join_code, code)

    def test_join_code_is_unique_at_database_level(self):
        first = make_tank(name="A")
        # bulk_create skips Tank.save, so this hits the database constraint.
        with self.assertRaises(IntegrityError):
            Tank.objects.bulk_create(
                [Tank(name="B", owner=first.owner, join_code=first.join_code)]
            )


class TankDefaultsTests(TestCase):
    def test_capacity_comes_from_game_settings(self):
        tank = make_tank()
        self.assertEqual(
            tank.capacity, settings.GAME_SETTINGS["DEFAULT_TANK_CAPACITY"]
        )

    def test_str_includes_name(self):
        tank = make_tank(name="Kelp Kingdom")
        self.assertIn("Kelp Kingdom", str(tank))


class FishUniqueConstraintTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.tank = make_tank(self.user)

    def test_same_user_cannot_own_two_fish_in_one_tank(self):
        Fish.objects.create(owner=self.user, tank=self.tank, name="Fish A")
        with self.assertRaises(IntegrityError):
            Fish.objects.create(owner=self.user, tank=self.tank, name="Fish B")

    def test_same_user_can_own_one_fish_per_tank(self):
        other_tank = make_tank(self.user, name="Other Tank")
        Fish.objects.create(owner=self.user, tank=self.tank, name="Fish A")
        Fish.objects.create(owner=self.user, tank=other_tank, name="Fish B")
        self.assertEqual(Fish.objects.filter(owner=self.user).count(), 2)

    def test_different_users_share_a_tank(self):
        other_user = make_user("bob")
        Fish.objects.create(owner=self.user, tank=self.tank, name="Fish A")
        Fish.objects.create(owner=other_user, tank=self.tank, name="Fish B")
        self.assertEqual(self.tank.fish.count(), 2)


class FishValidationTests(TestCase):
    def test_name_of_max_length_is_valid(self):
        fish = Fish(name="x" * 24)
        fish.clean()

    def test_name_longer_than_max_length_is_rejected(self):
        fish = Fish(name="x" * 25)
        with self.assertRaises(ValidationError):
            fish.clean()

    def test_str_includes_level_and_stage(self):
        fish = Fish(name="Nibble", level=3, stage=0)
        self.assertIn("Nibble", str(fish))


class EvolutionStageSeedingTests(TestCase):
    def test_six_stages_are_seeded(self):
        self.assertEqual(EvolutionStage.objects.count(), 6)

    def test_stage_rows_match_the_configured_thresholds(self):
        by_number = {
            stage.stage_number: (stage.min_level, stage.sprite_key)
            for stage in EvolutionStage.objects.all()
        }
        self.assertEqual(
            by_number,
            {
                0: (1, ""),
                1: (10, ""),
                2: (25, ""),
                3: (40, ""),
                4: (55, ""),
                5: (70, ""),
            },
        )

    def test_stage_names_are_unique(self):
        names = list(EvolutionStage.objects.values_list("name", flat=True))
        self.assertEqual(len(names), len(set(names)))
