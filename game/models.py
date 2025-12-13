import random

from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import Max


User = get_user_model()


class Game(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting for players"
        ACTIVE = "active", "Active"
        FINISHED = "finished", "Finished"

    class Mode(models.TextChoices):
        FINISH = "finish", "Finish Line"
        SURVIVAL = "survival", "Survival"

    code = models.CharField(
        max_length=8,
        unique=True,
        help_text="Short code to join the game (e.g. ABC123).",
    )
    host = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hosted_games",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.WAITING,
    )
    mode = models.CharField(
        max_length=16,
        choices=Mode.choices,
        default=Mode.FINISH,
    )
    max_players = models.PositiveSmallIntegerField(default=4)
    board_length = models.PositiveSmallIntegerField(
        default=50,
        help_text="Number of tiles on the board (including start/finish).",
    )

    # Turn handling: index in the sorted list of players_by_turn_order
    current_turn_index = models.PositiveSmallIntegerField(default=0)

    winner = models.ForeignKey(
        "PlayerInGame",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="won_games",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Game {self.code} ({self.get_status_display()})"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE
    @property
    def players_by_turn_order(self):
        """
        Shortcut: players in this game ordered by turn_order.
        Assumes PlayerInGame has FK game with related_name='players'.
        """
        return self.players.order_by("turn_order")

    @property
    def current_player(self):
        """
        Player whose turn it is, based on current_turn_index.
        Returns None if no players yet.
        """
        players = list(self.players_by_turn_order)
        if not players:
            return None

        index = self.current_turn_index % len(players)
        return players[index]

    def to_public_state(self, for_user=None):
        """
        JSON-serializable representation of the game state.
        """
        UserModel = get_user_model()

        # Players list
        players_qs = self.players.select_related("user").order_by("turn_order")
        players_list = list(players_qs)

        current = self.current_player

        me = None
        if for_user is not None and isinstance(for_user, UserModel):
            for p in players_list:
                if p.user_id == for_user.id:
                    me = p
                    break

        players_payload = []
        for p in players_list:
            players_payload.append(
                {
                    "id": p.id,
                    "user_id": p.user_id,
                    "username": p.user.username,
                    "turn_order": p.turn_order,
                    "hp": p.hp,
                    "coins": p.coins,
                    "position": p.position,
                    "is_alive": p.is_alive,
                    "is_you": (me is not None and p.id == me.id),
                    "is_current_turn": (current is not None and p.id == current.id),
                }
            )

        # Board tiles
        tiles_payload = []
        for tile in self.tiles.order_by("position"):
            tiles_payload.append(
                {
                    "id": tile.id,
                    "position": tile.position,
                    "type": tile.tile_type,
                    "type_display": tile.get_tile_type_display(),
                    "label": tile.label,          # NEW (your unified model)
                    "value_int": tile.value_int,  # NEW (replaces old 'value')
                    "config": tile.config or {},  # unchanged
                }
            )

        return {
            "id": self.id,
            "code": self.code,
            "mode": self.mode,
            "status": self.status,
            "max_players": self.max_players,
            "board_length": self.board_length,
            "current_turn_index": self.current_turn_index,
            "current_player_id": current.id if current else None,
            "winner_player_id": self.winner_id,
            "has_winner": self.winner_id is not None,
            "players": players_payload,
            "tiles": tiles_payload,
            "you_player_id": me.id if me is not None else None,
        }
    def last_tile_index(self) -> int:
        """
        Returns the index of the last tile on the board.
        Prefers actual tiles' max position; falls back to board_length - 1.
        """
        max_pos = self.tiles.aggregate(max_pos=Max("position"))["max_pos"]
        if max_pos is not None:
            return max_pos

        if self.board_length and self.board_length > 0:
            return self.board_length - 1

        # Very defensive fallback
        return 0

    def get_player_for_user(self, user):
        """
        Convenience helper to get PlayerInGame object for a given user.
        """
        return self.players.select_related("user").get(user=user)

    def apply_basic_move(self, player, dice_value: int) -> dict:
        """
        Move `player` forward by `dice_value` steps on this game’s board.
        Handles reaching the finish tile and setting winner.
        Also executes the landed tile's effect (TRAP, HEAL, BONUS, WARP, etc.).

        Returns a dict describing the movement result + tile effects.
        """
        from_pos = player.position
        last_index = self.last_tile_index()

        raw_target = from_pos + dice_value
        to_pos = min(raw_target, last_index)

        # Initial move
        player.position = to_pos
        player.save(update_fields=["position"])

        landed_tile = self.tiles.filter(position=to_pos).first()

        won = False
        tile_effect = None

        # If we landed on FINISH -> instant win, no extra tile effects
        if landed_tile and landed_tile.tile_type == BoardTile.TileType.FINISH:
            self.status = Game.Status.FINISHED
            self.winner = player
            self.save(update_fields=["status", "winner"])
            won = True
        else:
            # Execute tile effects (may modify player, positions, hp, coins, etc.)
            if landed_tile:
                tile_effect = self.execute_tile_effect(player, landed_tile)

        return {
            "from_position": from_pos,
            "to_position": player.position,  # may be modified by WARP/MASS_WARP
            "dice_value": dice_value,
            "won": won,
            "landed_tile_id": landed_tile.id if landed_tile else None,
            "landed_tile_type": landed_tile.tile_type if landed_tile else None,
            "tile_effect": tile_effect,
        }
    def execute_tile_effect(self, player, tile):
        """
        Apply the effect of `tile` to `player` (and sometimes other players).
        Uses:
          - tile.tile_type
          - tile.value_int
          - tile.config

        Returns a dict describing what happened (for frontend logs/UI).
        """
        t = tile.tile_type
        value = tile.value_int
        cfg = tile.config or {}

        effects = {
            "tile_type": t,
            "tile_label": tile.label,
            "hp_delta": 0,
            "coins_delta": 0,
            "position_delta": 0,
            "position_set": None,
            "mass_moved_player_ids": [],
            "extra": {},
        }

        # --- Helpers ---
        def clamp_position(pos: int) -> int:
            return max(0, min(pos, self.last_tile_index()))

        # Current baseline
        start_pos = player.position

        # ---------- EMPTY ----------
        if t == BoardTile.TileType.EMPTY or t == BoardTile.TileType.START:
            # No effect
            return effects

        # ---------- TRAP (HP -) ----------
        if t == BoardTile.TileType.TRAP:
            hp_delta = value if value is not None else cfg.get("hp_delta", -1)
            if hp_delta == 0:
                hp_delta = -1

            player.hp += hp_delta
            effects["hp_delta"] = hp_delta

            if player.hp <= 0:
                player.hp = 0
                player.is_alive = False
                effects["extra"]["died"] = True

            player.save(update_fields=["hp", "is_alive"])
            return effects

        # ---------- HEAL (HP +) ----------
        if t == BoardTile.TileType.HEAL:
            hp_delta = value if value is not None else cfg.get("hp_delta", 1)
            if hp_delta == 0:
                hp_delta = 1

            player.hp += hp_delta
            effects["hp_delta"] = hp_delta

            player.save(update_fields=["hp"])
            return effects

        # ---------- BONUS (coins +) ----------
        if t == BoardTile.TileType.BONUS:
            coins_delta = value if value is not None else cfg.get("coins_delta", 1)
            if coins_delta == 0:
                coins_delta = 1

            player.coins += coins_delta
            effects["coins_delta"] = coins_delta

            player.save(update_fields=["coins"])
            return effects

        # ---------- QUESTION ----------
        if t == BoardTile.TileType.QUESTION:
            # For now: auto-reward, no UI question yet.
            reward = value if value is not None else cfg.get("reward_coins", 2)
            if reward == 0:
                reward = 2

            player.coins += reward
            effects["coins_delta"] = reward
            effects["extra"]["auto_answered"] = True

            player.save(update_fields=["coins"])
            return effects

        # ---------- WARP (single player move) ----------
        if t == BoardTile.TileType.WARP:
            # value_int can be steps OR absolute target; default to relative move
            offset = cfg.get("warp_offset")
            if offset is None:
                # fallback: use value as offset; default 2
                offset = value if value is not None else 2
            try:
                offset = int(offset)
            except (TypeError, ValueError):
                offset = 2

            new_pos = clamp_position(start_pos + offset)
            player.position = new_pos
            player.save(update_fields=["position"])

            effects["position_delta"] = new_pos - start_pos
            effects["position_set"] = new_pos
            return effects

        # ---------- MASS_WARP (all players move) ----------
        if t == BoardTile.TileType.MASS_WARP:
            # Move all alive players to the same target position
            target = cfg.get("warp_target")
            if target is None:
                target = value if value is not None else self.last_tile_index() // 2

            try:
                target = int(target)
            except (TypeError, ValueError):
                target = self.last_tile_index() // 2

            target = clamp_position(target)

            moved_ids = []
            for p in self.players.filter(is_alive=True):
                p.position = target
                p.save(update_fields=["position"])
                moved_ids.append(p.id)

            effects["position_set"] = target
            effects["mass_moved_player_ids"] = moved_ids
            return effects

        # ---------- DUEL ----------
        if t == BoardTile.TileType.DUEL:
            # Simple logic: 50/50 win-lose against a random other alive player
            other_players = list(
                self.players.filter(is_alive=True).exclude(id=player.id)
            )
            if not other_players:
                # nobody to duel
                effects["extra"]["no_opponent"] = True
                return effects

            import random as _r
            opponent = _r.choice(other_players)

            reward_coins = cfg.get("reward_coins", 2)
            penalty_hp = cfg.get("penalty_hp", 1)

            win = _r.choice([True, False])
            effects["extra"]["opponent_id"] = opponent.id
            effects["extra"]["won_duel"] = win

            if win:
                # player gains coins, opponent loses some HP
                player.coins += reward_coins
                opponent.hp -= penalty_hp

                effects["coins_delta"] = reward_coins
                if opponent.hp <= 0:
                    opponent.hp = 0
                    opponent.is_alive = False
                    effects["extra"]["opponent_died"] = True

                player.save(update_fields=["coins"])
                opponent.save(update_fields=["hp", "is_alive"])
            else:
                # player loses HP
                player.hp -= penalty_hp
                effects["hp_delta"] = -penalty_hp

                if player.hp <= 0:
                    player.hp = 0
                    player.is_alive = False
                    effects["extra"]["died"] = True

                player.save(update_fields=["hp", "is_alive"])

            return effects

        # ---------- SHOP ----------
        if t == BoardTile.TileType.SHOP:
            # Very simple default: auto-buy HP if you have enough coins.
            # cost and hp_gain can be tuned via config.
            cost = cfg.get("cost", 2)
            hp_gain = cfg.get("hp_gain", 1)

            if player.coins >= cost:
                player.coins -= cost
                player.hp += hp_gain
                player.save(update_fields=["coins", "hp"])

                effects["coins_delta"] = -cost
                effects["hp_delta"] = hp_gain
                effects["extra"]["bought"] = True
            else:
                effects["extra"]["not_enough_coins"] = True

            return effects

        # ---------- FINISH ----------
        if t == BoardTile.TileType.FINISH:
            # Should already be handled before calling this, but just in case:
            return effects

        # Fallback: no effect
        return effects


    def advance_turn(self):
        """
        Move current_turn_index to the next *alive* player in turn order.
        If no alive players remain, mark game as finished.
        Returns the new current_player or None.
        """
        players = list(self.players_by_turn_order)
        if not players:
            return None

        n = len(players)
        idx = self.current_turn_index

        # Try at most n times to find next alive player
        for _ in range(n):
            idx = (idx + 1) % n
            candidate = players[idx]
            if candidate.is_alive:
                self.current_turn_index = idx
                self.save(update_fields=["current_turn_index"])
                return candidate

        # No alive players -> end game
        self.status = Game.Status.FINISHED
        self.save(update_fields=["status"])
        return None

    def roll_and_apply_for(self, player):
        """
        Full server-side action:
          - roll a d6
          - move the player
          - execute tile effect
          - if they did NOT win, advance to next player's turn
        """
        dice = random.randint(1, 6)

        move_result = self.apply_basic_move(player, dice_value=dice)

        # If player did not win, go to next player's turn
        if not move_result["won"]:
            self.advance_turn()

        next_player = self.current_player

        return {
            "dice": dice,
            "move": move_result,  # includes tile_effect as defined above
            "next_player_id": next_player.id if next_player else None,
            "game_finished": self.status == Game.Status.FINISHED,
            "winner_player_id": self.winner_id,
        }


    def generate_random_board(self):
        """
        Clears existing tiles and generates a fresh random linear board
        using the unified BoardTile model.

        Guarantees:
          - position 0           => START
          - position last        => FINISH
          - middle positions     => random tile types (QUESTION, TRAP, HEAL, BONUS, etc.)
        Uses self.board_length as total tiles (with a minimum).
        """
        # Ensure minimum length so the board is interesting
        length = max(self.board_length or 0, 8)
        if length != self.board_length:
            self.board_length = length
            self.save(update_fields=["board_length"])

        # Remove old tiles for this game
        self.tiles.all().delete()

        TileModel = self.tiles.model
        TT = TileModel.TileType

        # 1) START tile at position 0
        TileModel.objects.create(
            game=self,
            position=0,
            tile_type=TT.START,
            label="Start",
            value_int=None,
            config={},
        )

        # 2) Middle tiles (1 .. length-2)
        middle_positions = range(1, length - 1)

        # Pool of types for middle tiles
        tile_type_pool = [
            TT.EMPTY,
            TT.TRAP,
            TT.HEAL,
            TT.BONUS,
            TT.QUESTION,
            TT.WARP,
            TT.MASS_WARP,
            TT.DUEL,
            TT.SHOP,
        ]

        # Weights: how often each type should appear (tweak freely)
        tile_type_weights = [
            6,  # EMPTY      (most common)
            3,  # TRAP
            3,  # HEAL
            3,  # BONUS
            2,  # QUESTION
            1,  # WARP       (rare)
            1,  # MASS_WARP  (rare)
            1,  # DUEL       (rare)
            1,  # SHOP       (rare)
        ]

        for pos in middle_positions:
            t = random.choices(tile_type_pool, weights=tile_type_weights, k=1)[0]

            label = ""
            value_int = None
            config = {}

            if t == TT.EMPTY:
                label = ""
                # no effect
            elif t == TT.TRAP:
                hp_loss = random.randint(1, 3)
                label = f"-{hp_loss} HP"
                value_int = -hp_loss
                config = {"hp_delta": -hp_loss}
            elif t == TT.HEAL:
                hp_gain = random.randint(1, 3)
                label = f"+{hp_gain} HP"
                value_int = hp_gain
                config = {"hp_delta": hp_gain}
            elif t == TT.BONUS:
                coins = random.randint(1, 5)
                label = f"+{coins} C"
                value_int = coins
                config = {"coins_delta": coins}
            elif t == TT.QUESTION:
                reward = random.randint(1, 4)
                label = "?"
                value_int = reward
                config = {
                    "kind": "question",
                    "reward_coins": reward,
                    # later you can add question text & answers here
                }
            elif t == TT.WARP:
                # Relative move: -3..-1 or +1..+3
                offset = random.choice([-3, -2, -1, 1, 2, 3])
                label = "Warp"
                value_int = offset
                config = {
                    "warp_offset": offset,
                }
            elif t == TT.MASS_WARP:
                # All players move to the same random tile (not start/finish)
                target = random.randint(1, length - 2)
                label = "Mass Warp"
                value_int = target
                config = {
                    "warp_target": target,
                    "affects": "all",
                }
            elif t == TT.DUEL:
                reward = random.randint(1, 4)
                label = "Duel"
                value_int = reward
                config = {
                    "kind": "duel",
                    "reward_coins": reward,
                    "penalty_hp": 1,  # example default
                }
            elif t == TT.SHOP:
                label = "Shop"
                value_int = None
                config = {
                    "shop_level": random.randint(1, 3),
                    # you can add item list later here
                }

            TileModel.objects.create(
                game=self,
                position=pos,
                tile_type=t,
                label=label,
                value_int=value_int,
                config=config,
            )

        # 3) FINISH tile at last position
        TileModel.objects.create(
            game=self,
            position=length - 1,
            tile_type=TT.FINISH,
            label="Finish",
            value_int=None,
            config={},
        )



class PlayerInGame(models.Model):
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="players",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="game_players",
    )

    # 0–3 indicating turn order
    turn_order = models.PositiveSmallIntegerField(
        help_text="Order of turns within the game (0-based).",
    )

    hp = models.PositiveSmallIntegerField(default=3)
    coins = models.PositiveIntegerField(default=0)
    position = models.PositiveSmallIntegerField(default=0)

    is_alive = models.BooleanField(default=True)
    eliminated_at = models.DateTimeField(null=True, blank=True)

    # Convenience metadata
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("game", "user")
        ordering = ["game", "turn_order"]

    def __str__(self) -> str:
        return f"{self.user} in {self.game} (HP={self.hp}, pos={self.position})"


class BoardTile(models.Model):
    class TileType(models.TextChoices):
        START = "start", "Start"
        FINISH = "finish", "Finish"

        QUESTION = "question", "Question"
        TRAP = "trap", "Trap"
        HEAL = "heal", "Heal"
        BONUS = "bonus", "Bonus"

        WARP = "warp", "Warp"                 # single-player teleport or move
        MASS_WARP = "mass_warp", "Mass Warp"  # all players reposition

        DUEL = "duel", "Duel"                 # challenge another player
        SHOP = "shop", "Shop"                 # buy item (future expansion)

        EMPTY = "empty", "Empty"

    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="tiles",
    )

    position = models.PositiveSmallIntegerField(
        help_text="Zero-based index from start (0) to last tile."
    )

    tile_type = models.CharField(
        max_length=32,
        choices=TileType.choices,
        default=TileType.EMPTY,
    )

    # Optional readable label (useful for board UI)
    label = models.CharField(
        max_length=64,
        blank=True,
        help_text="Short label to show on the board (optional)."
    )

    # Generic numeric effect (HP change, coin change, movement steps, warp position, etc.)
    value_int = models.IntegerField(
        null=True,
        blank=True,
        help_text="Optional numeric value (HP change, coin change, move steps, warp index, etc.)."
    )

    # JSON config for tile-specific data (e.g., warp target, shop items, duel rules)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional JSON config for custom tile effects."
    )

    class Meta:
        unique_together = ("game", "position")
        ordering = ["game", "position"]

    def __str__(self) -> str:
        return f"Tile {self.position} ({self.get_tile_type_display()}) in {self.game.code}"



class Question(models.Model):
    DIFFICULTY_CHOICES = (
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    )

    text = models.TextField(
        help_text="Main question text or description of the kanji.",
    )
    kanji = models.CharField(
        max_length=16,
        blank=True,
        help_text="Optional kanji being tested.",
    )

    option_a = models.CharField(max_length=255)
    option_b = models.CharField(max_length=255)
    option_c = models.CharField(max_length=255)
    option_d = models.CharField(max_length=255)

    CORRECT_CHOICES = (
        ("A", "Option A"),
        ("B", "Option B"),
        ("C", "Option C"),
        ("D", "Option D"),
    )
    correct_option = models.CharField(
        max_length=1,
        choices=CORRECT_CHOICES,
    )

    difficulty = models.CharField(
        max_length=16,
        choices=DIFFICULTY_CHOICES,
        default="easy",
    )
    category = models.CharField(
        max_length=64,
        blank=True,
        help_text="Optional category/tag (e.g., JLPT level, topic).",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        base = self.kanji if self.kanji else self.text[:30]
        return f"Q#{self.id}: {base}"


class SupportCardType(models.Model):
    class EffectType(models.TextChoices):
        MOVE_EXTRA = "move_extra", "Move extra cells"
        HEAL = "heal", "Heal HP"
        SHIELD = "shield", "Damage shield"
        REROLL = "reroll", "Reroll dice"
        SWAP_POSITION = "swap_position", "Swap position with another player"
        CHANGE_QUESTION = "change_question", "Change question"
        CUSTOM = "custom", "Custom effect"

    name = models.CharField(max_length=64)
    code = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Short code identifier (e.g. skip_plus2).",
    )
    description = models.TextField(blank=True)

    effect_type = models.CharField(
        max_length=32,
        choices=EffectType.choices,
        default=EffectType.CUSTOM,
    )
    params = models.JSONField(
        default=dict,
        blank=True,
        help_text="Config for the effect (e.g., {'cells': 2, 'max_hp_gain': 1}).",
    )

    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class SupportCardInstance(models.Model):
    card_type = models.ForeignKey(
        SupportCardType,
        on_delete=models.CASCADE,
        related_name="instances",
    )
    owner = models.ForeignKey(
        PlayerInGame,
        on_delete=models.CASCADE,
        related_name="cards",
    )

    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["owner", "created_at"]

    def __str__(self) -> str:
        status = "used" if self.is_used else "in hand"
        return f"{self.card_type.name} ({status}) for {self.owner}"


class GameLog(models.Model):
    class ActionType(models.TextChoices):
        CREATE_GAME = "create_game", "Create Game"
        JOIN_GAME = "join_game", "Join Game"
        START_GAME = "start_game", "Start Game"
        ROLL_DICE = "roll_dice", "Roll Dice"
        MOVE = "move", "Move"
        TILE_EFFECT = "tile_effect", "Tile Effect"
        QUESTION_START = "question_start", "Question Start"
        QUESTION_ANSWER = "question_answer", "Question Answer"
        DUEL_START = "duel_start", "Duel Start"
        DUEL_RESULT = "duel_result", "Duel Result"
        CARD_USE = "card_use", "Use Card"
        PLAYER_ELIMINATED = "player_eliminated", "Player Eliminated"
        GAME_END = "game_end", "Game End"

    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    player = models.ForeignKey(
        PlayerInGame,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )

    action_type = models.CharField(
        max_length=32,
        choices=ActionType.choices,
    )
    message = models.TextField(blank=True)
    payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw event data (dice value, old/new positions, question id, etc.).",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        who = self.player or "System"
        return f"[{self.game.code}] {who}: {self.get_action_type_display()}"
