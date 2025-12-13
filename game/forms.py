from django import forms
from .models import Game


class GameCreateForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ("mode", "max_players", "board_length")
        widgets = {
            "mode": forms.Select(),
            "max_players": forms.NumberInput(attrs={"min": 2, "max": 4}),
            "board_length": forms.NumberInput(attrs={"min": 10, "max": 100}),
        }


class JoinGameForm(forms.Form):
    code = forms.CharField(
        max_length=8,
        label="Game code",
        widget=forms.TextInput(attrs={"placeholder": "Enter game code (e.g. ABC123)"}),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        return code
