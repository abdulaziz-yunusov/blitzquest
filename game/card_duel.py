import random
from django.db import transaction

from .models import Game, PlayerInGame, CardDuelCardType
from .card_duel_seed import seed_card_duel_cards

# -----------------------------------------------------------------------------
# Helpers for Card Duel Mode
# -----------------------------------------------------------------------------

def deal_cd_pick_options(p: PlayerInGame, k: int = 3) -> list[str]:
    """
    Reserves k cards by popping from the deck and storing them in cd_pick_options.
    The reserved cards are removed from cd_deck until the pick resolves.

    Args:
        p (PlayerInGame): The player to deal cards to.
        k (int): Number of cards to pick. Defaults to 3.

    Returns:
        list[str]: list of card codes reserved for selection.
    """
    p.cd_deck = list(p.cd_deck or [])
    random.shuffle(p.cd_deck)

    take = min(k, len(p.cd_deck))
    opts = p.cd_deck[:take]
    p.cd_deck = p.cd_deck[take:]
    return opts

CARD_DUEL_START_HP = 20
CARD_DUEL_START_HAND = 5


def build_deck_codes() -> list[str]:
    """
    Fetches all active CardDuelCardType codes to build a fresh deck.

    Returns:
        list[str]: list of active card codes.
    """
    return list(
        CardDuelCardType.objects.filter(is_active=True)
        .order_by("category", "code")
        .values_list("code", flat=True)
    )


def draw(deck: list[str], n: int) -> tuple[list[str], list[str]]:
    """
    Draws n cards from the given deck.

    Args:
        deck (list[str]): The deck to draw from.
        n (int): Number of cards to draw.

    Returns:
        tuple[list[str], list[str]]: A tuple containing (drawn_cards, remaining_deck).
    """
    n = max(0, int(n))
    return deck[:n], deck[n:]


@transaction.atomic
def start_game(game: Game) -> None:
    """
    Starts a Card Duel game mode.
    - Seeds card definitions.
    - Clears existing board tiles (as Card Duel does not use the board).
    - Sets game status to ACTIVE.
    - Randomizes turn order.
    - Initializes Card Duel state for each player (HP, deck, hand, etc.).

    Args:
        game (Game): The game instance to start.

    Raises:
        RuntimeError: If no active Card Duel cards are found.
    """
    seed_card_duel_cards()

    # No board in Card Duel mode
    game.tiles.all().delete()

    # Randomize player order
    player_ids = list(game.players.values_list("id", flat=True))
    random.shuffle(player_ids)
    for idx, pid in enumerate(player_ids):
        game.players.filter(id=pid).update(turn_order=idx)

    game.current_turn_index = 0
    game.status = Game.Status.ACTIVE
    game.save(update_fields=["current_turn_index", "status"])

    deck_codes = build_deck_codes()
    if not deck_codes:
        raise RuntimeError(
            "Card Duel failed to start: no active Card Duel cards found. "
            "Run seed_card_duel_cards() and ensure CardDuelCardType.is_active=True."
        )

    # Initialize each player's state
    for p in game.players.all():
        p.position = 0
        p.coins = 0
        p.hp = CARD_DUEL_START_HP
        p.shield_points = 0
        p.extra_rolls = 0
        p.is_alive = True

        p.cd_deck = deck_codes[:]
        random.shuffle(p.cd_deck)

        p.cd_hand = []
        p.cd_picks_done = 0
        p.cd_pick_options = deal_cd_pick_options(p, k=3)
        p.cd_discard = []
        p.cd_status = []
        p.cd_turn_flags = {
            "action_used": False,
            "bonus_used": False,
            "draws_this_turn": 0,
            "last_played": None
        }

        p.save(
            update_fields=[
                "position", "coins", "hp", "shield_points", "extra_rolls", "is_alive",
                "cd_deck", "cd_hand", "cd_discard", "cd_status", "cd_turn_flags", "cd_picks_done", "cd_pick_options",
            ]
        )


def public_state_patch_for_player(player: PlayerInGame) -> dict:
    """
    Generates a player-specific payload for the game state response.
    Includes Card Duel specific information like hand, deck count, and status.

    Args:
        player (PlayerInGame): The player to generate state for.

    Returns:
        dict: A dictionary containing the Card Duel state.
    """
    return {
        "card_duel": {
            "hand": list(player.cd_hand or []),
            "deck_count": len(player.cd_deck or []),
            "discard_count": len(player.cd_discard or []),
            "status": list(player.cd_status or []),
            "turn_flags": dict(player.cd_turn_flags or {}),
        }
    }
