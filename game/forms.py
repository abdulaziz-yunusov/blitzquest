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
        choices=[
            (BoardTile.TileType.QUESTION, "Question"),
            (BoardTile.TileType.TRAP, "Trap"),
            (BoardTile.TileType.HEAL, "Heal"),
            (BoardTile.TileType.BONUS, "Bonus"),
            (BoardTile.TileType.WARP, "Warp"),
            (BoardTile.TileType.MASS_WARP, "Mass Warp"),
            (BoardTile.TileType.DUEL, "Duel"),
            (BoardTile.TileType.SHOP, "Shop"),
        ],
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Tiles",
    )

    class Meta:
        model = Game
        fields = ("mode", "survival_difficulty", "board_length", "max_players", "enabled_tiles")

    def clean_enabled_tiles(self):
        tiles = self.cleaned_data.get("enabled_tiles") or []
        # fallback to all
        return tiles if tiles else [v for (v, _) in self.fields["enabled_tiles"].choices]
    
    def clean_board_length(self):
        mode = self.cleaned_data.get("mode") or Game.Mode.FINISH
        bl = int(self.cleaned_data.get("board_length") or 35)

        if mode == [Game.Mode.SURVIVAL, Game.Mode.DRAFT]:
            return 35  # force

        # Finish Line: allow configurable size
        if bl < 20 or bl > 80:
            raise forms.ValidationError("Board length must be between 20 and 80.")
        return bl


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
