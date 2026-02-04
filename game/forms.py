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
    (BoardTile.TileType.GUN, "Gun"),
]

DEFAULT_TILES = [v for (v, _) in TILE_CHOICES]


class GameCreateForm(forms.ModelForm):
    """
    Form for creating a new game.
    Allows configuring game mode, difficulty, board length, max players, and enabled tiles.
    """
    enabled_tiles = forms.MultipleChoiceField(
        choices=TILE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Tiles",
    )

    class Meta:
        model = Game
        fields = ("mode", "survival_difficulty", "board_length", "max_players", "enabled_tiles")

    def clean_enabled_tiles(self):
        """
        Validates the enabled tiles selection.
        If no tiles are selected, defaults to all available tiles.
        """
        tiles = self.cleaned_data.get("enabled_tiles") or []
        # fallback to all
        return tiles if tiles else [v for (v, _) in self.fields["enabled_tiles"].choices]
    
    def clean_board_length(self):
        """
        Validates board length constraints based on game mode.
        """
        mode = self.cleaned_data.get("mode") or Game.Mode.FINISH
        bl = int(self.cleaned_data.get("board_length") or 35)

        if mode in [Game.Mode.SURVIVAL, Game.Mode.DRAFT]:
            return 35  # force fixed length for these modes

        # Finish Line: allow configurable size
        if bl < 20 or bl > 80:
            raise forms.ValidationError("Board length must be between 20 and 80.")
        return bl
    
    def clean_max_players(self):
        """
        Validates max players constraints based on game mode.
        """
        mode = self.cleaned_data.get("mode") or Game.Mode.FINISH
        max_players = int(self.cleaned_data.get("max_players") or 4)
        
        # Card Duel mode: enforce exactly 2 players
        if mode == Game.Mode.CARD_DUEL:
            if max_players != 2:
                max_players = 2  # Force to 2 players
        
        # Custom game mode: enforce 2-4 players
        elif mode == Game.Mode.FINISH:
            if max_players < 2:
                raise forms.ValidationError("Custom game mode requires at least 2 players.")
            if max_players > 4:
                raise forms.ValidationError("Custom game mode allows maximum 4 players.")
        
        return max_players


    def save(self, commit=True):
        """
        Saves the form data to the Game model.
        Explicitly handles the enabled_tiles field.
        """
        obj = super().save(commit=False)
        obj.enabled_tiles = self.cleaned_data["enabled_tiles"]
        if commit:
            obj.save()
        return obj


class JoinGameForm(forms.Form):
    """
    Form for joining an existing game via code.
    """
    code = forms.CharField(
        max_length=8,
        label="Game code",
        widget=forms.TextInput(attrs={"placeholder": "Enter game code (e.g. ABC123)"}),
    )

    def clean_code(self):
        """
        Normalizes the game code to uppercase and strips whitespace.
        """
        code = self.cleaned_data["code"].strip().upper()
        return code
