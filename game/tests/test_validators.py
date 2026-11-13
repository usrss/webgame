"""Tests for the shared tank/fish name validator."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from game.validators import validate_display_name


def validate(value, max_length=40, label="Name"):
    return validate_display_name(value, max_length=max_length, field_label=label)


class ValidateDisplayNameTests(SimpleTestCase):
    def test_accepts_plain_name(self):
        self.assertEqual(validate("Coral Reef"), "Coral Reef")

    def test_accepts_digits_apostrophe_hyphen_underscore(self):
        self.assertEqual(validate("Nemo's Tank-2_a"), "Nemo's Tank-2_a")

    def test_trims_and_collapses_whitespace(self):
        self.assertEqual(validate("  Coral    Reef  "), "Coral Reef")

    def test_rejects_html(self):
        for value in ["<script>alert(1)</script>", "<b>bold</b>", "a<b"]:
            with self.assertRaises(ValidationError, msg=value):
                validate(value)

    def test_rejects_emoji(self):
        with self.assertRaises(ValidationError):
            validate("Fish 🐟")

    def test_rejects_control_characters(self):
        for value in ["two\nlines", "tab\there", "null\x00byte"]:
            with self.assertRaises(ValidationError, msg=repr(value)):
                validate(value)

    def test_rejects_too_short(self):
        with self.assertRaises(ValidationError):
            validate("A")
        with self.assertRaises(ValidationError):
            validate("")

    def test_rejects_only_spaces(self):
        with self.assertRaises(ValidationError):
            validate("     ")

    def test_rejects_too_long(self):
        with self.assertRaises(ValidationError):
            validate("x" * 41)
        validate("x" * 40)

    def test_respects_short_max_length_for_fish(self):
        self.assertEqual(validate("x" * 24, max_length=24), "x" * 24)
        with self.assertRaises(ValidationError):
            validate("x" * 25, max_length=24)

    def test_none_is_rejected_as_too_short(self):
        with self.assertRaises(ValidationError):
            validate(None)

    def test_error_message_uses_field_label(self):
        with self.assertRaises(ValidationError) as ctx:
            validate("<b>", label="Fish name")
        self.assertIn("Fish name", ctx.exception.messages[0])
