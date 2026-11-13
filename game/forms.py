"""Forms for Phase 2: signup, tank creation and joining."""

from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import Fish, Tank
from .validators import validate_display_name

User = get_user_model()

TANK_NAME_MAX_LENGTH = Tank._meta.get_field("name").max_length
FISH_NAME_MAX_LENGTH = Fish._meta.get_field("name").max_length


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


class CreateTankForm(forms.Form):
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

    def clean_code(self):
        return (self.cleaned_data["code"] or "").strip().upper()

    def clean_fish_name(self):
        return _clean_name(
            self.cleaned_data["fish_name"],
            max_length=FISH_NAME_MAX_LENGTH,
            field_label="Fish name",
        )
