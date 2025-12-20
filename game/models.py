import random as _r

from django.db import models, transaction
from django.contrib.auth import get_user_model
from django.db.models import Max
from .questions import generate_math_question


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

    enabled_tiles = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # When set, question is active and MUST be answered by for_player_id before turn advances
    pending_question = models.JSONField(null=True, blank=True)

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

    # ---------------------------
    # NEW: keep turn locked to pending question owner
    # ---------------------------
    def sync_turn_to_pending_question(self) -> bool:
        """
        If there is a pending question, ensure current_turn_index points to
        the player who must answer it.
        Returns True if changed.
        """
        pq = self.pending_question
        if not pq:
            return False

        pid = pq.get("for_player_id")
        if not pid:
            return False

        players = list(self.players_by_turn_order)
        if not players:
            return False

        for idx, p in enumerate(players):
            if p.id == pid:
                if self.current_turn_index != idx:
                    self.current_turn_index = idx
                    self.save(update_fields=["current_turn_index"])
                    return True
                return False

        return False

    def to_public_state(self, for_user=None):
        """
        JSON-serializable representation of the game state.
        """
        UserModel = get_user_model()

        # Ensure consistency: if question is pending, lock turn to that player
        # (safe + doesn't change game logic; just prevents drift)
        self.sync_turn_to_pending_question()

        # Players list
        players_qs = self.players.select_related("user").order_by("turn_order")
        players_list = list(players_qs)

        current = self.current_player

        # Determine `me` (PlayerInGame for the requesting user) early so
        # pending question reveal logic can reference it safely.
        me = None
        if for_user is not None and isinstance(for_user, UserModel):
            for p in players_list:
                if p.user_id == for_user.id:
                    me = p
                    break

        pending_payload = None
        pending_for_player_id = None
        pending_active = bool(self.pending_question)

        if self.pending_question:
            pending_for_player_id = self.pending_question.get("for_player_id")

            # Only reveal the question content to the player who must answer
            if me is not None and pending_for_player_id == me.id:
                pending_payload = {
                    "id": self.pending_question.get("id"),
                    "prompt": self.pending_question.get("prompt"),
                    "choices": self.pending_question.get("choices", []),
                    "changed_once": bool(self.pending_question.get("changed_once")),
                }

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
                    "label": tile.label,
                    "value_int": tile.value_int,
                    "config": tile.config or {},
                }
            )

        payload = {
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
            "pending_question": pending_payload,
            "pending_question_active": pending_active,
            "pending_question_for_player_id": pending_for_player_id,
        }

        # --- Support cards inventory ---
        if me is not None:
            payload["your_cards"] = [
                {
                    "id": c.id,
                    "name": c.card_type.name,
                    "code": c.card_type.code,
                    "description": c.card_type.description,
                    "effect_type": c.card_type.effect_type,
                    "params": c.card_type.params or {},
                    "is_used": c.is_used,
                }
                for c in me.cards.select_related("card_type").all()
                if not c.is_used
            ]
            payload["you_shield_points"] = getattr(me, "shield_points", 0)
            payload["you_extra_rolls"] = getattr(me, "extra_rolls", 0)

        if self.status == "finished" or self.winner_id is not None:
            payload["leaderboard"] = self.build_leaderboard()

        return payload

    def last_tile_index(self) -> int:
        max_pos = self.tiles.aggregate(max_pos=Max("position"))["max_pos"]
        if max_pos is not None:
            return max_pos

        if self.board_length and self.board_length > 0:
            return self.board_length - 1

        return 0

    def get_player_for_user(self, user):
        return self.players.select_related("user").get(user=user)

    def apply_basic_move(self, player, dice_value: int) -> dict:
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

        if landed_tile and landed_tile.tile_type == BoardTile.TileType.FINISH:
            self.status = Game.Status.FINISHED
            self.winner = player
            self.save(update_fields=["status", "winner"])
            won = True
        else:
            if landed_tile:
                tile_effect = self.execute_tile_effect(player, landed_tile)

        return {
            "from_position": from_pos,
            "to_position": player.position,
            "dice_value": dice_value,
            "won": won,
            "landed_tile_id": landed_tile.id if landed_tile else None,
            "landed_tile_type": landed_tile.tile_type if landed_tile else None,
            "tile_effect": tile_effect,
        }

    def execute_tile_effect(self, player, tile, *, ctx=None):
        t = tile.tile_type
        value = tile.value_int
        cfg = tile.config or {}
        if ctx is None:
            ctx = {}

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

        def clamp_position(pos: int) -> int:
            return max(0, min(pos, self.last_tile_index()))

        start_pos = player.position

        if t == BoardTile.TileType.SAFE or t == BoardTile.TileType.START:
            return effects

        if t == BoardTile.TileType.TRAP:
            hp_delta = value if value is not None else cfg.get("hp_delta", -1)
            if hp_delta == 0:
                hp_delta = -1
            if hp_delta > 0:
                hp_delta = -hp_delta

            damage = abs(int(hp_delta))
            self.apply_damage(player, damage, effects, source="trap")
            return effects

        if t == BoardTile.TileType.HEAL:
            hp_delta = value if value is not None else cfg.get("hp_delta", 1)
            if hp_delta == 0:
                hp_delta = 1

            player.hp += hp_delta
            effects["hp_delta"] = hp_delta

            player.save(update_fields=["hp"])
            return effects

        if t == BoardTile.TileType.BONUS:
            active_types = list(SupportCardType.objects.filter(is_active=True))
            if not active_types:
                effects["extra"]["no_cards_available"] = True
                return effects

            card_type = _r.choice(active_types)
            SupportCardInstance.objects.create(card_type=card_type, owner=player)

            effects["extra"]["granted_card"] = {
                "name": card_type.name,
                "code": card_type.code,
                "effect_type": card_type.effect_type,
                "params": card_type.params or {},
            }
            return effects

        # ---------- QUESTION ----------
        if t == BoardTile.TileType.QUESTION:
            # Pause the game and ask via UI. Do not auto-reward.
            if not self.pending_question:
                self.pending_question = { **generate_math_question(), "for_player_id": player.id }

                # lock turn to the same player who must answer
                players = list(self.players.order_by("turn_order"))
                for idx, p in enumerate(players):
                    if p.id == player.id:
                        self.current_turn_index = idx
                        break

                self.save(update_fields=["pending_question", "current_turn_index"])

            effects["extra"]["question_triggered"] = True
            return effects

        if t == BoardTile.TileType.WARP:
            board_size = int(effects["extra"].get("board_size") or 0)
            if not board_size:
                board_size = self.tiles.count() if hasattr(self, "tiles") else 50

            distance = _r.randint(1, 3)
            direction = _r.choice([-1, 1])
            delta = direction * distance

            new_pos = (start_pos + delta) % board_size

            player.position = new_pos
            player.save(update_fields=["position"])

            effects["position_delta"] = delta
            effects["position_set"] = new_pos
            effects["extra"].update({
                "warp": {
                    "range": [1, 3],
                    "direction": "forward" if direction == 1 else "back",
                    "distance": distance,
                    "from": start_pos,
                    "to": new_pos,
                }
            })
            return effects

        if t == BoardTile.TileType.MASS_WARP:
            if ctx.get("mass_warp_fired"):
                effects["extra"]["mass_warp"] = {"skipped": True, "reason": "mass_warp_already_fired"}
                effects["position_delta"] = 0
                effects["position_set"] = player.position
                return effects

            ctx["mass_warp_fired"] = True

            alive_players = list(self.players.filter(is_alive=True).order_by("id"))
            if len(alive_players) < 2:
                effects["extra"]["mass_warp"] = {"moved": [], "note": "Not enough alive players to swap."}
                effects["position_delta"] = 0
                effects["position_set"] = player.position
                return effects

            old_positions = [p.position for p in alive_players]
            new_positions = old_positions[:]
            for _ in range(10):
                _r.shuffle(new_positions)
                if any(a != b for a, b in zip(old_positions, new_positions)):
                    break

            moved = []
            with transaction.atomic():
                for p, old_pos, new_pos in zip(alive_players, old_positions, new_positions):
                    p.position = new_pos
                    moved.append({"player_id": p.id, "from": old_pos, "to": new_pos, "delta": new_pos - old_pos})
                type(alive_players[0]).objects.bulk_update(alive_players, ["position"])

            retriggered = []
            queue = alive_players[:]
            max_triggers = ctx.get("max_triggers", 50)
            triggers_used = 0

            while queue and triggers_used < max_triggers:
                p = queue.pop(0)
                landed_tile = self.tiles.filter(position=p.position).first()
                if not landed_tile:
                    continue

                if landed_tile.tile_type == BoardTile.TileType.MASS_WARP:
                    retriggered.append({"player_id": p.id, "tile": "MASS_WARP", "skipped": True})
                    continue

                triggers_used += 1
                sub = self.execute_tile_effect(p, landed_tile, ctx=ctx)

                retriggered.append({
                    "player_id": p.id,
                    "tile": landed_tile.tile_type,
                    "effects": sub.get("extra", sub),
                })

                if sub.get("position_set") is not None and sub["position_set"] != p.position:
                    queue.append(p)

            effects["extra"]["mass_warp"] = {
                "mode": "shuffle_positions",
                "moved": moved,
                "retriggered": retriggered,
                "triggers_used": triggers_used,
                "max_triggers": max_triggers,
            }
            effects["position_delta"] = 0
            effects["position_set"] = player.position
            return effects

        if t == BoardTile.TileType.DUEL:
            other_players = list(self.players.filter(is_alive=True).exclude(id=player.id))
            if not other_players:
                effects.setdefault("extra", {})
                effects["extra"]["no_opponent"] = True
                return effects

            opponent = _r.choice(other_players)

            cfg = cfg or {}
            reward_coins = int(cfg.get("reward_coins", 2) or 2)
            penalty_hp = int(cfg.get("penalty_hp", 1) or 1)
            if penalty_hp < 0:
                penalty_hp = abs(penalty_hp)

            effects.setdefault("extra", {})
            win = _r.choice([True, False])
            effects["extra"]["opponent_id"] = opponent.id
            effects["extra"]["won_duel"] = win

            if win:
                player.coins = int(player.coins or 0) + reward_coins
                player.save(update_fields=["coins"])
                effects["coins_delta"] = effects.get("coins_delta", 0) + reward_coins

                dmg_result = self.apply_damage(opponent, penalty_hp, effects, source="duel")
                if dmg_result.get("died"):
                    effects["extra"]["opponent_died"] = True

            else:
                dmg_result = self.apply_damage(player, penalty_hp, effects, source="duel")
                if dmg_result.get("died"):
                    effects["extra"]["died"] = True

            return effects

        if t == BoardTile.TileType.SHOP:
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

        if t == BoardTile.TileType.FINISH:
            return effects

        return effects

    def apply_damage(self, player, damage: int, effects: dict | None = None, *, source: str | None = None):
        dmg = max(0, int(damage or 0))
        if dmg == 0:
            return {"blocked": 0, "taken": 0, "died": False}

        shield = int(getattr(player, "shield_points", 0) or 0)
        blocked = min(shield, dmg)
        taken = dmg - blocked

        update_fields = []

        if blocked:
            player.shield_points = shield - blocked
            update_fields.append("shield_points")

        if taken:
            player.hp = max(0, int(player.hp) - taken)
            update_fields.append("hp")
            if player.hp == 0:
                player.is_alive = False
                update_fields.append("is_alive")

        if update_fields:
            player.save(update_fields=sorted(set(update_fields)))

        if effects is not None:
            effects["hp_delta"] = effects.get("hp_delta", 0) - taken
            extra = effects.setdefault("extra", {})
            if blocked:
                extra["shield_blocked"] = extra.get("shield_blocked", 0) + blocked
            if source:
                extra["damage_source"] = source

        return {"blocked": blocked, "taken": taken, "died": (taken > 0 and player.hp == 0)}

    def build_leaderboard(self):
        players_qs = self.players.select_related("user").all()

        ranked = sorted(
            players_qs,
            key=lambda p: (
                -int(p.position or 0),
                -int(p.coins or 0),
                -int(p.hp or 0),
            ),
        )

        leaderboard = []
        for idx, p in enumerate(ranked, start=1):
            if idx == 1 and self.winner_id:
                status = "Winner"
            else:
                status = "Alive" if getattr(p, "is_alive", True) else "Eliminated"

            leaderboard.append(
                {
                    "rank": idx,
                    "player_id": p.id,
                    "user_id": p.user_id,
                    "username": p.user.username,
                    "position": p.position,
                    "coins": p.coins,
                    "hp": p.hp,
                    "is_alive": p.is_alive,
                    "status": status,
                }
            )

        return leaderboard

    def advance_turn(self):
        players = list(self.players_by_turn_order)
        if not players:
            return None

        n = len(players)
        idx = self.current_turn_index

        for _ in range(n):
            idx = (idx + 1) % n
            candidate = players[idx]
            if candidate.is_alive:
                self.current_turn_index = idx
                self.save(update_fields=["current_turn_index"])
                return candidate

        self.status = Game.Status.FINISHED
        self.save(update_fields=["status"])
        return None

    def roll_and_apply_for(self, player):
        dice = _r.randint(1, 6)

        move_result = self.apply_basic_move(player, dice_value=dice)

        # If a question is pending, hard-lock turn to that player
        if self.pending_question:
            self.sync_turn_to_pending_question()

        # If player did not win, go to next player's turn
        if not move_result["won"] and not self.pending_question:
            if getattr(player, "extra_rolls", 0) > 0:
                player.extra_rolls -= 1
                player.save(update_fields=["extra_rolls"])
            else:
                self.advance_turn()

        next_player = self.current_player

        return {
            "dice": dice,
            "move": move_result,
            "next_player_id": next_player.id if next_player else None,
            "game_finished": self.status == Game.Status.FINISHED,
            "winner_player_id": self.winner_id,
        }

    def generate_random_board(self):
        length = max(self.board_length or 0, 8)
        if length != self.board_length:
            self.board_length = length
            self.save(update_fields=["board_length"])

        self.tiles.all().delete()

        TileModel = self.tiles.model
        TT = BoardTile.TileType

        TileModel.objects.create(
            game=self,
            position=0,
            tile_type=TT.START,
            label="Start",
            value_int=None,
            config={},
        )

        middle_positions = range(1, length - 1)

        default_pool = [
            TT.SAFE,
            TT.TRAP,
            TT.HEAL,
            TT.BONUS,
            TT.QUESTION,
            TT.WARP,
            TT.MASS_WARP,
            TT.DUEL,
            TT.SHOP,
        ]
        selected = [
            t for t in (self.enabled_tiles or [])
            if t not in (TT.START, TT.FINISH) and t in dict(TT.choices)
        ]
        if TT.SAFE not in selected:
            selected.append(TT.SAFE)

        tile_type_pool = selected or default_pool

        default_weights = {
            TT.SAFE: 0,
            TT.TRAP: 3,
            TT.HEAL: 3,
            TT.BONUS: 3,
            TT.QUESTION: 2,
            TT.WARP: 1,
            TT.MASS_WARP: 1,
            TT.DUEL: 1,
            TT.SHOP: 1,
        }
        tile_type_weights = [default_weights.get(t, 1) for t in tile_type_pool]

        for pos in middle_positions:
            t = _r.choices(tile_type_pool, weights=tile_type_weights, k=1)[0]

            label = ""
            value_int = None
            config = {}

            if t == TT.SAFE:
                label = ""
            elif t == TT.TRAP:
                hp_loss = _r.randint(1, 3)
                label = f"-{hp_loss} HP"
                value_int = -hp_loss
                config = {"hp_delta": -hp_loss}
            elif t == TT.HEAL:
                hp_gain = _r.randint(1, 3)
                label = f"+{hp_gain} HP"
                value_int = hp_gain
                config = {"hp_delta": hp_gain}
            elif t == TT.BONUS:
                coins = _r.randint(1, 5)
                label = f"+{coins} C"
                value_int = coins
                config = {"coins_delta": coins}
            elif t == TT.QUESTION:
                reward = _r.randint(1, 4)
                label = "?"
                value_int = reward
                config = {
                    "kind": "question",
                    "reward_coins": reward,
                }
            elif t == TT.WARP:
                offset = _r.choice([-3, -2, -1, 1, 2, 3])
                label = "Warp"
                value_int = offset
                config = {"warp_offset": offset}
            elif t == TT.MASS_WARP:
                target = _r.randint(1, length - 2)
                label = "Mass Warp"
                value_int = target
                config = {"warp_target": target, "affects": "all"}
            elif t == TT.DUEL:
                reward = _r.randint(1, 4)
                label = "Duel"
                value_int = reward
                config = {"kind": "duel", "reward_coins": reward, "penalty_hp": 1}
            elif t == TT.SHOP:
                label = "Shop"
                value_int = None
                config = {"shop_level": _r.randint(1, 3)}

            TileModel.objects.create(
                game=self,
                position=pos,
                tile_type=t,
                label=label,
                value_int=value_int,
                config=config,
            )

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

    turn_order = models.PositiveSmallIntegerField(
        help_text="Order of turns within the game (0-based).",
    )

    hp = models.PositiveSmallIntegerField(default=3)
    coins = models.PositiveIntegerField(default=0)
    position = models.PositiveSmallIntegerField(default=0)

    shield_points = models.PositiveSmallIntegerField(
        default=0,
        help_text="Blocks incoming damage (negative HP deltas) until depleted.",
    )
    extra_rolls = models.PositiveSmallIntegerField(
        default=0,
        help_text="Extra dice rolls available (from Reroll Dice card).",
    )

    is_alive = models.BooleanField(default=True)
    eliminated_at = models.DateTimeField(null=True, blank=True)

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

        WARP = "warp", "Warp"
        MASS_WARP = "mass_warp", "Mass Warp"

        DUEL = "duel", "Duel"
        SHOP = "shop", "Shop"

        SAFE = "safe", "Safe"

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
        default=TileType.SAFE,
    )

    label = models.CharField(
        max_length=64,
        blank=True,
        help_text="Short label to show on the board (optional)."
    )

    value_int = models.IntegerField(
        null=True,
        blank=True,
        help_text="Optional numeric value (HP change, coin change, move steps, warp index, etc.)."
    )

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
        BONUS_COIN = "bonus_coin", "Bonus coin"

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
