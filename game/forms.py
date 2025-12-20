from django import forms
from .models import Game, BoardTile

TILE_CHOICES = [
    (BoardTile.TileType.QUESTION, "Question"),
    (BoardTile.TileType.TRAP, "Trap"),
    (BoardTile.TileType.HEAL, "Heal"),
    (BoardTile.TileType.BONUS, "Bonus"),
    (BoardTile.TileType.WARP, "Warp"),
    (BoardTile.TileType.MASS_WARP, "Mass Warp"),
    (BoardTile.TileType.DUEL, "Duel"),
    (BoardTile.TileType.SHOP, "Shop"),
]

DEFAULT_TILES = [v for (v, _) in TILE_CHOICES]

class GameCreateForm(forms.ModelForm):
    enabled_tiles = forms.MultipleChoiceField(
        choices=TILE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        initial=DEFAULT_TILES,
        label="Tiles"
    )

    class Meta:
        model = Game
        fields = ("mode", "max_players", "board_length", "enabled_tiles")

    def clean_enabled_tiles(self):
        tiles = self.cleaned_data.get("enabled_tiles") or []
        # If user selects nothing, default to all (prevents empty choices)
        return tiles if tiles else DEFAULT_TILES

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.enabled_tiles = self.cleaned_data["enabled_tiles"]
        if commit:
            obj.save()
        return obj


class JoinGameForm(forms.Form):
    code = forms.CharField(
        max_length=8,
        label="Game code",
        widget=forms.TextInput(attrs={"placeholder": "Enter game code (e.g. ABC123)"}),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        return code
