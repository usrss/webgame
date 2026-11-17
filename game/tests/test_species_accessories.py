"""Tests for Phase 9: species, evolution, pearls, accessories and wardrobe."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from game.models import (
    Accessory,
    Fish,
    FishEquipment,
    FishSpecies,
    PearlTransaction,
    PlayerProfile,
    SpeciesStageName,
    Tank,
    UserAccessory,
)
from game.seeding import ACCESSORIES_PATH, SPECIES_PATH, seed_content
from game.services import (
    AccessoryNotFound,
    AlreadyOwned,
    InvalidSlot,
    InvalidSpecies,
    NotEnoughPearls,
    NotForSale,
    NotOwned,
    award_pearls,
    buy_accessory,
    create_tank,
    equip,
    feed,
    get_profile,
    grant_evolution_gifts,
    join_tank,
)

User = get_user_model()
STATIC = Path(settings.BASE_DIR) / "game" / "static" / "game"
_user_counter = 0


def make_user():
    global _user_counter
    _user_counter += 1
    return User.objects.create_user(username=f"wardrobe{_user_counter}", password="pw-123456")


def make_fish(owner, species="goldfish", tank=None, name="Nibble"):
    if tank is None:
        tank = Tank.objects.create(name=f"Tank {Tank.objects.count() + 1}", owner=owner)
    return Fish.objects.create(
        owner=owner, tank=tank, name=name, species=get_species(species)
    )


def get_species(key):
    return FishSpecies.objects.get(key=key)


def xp_to_reach(level, from_level=1):
    step = settings.GAME_SETTINGS["XP_PER_LEVEL_STEP"]
    return sum(step * n for n in range(from_level, level))


class SeedingTests(TestCase):
    def test_fifteen_species_with_six_stage_names_each(self):
        self.assertEqual(FishSpecies.objects.count(), 15)
        self.assertEqual(SpeciesStageName.objects.count(), 90)
        for species in FishSpecies.objects.all():
            names = list(species.stage_names.order_by("stage_number"))
            self.assertEqual(len(names), 6, species.key)
            self.assertEqual([row.stage_number for row in names], list(range(6)))
            self.assertEqual(len({row.name for row in names}), 6)
            for row in names:
                self.assertLessEqual(len(row.name), 14)

    def test_twenty_four_accessories_and_unlock_mix(self):
        self.assertEqual(Accessory.objects.count(), 24)
        for slot in ("head", "face", "body", "tail"):
            self.assertEqual(Accessory.objects.filter(slot=slot).count(), 6, slot)
        self.assertEqual(Accessory.objects.filter(unlock_type="starter").count(), 4)
        self.assertEqual(Accessory.objects.filter(unlock_type="evolution").count(), 5)
        self.assertEqual(Accessory.objects.filter(unlock_type="shop").count(), 15)
        for item in Accessory.objects.filter(unlock_type="shop"):
            self.assertGreater(item.price, 0)
        for item in Accessory.objects.exclude(unlock_type="shop"):
            self.assertEqual(item.price, 0)

    def test_seeding_twice_changes_nothing_and_keeps_inventory(self):
        owner = make_user()
        get_profile(owner)
        before = (FishSpecies.objects.count(), SpeciesStageName.objects.count(), Accessory.objects.count())
        inventory = set(owner.accessories.values_list("accessory__key", flat=True))

        seed_content()
        seed_content()

        self.assertEqual(
            (FishSpecies.objects.count(), SpeciesStageName.objects.count(), Accessory.objects.count()),
            before,
        )
        self.assertEqual(
            set(owner.accessories.values_list("accessory__key", flat=True)), inventory
        )

    def test_names_pass_the_project_name_filter_at_seed_time(self):
        data = json.loads(SPECIES_PATH.read_text(encoding="utf-8"))
        for entry in data:
            self.assertEqual(len(entry["stage_names"]), 6)
            for name in entry["stage_names"]:
                self.assertLessEqual(len(name), 14)
        accessories = json.loads(ACCESSORIES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(accessories), 24)

    def test_every_species_sheet_is_128x192(self):
        for species in FishSpecies.objects.all():
            path = STATIC / "sprites" / f"fish_{species.key}.png"
            with Image.open(path) as image:
                self.assertEqual(image.size, (128, 192), species.key)

    def test_anchors_cover_every_species_and_stage(self):
        anchors = json.loads((STATIC / "data" / "anchors.json").read_text(encoding="utf-8"))
        self.assertEqual(set(anchors), {species.key for species in FishSpecies.objects.all()})
        for key, stages in anchors.items():
            self.assertEqual(set(stages), {str(stage) for stage in range(6)}, key)
            for geometry in stages.values():
                for slot in ("head", "face", "body", "tail"):
                    self.assertEqual(len(geometry[slot]), 2)
                self.assertEqual(len(geometry["bbox"]), 2)

    def test_accessory_atlases_and_art_mapping(self):
        art = json.loads((STATIC / "data" / "accessories.json").read_text(encoding="utf-8"))
        self.assertEqual(set(art), set(Accessory.objects.values_list("key", flat=True)))
        for key, entry in art.items():
            self.assertIn("pivot", entry)
            self.assertIn("small", entry)
            self.assertIn(entry["layer"], {"front", "behind"})
            self.assertIn(entry["frames"], {1, 4}, key)
        with Image.open(STATIC / "sprites" / "accessories.png") as normal:
            self.assertEqual(normal.size, (96, 80))
        with Image.open(STATIC / "sprites" / "accessories_small.png") as small:
            self.assertEqual(small.size, (48, 40))

    def test_sprite_pixels_are_palette_only_and_opaque(self):
        palette = json.loads((STATIC / "palette.json").read_text(encoding="utf-8"))["colors"]
        allowed = {
            tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))
            for value in palette
        }
        for key in ("goldfish", "seahorse", "anglerfish"):
            with Image.open(STATIC / "sprites" / f"fish_{key}.png") as image:
                for pixel in image.getdata():
                    red, green, blue, alpha = pixel
                    self.assertIn(alpha, (0, 255))
                    if alpha:
                        self.assertIn((red, green, blue), allowed)


class SpeciesSelectionTests(TestCase):
    def test_create_and_join_store_the_chosen_species(self):
        owner = make_user()
        tank, fish = create_tank(owner, "Reef", "Nemo", "clownfish")
        self.assertEqual(fish.species.key, "clownfish")

        joiner = make_user()
        _tank, joined = join_tank(joiner, tank.join_code, "Bubbles", "seahorse")
        self.assertEqual(joined.species.key, "seahorse")

    def test_invalid_and_inactive_species_are_rejected(self):
        owner = make_user()
        with self.assertRaises(InvalidSpecies):
            create_tank(owner, "Reef", "Nibble", "nope")
        # An absent key is the legacy default, which stays goldfish.
        _tank, fish = create_tank(owner, "Reef", "Nibble", None)
        self.assertEqual(fish.species.key, "goldfish")

        betta = get_species("betta")
        betta.active = False
        betta.save(update_fields=["active"])
        with self.assertRaises(InvalidSpecies):
            create_tank(owner, "Reef", "Nibble", "betta")

    def test_fish_created_without_a_species_defaults_to_goldfish(self):
        owner = make_user()
        tank = Tank.objects.create(name="Legacy", owner=owner)
        fish = Fish.objects.create(owner=owner, tank=tank, name="Old Fish")
        self.assertEqual(fish.species.key, "goldfish")


class PearlTests(TestCase):
    def setUp(self):
        self.owner = make_user()

    def test_new_profile_has_zero_pearls_and_four_starters(self):
        profile = get_profile(self.owner)
        self.assertEqual(profile.pearls, 0)
        keys = set(self.owner.accessories.values_list("accessory__key", flat=True))
        self.assertEqual(
            keys, {"party_hat", "round_glasses", "red_bow_tie", "tail_ribbon"}
        )
        self.assertEqual(get_profile(self.owner).pk, profile.pk)

    def test_each_feed_awards_pearls_and_writes_one_transaction(self):
        fish = make_fish(self.owner)
        result = feed(fish, now=timezone.now())

        profile = PlayerProfile.objects.get(user=self.owner)
        self.assertEqual(result.pearls_gained, 1)
        self.assertEqual(profile.pearls, 1)
        transactions = PearlTransaction.objects.filter(user=self.owner)
        self.assertEqual(transactions.count(), 1)
        self.assertEqual(transactions.get().reason, "feed")

    def test_evolving_feed_adds_the_bonus_and_grants_the_gift(self):
        fish = make_fish(self.owner)
        fish.level = 9
        fish.xp = xp_to_reach(10, 9) - 1
        fish.save(update_fields=["level", "xp"])

        result = feed(fish, now=timezone.now())

        self.assertTrue(result.evolved)
        self.assertEqual(result.pearls_gained, 26)
        self.assertEqual([gift.key for gift in result.gifts], ["sailor_cap"])
        self.assertTrue(
            UserAccessory.objects.filter(user=self.owner, accessory__key="sailor_cap").exists()
        )
        reasons = list(
            PearlTransaction.objects.filter(user=self.owner).values_list("reason", flat=True)
        )
        self.assertCountEqual(reasons, ["feed", "evolution"])

    def test_balance_can_never_go_negative(self):
        get_profile(self.owner)
        with self.assertRaises(NotEnoughPearls):
            award_pearls(self.owner, -1, "test")
        self.assertEqual(PlayerProfile.objects.get(user=self.owner).pearls, 0)

    def test_max_level_feed_still_awards_pearls(self):
        fish = make_fish(self.owner)
        fish.level = settings.GAME_SETTINGS["MAX_LEVEL"]
        fish.stage = 5
        fish.save(update_fields=["level", "stage"])

        result = feed(fish, now=timezone.now())
        self.assertEqual(result.xp_gained, 0)
        self.assertEqual(result.pearls_gained, 1)


class GiftingTests(TestCase):
    def test_gifts_are_granted_once_per_account_across_fish(self):
        owner = make_user()
        first = make_fish(owner, name="One")
        second = make_fish(owner, name="Two")

        self.assertEqual([g.key for g in grant_evolution_gifts(owner, 2)], ["sailor_cap", "superhero_cape"])
        self.assertEqual(grant_evolution_gifts(owner, 2), [])
        self.assertEqual([g.key for g in grant_evolution_gifts(owner, 4)], ["star_shades", "sparkle_trail"])

        # A second fish reaching the same stage does not duplicate anything.
        self.assertEqual(grant_evolution_gifts(owner, 4), [])


class BuyingTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        award_pearls(self.owner, 100, "test")

    def test_buying_deducts_price_and_records_it(self):
        owned = buy_accessory(self.owner, "flower")

        self.assertEqual(owned.accessory.key, "flower")
        self.assertEqual(PlayerProfile.objects.get(user=self.owner).pearls, 90)
        self.assertTrue(
            PearlTransaction.objects.filter(
                user=self.owner, amount=-10, reason="purchase"
            ).exists()
        )

    def test_cannot_buy_twice_without_pearls_or_non_shop_items(self):
        buy_accessory(self.owner, "flower")
        with self.assertRaises(AlreadyOwned):
            buy_accessory(self.owner, "flower")
        with self.assertRaises(NotForSale):
            buy_accessory(self.owner, "party_hat")
        with self.assertRaises(NotForSale):
            buy_accessory(self.owner, "golden_crown")
        with self.assertRaises(NotForSale):
            buy_accessory(self.owner, "does_not_exist")

    def test_insufficient_pearls_does_not_change_the_balance(self):
        award_pearls(self.owner, -60, "test")  # 40 left
        with self.assertRaises(NotEnoughPearls) as caught:
            buy_accessory(self.owner, "rainbow_goggles")
        self.assertEqual(caught.exception.missing, 20)
        self.assertEqual(PlayerProfile.objects.get(user=self.owner).pearls, 40)


class BuyingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        award_pearls(self.owner, 100, "test")

    def test_concurrent_double_buy_charges_once(self):
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=10)
                results.append(buy_accessory(self.owner, "flower"))
            except Exception as exc:  # noqa: BLE001 - collected for the assertion
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], AlreadyOwned)
        self.assertEqual(PlayerProfile.objects.get(user=self.owner).pearls, 90)
        self.assertEqual(
            UserAccessory.objects.filter(user=self.owner, accessory__key="flower").count(), 1
        )
        self.assertEqual(
            PearlTransaction.objects.filter(user=self.owner, reason="purchase").count(), 1
        )


class EquippingTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        award_pearls(self.owner, 40, "test")
        self.fish = make_fish(self.owner)

    def test_equip_requires_ownership_and_a_matching_slot(self):
        with self.assertRaises(NotOwned):
            equip(self.owner, self.fish, "head", "wizard_hat")
        with self.assertRaises(InvalidSlot):
            equip(self.owner, self.fish, "body", "party_hat")
        with self.assertRaises(InvalidSlot):
            equip(self.owner, self.fish, "hat", "party_hat")
        with self.assertRaises(AccessoryNotFound):
            equip(self.owner, self.fish, "head", "missing_item")

    def test_equipping_replaces_the_slot_and_can_unequip(self):
        buy_accessory(self.owner, "top_hat")
        equip(self.owner, self.fish, "head", "party_hat")
        equip(self.owner, self.fish, "head", "top_hat")
        self.assertEqual(
            FishEquipment.objects.get(fish=self.fish, slot="head").accessory.key, "top_hat"
        )

        equip(self.owner, self.fish, "head", None)
        self.assertFalse(FishEquipment.objects.filter(fish=self.fish, slot="head").exists())

    def test_cannot_equip_on_someone_elses_fish(self):
        other = make_user()
        get_profile(other)
        their_fish = make_fish(other)
        with self.assertRaises(PermissionDenied):
            equip(self.owner, their_fish, "head", "party_hat")

    def test_same_owned_item_can_be_on_several_of_my_fish(self):
        second = make_fish(self.owner, name="Splash")
        equip(self.owner, self.fish, "head", "party_hat")
        equip(self.owner, second, "head", "party_hat")
        self.assertEqual(
            FishEquipment.objects.filter(accessory__key="party_hat").count(), 2
        )


class SpeciesPickerAndDebugTests(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.client.force_login(self.owner)

    def test_create_form_lists_all_fifteen_species_with_sprites(self):
        response = self.client.get(reverse("game:tank_create"))
        html = response.content.decode()

        self.assertEqual(html.count('name="species"'), 15)
        self.assertContains(response, 'value="goldfish"')
        self.assertContains(response, 'value="seahorse"')
        self.assertContains(response, "game/sprites/fish_goldfish.png")
        self.assertContains(response, "A round orange fish")

    def test_join_form_also_has_the_picker(self):
        response = self.client.get(reverse("game:tank_join"))
        self.assertEqual(response.content.decode().count('name="species"'), 15)

    def test_creating_with_a_species_stores_it(self):
        response = self.client.post(
            reverse("game:tank_create"),
            {"species": "seahorse", "tank_name": "Picker Reef", "fish_name": "Curl"},
        )
        self.assertEqual(response.status_code, 302)
        fish = Fish.objects.get(owner=self.owner)
        self.assertEqual(fish.species.key, "seahorse")

    def test_bad_species_is_a_form_error(self):
        response = self.client.post(
            reverse("game:tank_create"),
            {"species": "dragon", "tank_name": "Picker Reef", "fish_name": "Curl"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "available fish species")
        self.assertFalse(Fish.objects.filter(owner=self.owner).exists())

    def test_tank_page_has_the_wardrobe_button_and_dialog(self):
        tank, _fish = create_tank(self.owner, "Wardrobe Reef", "Nibble")
        response = self.client.get(reverse("game:tank_detail", args=[tank.pk]))

        for element_id in ("wardrobe-button", "wardrobe-dialog", "wardrobe-preview"):
            self.assertContains(response, f'id="{element_id}"')
        self.assertContains(response, reverse("game:wardrobe_state", args=[tank.pk]))
        self.assertContains(response, reverse("game:wardrobe_buy"))

    def test_art_debug_page_is_staff_only(self):
        url = reverse("game:art_debug")
        self.assertEqual(self.client.get(url).status_code, 302)

        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "art-grid")


class WardrobeEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.tank, self.fish = create_tank(self.owner, "Reef", "Nemo", "clownfish")
        get_profile(self.owner)
        self.client.force_login(self.owner)
        self.state_url = reverse("game:wardrobe_state", args=[self.tank.pk])
        self.equip_url = reverse("game:wardrobe_equip", args=[self.tank.pk])
        self.buy_url = reverse("game:wardrobe_buy")

    def post_json(self, url, payload):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

    def test_state_returns_my_fish_and_the_catalog(self):
        response = self.client.get(self.state_url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["species"], "clownfish")
        self.assertEqual(payload["stage"], 0)
        self.assertEqual(payload["stage_name"], "Clown Egg")
        self.assertEqual(payload["pearls"], 0)
        self.assertEqual(len(payload["catalog"]), 24)
        self.assertEqual(len(payload["stage_names"]), 6)
        self.assertEqual(
            payload["equipped"], {"head": None, "face": None, "body": None, "tail": None}
        )
        flower = next(item for item in payload["catalog"] if item["key"] == "flower")
        self.assertTrue(flower["owned"] is False)
        self.assertEqual(flower["locked_reason"], "not_enough_pearls")
        crown = next(item for item in payload["catalog"] if item["key"] == "golden_crown")
        self.assertEqual(crown["locked_reason"], "reach_stage")

    def test_equip_and_unequip_round_trip(self):
        response = self.post_json(self.equip_url, {"slot": "head", "accessory_key": "party_hat"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["equipped"]["head"], "party_hat")

        state = self.client.get(self.state_url).json()
        self.assertEqual(state["equipped"]["head"], "party_hat")

        response = self.post_json(self.equip_url, {"slot": "head", "accessory_key": None})
        self.assertEqual(response.json()["equipped"]["head"], None)

    def test_equip_errors(self):
        response = self.post_json(self.equip_url, {"slot": "body", "accessory_key": "party_hat"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_slot")

        response = self.post_json(self.equip_url, {"slot": "head", "accessory_key": "wizard_hat"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "not_owned")

    def test_buying_through_the_endpoint(self):
        award_pearls(self.owner, 15, "test")
        response = self.post_json(self.buy_url, {"accessory_key": "flower"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pearls"], 5)
        self.assertTrue(
            UserAccessory.objects.filter(user=self.owner, accessory__key="flower").exists()
        )

    def test_buy_endpoint_errors(self):
        response = self.post_json(self.buy_url, {"accessory_key": "flower"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "not_enough_pearls")

        response = self.post_json(self.buy_url, {"accessory_key": "party_hat"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "not_for_sale")

    def test_permissions(self):
        stranger = make_user()
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.state_url).status_code, 404)
        self.assertEqual(
            self.post_json(self.equip_url, {"slot": "head", "accessory_key": None}).status_code,
            404,
        )

        self.client.logout()
        self.assertEqual(self.client.get(self.state_url).status_code, 302)

    def test_equip_is_rate_limited(self):
        limit = settings.GAME_SETTINGS["WARDROBE_RATE_LIMIT_ATTEMPTS"]
        for _ in range(limit):
            self.assertEqual(
                self.post_json(
                    self.equip_url, {"slot": "head", "accessory_key": "party_hat"}
                ).status_code,
                200,
            )
        response = self.post_json(
            self.equip_url, {"slot": "head", "accessory_key": "party_hat"}
        )
        self.assertEqual(response.status_code, 429)

    def test_state_does_not_expose_unanswered_answers_or_other_inventory(self):
        member = make_user()
        get_profile(member)
        Fish.objects.create(owner=member, tank=self.tank, name="Splash")
        equip(member, Fish.objects.get(owner=member, tank=self.tank), "head", "party_hat")

        payload = self.client.get(self.state_url).json()
        self.assertEqual(payload["equipped"]["head"], None)
        self.assertNotIn("correct_index", payload)
        self.assertNotIn("accessories", payload)
