"""Tests for the Phase 2 tank services: create, join, membership."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from game.models import Fish, Tank
from game.services import (
    AlreadyInTank,
    InvalidJoinCode,
    TankFull,
    create_tank,
    get_membership,
    join_tank,
)

User = get_user_model()

_user_counter = 0


def make_user():
    global _user_counter
    _user_counter += 1
    return User.objects.create_user(username=f"player{_user_counter}", password="pw-123456")


class CreateTankTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_creates_tank_and_owner_fish(self):
        tank, fish = create_tank(self.user, "Coral Reef", "Nibble")

        self.assertEqual(tank.owner, self.user)
        self.assertEqual(tank.name, "Coral Reef")
        self.assertEqual(fish.owner, self.user)
        self.assertEqual(fish.tank, tank)
        self.assertEqual(fish.name, "Nibble")
        self.assertEqual(fish.level, 1)
        self.assertEqual(fish.stage, 0)
        self.assertEqual(fish.xp, 0)

    def test_capacity_and_join_code(self):
        tank, _fish = create_tank(self.user, "Coral Reef", "Nibble")
        self.assertEqual(tank.capacity, settings.GAME_SETTINGS["DEFAULT_TANK_CAPACITY"])
        self.assertEqual(len(tank.join_code), settings.GAME_SETTINGS["JOIN_CODE_LENGTH"])

    def test_owner_is_a_member(self):
        tank, fish = create_tank(self.user, "Coral Reef", "Nibble")
        self.assertEqual(get_membership(self.user, tank.pk), fish)

    def test_names_are_cleaned(self):
        tank, fish = create_tank(self.user, "  Coral   Reef ", "  Nibble  ")
        self.assertEqual(tank.name, "Coral Reef")
        self.assertEqual(fish.name, "Nibble")

    def test_invalid_tank_name_creates_nothing(self):
        with self.assertRaises(ValidationError):
            create_tank(self.user, "<script>", "Nibble")
        self.assertFalse(Tank.objects.exists())

    def test_invalid_fish_name_creates_nothing(self):
        with self.assertRaises(ValidationError):
            create_tank(self.user, "Coral Reef", "🐟")
        self.assertFalse(Tank.objects.exists())


class JoinTankTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, _owner_fish = create_tank(self.owner, "Coral Reef", "Nibble")
        self.joiner = make_user()

    def test_join_succeeds(self):
        tank, fish = join_tank(self.joiner, self.tank.join_code, "Bubbles")

        self.assertEqual(tank, self.tank)
        self.assertEqual(fish.owner, self.joiner)
        self.assertEqual(fish.tank, self.tank)
        self.assertEqual(fish.name, "Bubbles")
        self.assertEqual(self.tank.fish.count(), 2)

    def test_code_is_normalized(self):
        code = f"  {self.tank.join_code.lower()}  "
        tank, _fish = join_tank(self.joiner, code, "Bubbles")
        self.assertEqual(tank, self.tank)

    def test_wrong_code_raises(self):
        with self.assertRaises(InvalidJoinCode):
            join_tank(self.joiner, "ZZZZZZ", "Bubbles")
        self.assertEqual(self.tank.fish.count(), 1)

    def test_already_in_tank_raises(self):
        with self.assertRaises(AlreadyInTank):
            join_tank(self.owner, self.tank.join_code, "Second Fish")
        self.assertEqual(self.tank.fish.count(), 1)

    def test_full_tank_raises(self):
        self.tank.capacity = 1
        self.tank.save()

        with self.assertRaises(TankFull):
            join_tank(self.joiner, self.tank.join_code, "Bubbles")
        self.assertEqual(self.tank.fish.count(), 1)

    def test_join_with_invalid_fish_name_raises_and_adds_no_fish(self):
        with self.assertRaises(ValidationError):
            join_tank(self.joiner, self.tank.join_code, "<b>")
        self.assertEqual(self.tank.fish.count(), 1)

    def test_last_slot_is_evaluated_from_current_count(self):
        self.tank.capacity = 2
        self.tank.save()

        join_tank(self.joiner, self.tank.join_code, "Bubbles")
        third = make_user()

        with self.assertRaises(TankFull):
            join_tank(third, self.tank.join_code, "Splash")
        self.assertEqual(self.tank.fish.count(), 2)


class GetMembershipTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Coral Reef", "Nibble")

    def test_member_gets_their_fish(self):
        self.assertEqual(get_membership(self.owner, self.tank.pk), self.fish)

    def test_non_member_gets_none(self):
        self.assertIsNone(get_membership(make_user(), self.tank.pk))

    def test_unknown_tank_gets_none(self):
        self.assertIsNone(get_membership(self.owner, 999_999))

    def test_fish_from_another_tank_is_not_returned(self):
        other_tank, _other_fish = create_tank(self.owner, "Second Tank", "Bubbles")
        membership = get_membership(self.owner, other_tank.pk)
        self.assertEqual(membership.tank, other_tank)
        self.assertNotEqual(membership, self.fish)
        self.assertEqual(Fish.objects.filter(owner=self.owner).count(), 2)
