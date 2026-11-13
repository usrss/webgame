"""Service-layer tests for Phase 1: XP, hunger, feeding, leveling, evolution."""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from game.models import Fish, Tank
from game.services import (
    FeedOnCooldown,
    feed,
    get_hunger,
    seconds_until_can_feed,
    stage_for_level,
    xp_to_next_level,
)

User = get_user_model()

T0 = datetime(2020, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
COOLDOWN = settings.GAME_SETTINGS["FEED_COOLDOWN_SECONDS"]
XP_PER_FEED = settings.GAME_SETTINGS["XP_PER_FEED"]
HUNGER_FULL_SECONDS = settings.GAME_SETTINGS["HUNGER_FULL_SECONDS"]
MAX_LEVEL = settings.GAME_SETTINGS["MAX_LEVEL"]

_user_counter = 0


def make_user():
    global _user_counter
    _user_counter += 1
    return User.objects.create_user(
        username=f"player{_user_counter}", password="test-pass-123"
    )


def make_fish(level=1, xp=0, stage=None, last_fed_at=None):
    owner = make_user()
    tank = Tank.objects.create(name="Tank", owner=owner)
    return Fish.objects.create(
        owner=owner,
        tank=tank,
        name="Nibble",
        xp=xp,
        level=level,
        stage=stage_for_level(level) if stage is None else stage,
        last_fed_at=last_fed_at,
    )


def xp_to_reach(level, from_level=1):
    """XP (within the current level) needed to climb from *from_level* to *level*."""
    return sum(xp_to_next_level(n) for n in range(from_level, level))


class XpToNextLevelTests(TestCase):
    def test_values_for_selected_levels(self):
        self.assertEqual(xp_to_next_level(1), 50)
        self.assertEqual(xp_to_next_level(2), 100)
        self.assertEqual(xp_to_next_level(10), 500)

    def test_uses_configured_step(self):
        self.assertEqual(
            xp_to_next_level(7),
            settings.GAME_SETTINGS["XP_PER_LEVEL_STEP"] * 7,
        )


class StageForLevelTests(TestCase):
    def test_stage_boundaries(self):
        expected = {1: 0, 4: 0, 5: 1, 14: 1, 15: 2, 29: 2, 30: 3, 50: 3}
        for level, stage in expected.items():
            self.assertEqual(stage_for_level(level), stage, f"level {level}")


class GetHungerTests(TestCase):
    def test_zero_right_after_feeding(self):
        fish = make_fish(last_fed_at=T0)
        self.assertEqual(get_hunger(fish, now=T0), 0)

    def test_fifty_at_half_interval(self):
        fish = make_fish(last_fed_at=T0)
        now = T0 + timedelta(seconds=HUNGER_FULL_SECONDS // 2)
        self.assertEqual(get_hunger(fish, now=now), 50)

    def test_capped_at_hundred(self):
        fish = make_fish(last_fed_at=T0)
        now = T0 + timedelta(seconds=HUNGER_FULL_SECONDS + 1)
        self.assertEqual(get_hunger(fish, now=now), 100)

    def test_uses_created_at_when_never_fed(self):
        fish = make_fish()
        Fish.objects.filter(pk=fish.pk).update(created_at=T0)
        fish.refresh_from_db()
        now = T0 + timedelta(seconds=HUNGER_FULL_SECONDS // 2)
        self.assertEqual(get_hunger(fish, now=now), 50)

    def test_never_negative_on_clock_skew(self):
        fish = make_fish(last_fed_at=T0)
        self.assertEqual(get_hunger(fish, now=T0 - timedelta(seconds=60)), 0)


class SecondsUntilCanFeedTests(TestCase):
    def test_never_fed_is_instant(self):
        self.assertEqual(seconds_until_can_feed(make_fish()), 0)

    def test_returns_remaining_within_cooldown(self):
        fish = make_fish(last_fed_at=T0 - timedelta(seconds=60))
        self.assertEqual(seconds_until_can_feed(fish, now=T0), COOLDOWN - 60)

    def test_returns_zero_after_cooldown(self):
        fish = make_fish(last_fed_at=T0 - timedelta(seconds=COOLDOWN))
        self.assertEqual(seconds_until_can_feed(fish, now=T0), 0)


class FeedTests(TestCase):
    def test_first_feed_succeeds(self):
        result = feed(make_fish(), now=T0)

        self.assertEqual(result.xp_gained, XP_PER_FEED)
        self.assertEqual(result.fish.xp, XP_PER_FEED)
        self.assertEqual(result.fish.level, 1)
        self.assertEqual(result.fish.stage, 0)
        self.assertFalse(result.leveled_up)
        self.assertFalse(result.evolved)
        self.assertEqual(result.levels_gained, 0)
        self.assertEqual(result.cooldown_seconds, COOLDOWN)
        self.assertEqual(result.fish.last_fed_at, T0)

    def test_feed_is_persisted(self):
        fish = make_fish()
        feed(fish, now=T0)
        fish.refresh_from_db()
        self.assertEqual(fish.xp, XP_PER_FEED)
        self.assertEqual(fish.last_fed_at, T0)

    def test_second_feed_within_cooldown_raises_with_remaining_seconds(self):
        fish = make_fish()
        feed(fish, now=T0)

        with self.assertRaises(FeedOnCooldown) as ctx:
            feed(fish, now=T0)
        self.assertEqual(ctx.exception.seconds_remaining, COOLDOWN)

        with self.assertRaises(FeedOnCooldown) as ctx:
            feed(fish, now=T0 + timedelta(seconds=120))
        self.assertEqual(ctx.exception.seconds_remaining, COOLDOWN - 120)

    def test_feed_after_cooldown_succeeds(self):
        fish = make_fish()
        feed(fish, now=T0)

        later = T0 + timedelta(seconds=COOLDOWN)
        result = feed(fish, now=later)
        self.assertEqual(result.xp_gained, XP_PER_FEED)
        self.assertEqual(result.fish.last_fed_at, later)

    def test_two_clients_racing_the_same_instant_only_first_succeeds(self):
        fish = make_fish()
        other_view = Fish.objects.get(pk=fish.pk)

        feed(fish, now=T0)
        with self.assertRaises(FeedOnCooldown):
            feed(other_view, now=T0)

        fish.refresh_from_db()
        self.assertEqual(fish.xp, XP_PER_FEED)

    def test_single_level_up_with_xp_carry_over(self):
        result = feed(make_fish(level=1, xp=xp_to_next_level(1) - 1), now=T0)

        self.assertTrue(result.leveled_up)
        self.assertEqual(result.levels_gained, 1)
        self.assertFalse(result.evolved)
        self.assertEqual(result.fish.level, 2)
        self.assertEqual(result.fish.xp, XP_PER_FEED - 1)

    def test_multiple_levels_chain_in_one_feed(self):
        # 140 XP at level 1: +10 reaches 150, which covers 50 (L1) + 100 (L2).
        result = feed(make_fish(level=1, xp=140), now=T0)

        self.assertEqual(result.fish.level, 3)
        self.assertEqual(result.fish.xp, 0)
        self.assertEqual(result.levels_gained, 2)
        self.assertTrue(result.leveled_up)
        self.assertEqual(result.xp_gained, XP_PER_FEED)

    def test_level_up_without_evolution(self):
        result = feed(make_fish(level=6, xp=xp_to_next_level(6) - 1), now=T0)

        self.assertEqual(result.fish.level, 7)
        self.assertEqual(result.fish.xp, XP_PER_FEED - 1)
        self.assertEqual(result.fish.stage, 1)
        self.assertTrue(result.leveled_up)
        self.assertFalse(result.evolved)


class EvolutionTests(TestCase):
    def test_crossing_level_5_evolves_to_juvenile(self):
        fish = make_fish(level=4, xp=xp_to_reach(5, 4) - 1)
        result = feed(fish, now=T0)

        self.assertEqual(result.fish.level, 5)
        self.assertEqual(result.fish.stage, 1)
        self.assertTrue(result.evolved)
        self.assertEqual((result.old_stage, result.new_stage), (0, 1))

    def test_crossing_level_15_evolves_to_adult(self):
        fish = make_fish(level=14, xp=xp_to_reach(15, 14) - 1)
        result = feed(fish, now=T0)

        self.assertEqual(result.fish.level, 15)
        self.assertEqual(result.fish.stage, 2)
        self.assertTrue(result.evolved)
        self.assertEqual((result.old_stage, result.new_stage), (1, 2))

    def test_crossing_level_30_evolves_to_elder(self):
        fish = make_fish(level=29, xp=xp_to_reach(30, 29) - 1)
        result = feed(fish, now=T0)

        self.assertEqual(result.fish.level, 30)
        self.assertEqual(result.fish.stage, 3)
        self.assertTrue(result.evolved)
        self.assertEqual((result.old_stage, result.new_stage), (2, 3))

    def test_leaping_a_stage_boundary_in_one_feed_reports_evolved(self):
        fish = make_fish(level=4, xp=xp_to_reach(15, 4) - 1)
        result = feed(fish, now=T0)

        self.assertEqual(result.fish.level, 15)
        self.assertEqual(result.fish.stage, 2)
        self.assertTrue(result.evolved)
        self.assertEqual((result.old_stage, result.new_stage), (0, 2))


class MaxLevelTests(TestCase):
    def test_level_never_exceeds_max_level(self):
        result = feed(
            make_fish(level=MAX_LEVEL - 1, xp=xp_to_next_level(MAX_LEVEL - 1) - 1),
            now=T0,
        )

        self.assertEqual(result.fish.level, MAX_LEVEL)
        self.assertEqual(result.levels_gained, 1)

    def test_max_level_feed_gains_no_xp_but_keeps_cooldown(self):
        result = feed(make_fish(level=MAX_LEVEL, xp=123, stage=3), now=T0)

        self.assertEqual(result.xp_gained, 0)
        self.assertEqual(result.fish.level, MAX_LEVEL)
        self.assertEqual(result.fish.xp, 123)
        self.assertFalse(result.leveled_up)
        self.assertFalse(result.evolved)
        self.assertEqual(result.fish.last_fed_at, T0)
        self.assertEqual(seconds_until_can_feed(result.fish, now=T0), COOLDOWN)
