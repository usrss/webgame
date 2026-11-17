"""Forms for Phase 2: signup, tank creation and joining."""

from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import Fish, Tank
from .services import InvalidSpecies, get_species
from .validators import validate_display_name

User = get_user_model()

TANK_NAME_MAX_LENGTH = Tank._meta.get_field("name").max_length
FISH_NAME_MAX_LENGTH = Fish._meta.get_field("name").max_length


def _clean_species(value):
    """Validate an active species key, defaulting to goldfish when absent."""
    try:
        return get_species(value or "goldfish").key
    except InvalidSpecies as exc:
        raise forms.ValidationError(str(exc)) from exc


def _clean_name(value: str, *, max_length: int, field_label: str) -> str:
    """Run the shared display-name rules and surface errors on the field."""
    try:
        return validate_display_name(value, max_length=max_length, field_label=field_label)
    except ValidationError as exc:
        raise forms.ValidationError(exc.messages) from exc


class SignupForm(UserCreationForm):
    """Minimal account creation: username + password (Phase 0 gap)."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)


class QuizUploadForm(forms.Form):
    """Upload one custom quiz file (Phase 8).

    File type, size and content are checked by the importer service so every
    format shares one set of messages.
    """

    name = forms.CharField(
        max_length=60,
        label="Quiz name",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    file = forms.FileField(
        label="Quiz file",
        widget=forms.FileInput(attrs={"accept": ".csv,.xlsx,.txt,.docx"}),
    )


class CreateTankForm(forms.Form):
    species = forms.CharField(
        required=False,
        initial="goldfish",
        label="Fish species",
        widget=forms.HiddenInput(attrs={"id": "id_species"}),
    )
    tank_name = forms.CharField(
        max_length=TANK_NAME_MAX_LENGTH,
        label="Tank name",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    fish_name = forms.CharField(
        max_length=FISH_NAME_MAX_LENGTH,
        label="Your fish's name",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    def clean_species(self):
        return _clean_species(self.cleaned_data.get("species"))

    def clean_tank_name(self):
        return _clean_name(
            self.cleaned_data["tank_name"],
            max_length=TANK_NAME_MAX_LENGTH,
            field_label="Tank name",
        )

    def clean_fish_name(self):
        return _clean_name(
            self.cleaned_data["fish_name"],
            max_length=FISH_NAME_MAX_LENGTH,
            field_label="Fish name",
        )


class JoinTankForm(forms.Form):
    species = forms.CharField(
        required=False,
        initial="goldfish",
        label="Fish species",
        widget=forms.HiddenInput(attrs={"id": "id_species"}),
    )
    code = forms.CharField(
        max_length=settings.GAME_SETTINGS["JOIN_CODE_LENGTH"],
        label="Join code",
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "autocapitalize": "characters", "class": "join-code"}
        ),
    )
    fish_name = forms.CharField(
        max_length=FISH_NAME_MAX_LENGTH,
        label="Your fish's name",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    def clean_species(self):
        return _clean_species(self.cleaned_data.get("species"))

    def clean_code(self):
        return (self.cleaned_data["code"] or "").strip().upper()

    def clean_fish_name(self):
        return _clean_name(
            self.cleaned_data["fish_name"],
            max_length=FISH_NAME_MAX_LENGTH,
            field_label="Fish name",
        )
