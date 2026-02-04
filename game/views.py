import secrets
import string
import json
import random
import re
from urllib import request

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login, get_user_model
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.templatetags.static import static

from .card_duel_seed import seed_card_duel_cards


from django.db import transaction
from django.http import HttpResponse

from . import card_duel

from .forms import GameCreateForm, JoinGameForm

from .models import (
    Game,
    PlayerInGame,
    BoardTile,
    SupportCardInstance,
    SupportCardType,
    GameChatMessage,
    CardDuelCardType,
)
import game


def signup(request):
    """
    Handles user registration via a standard form.
    Logs the user in automatically upon successful signup.
    """
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect("game:home")
    else:
        form = UserCreationForm()

    return render(request, "registration/signup.html", {"form": form})


def password_reset_request(request):
    """
    Initiates the password reset flow by verifying the username.
    Stores user ID in session for the confirmation step.
    """
    if request.method == "POST":
        username = request.POST.get("username")
        User = get_user_model()
        user = User.objects.filter(username=username).first()
        if user:
            request.session["reset_user_id"] = user.id
            return redirect("game:password_reset_confirm")
        else:
            messages.error(request, "User with this username does not exist.")
    return render(request, "registration/password_reset_request.html")


def password_reset_confirm(request):
    """
    Completes the password reset process for the user in the session.
    """
    reset_user_id = request.session.get("reset_user_id")
    if not reset_user_id:
        return redirect("game:password_reset_request")

    User = get_user_model()
    user = get_object_or_404(User, id=reset_user_id)

    if request.method == "POST":
        new_password = request.POST.get("password")
        if new_password:
            user.set_password(new_password)
            user.save()
            del request.session["reset_user_id"]
            messages.success(request, "Password updated successfully. Please login.")
            return redirect("login")
        else:
            messages.error(request, "Please enter a new password.")

    return render(request, "registration/password_reset_confirm.html", {"reset_user": user})


@login_required
def profile(request):
    """
    Displays and updates the user's profile and game statistics.
    Handles profile picture uploads and basic info updates.
    """
    user = request.user
    from .models import Profile

    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == "POST":
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        birthdate = request.POST.get("birthdate")
        gender = request.POST.get("gender")
        profile_pic = request.FILES.get("profile_picture")

        if username and username != user.username:
            if get_user_model().objects.filter(username=username).exists():
                messages.error(request, "This username is already taken.")
            else:
                user.username = username

        user.first_name = first_name if first_name is not None else user.first_name
        user.last_name = last_name if last_name is not None else user.last_name
        user.email = email if email is not None else user.email

        if password:
            user.set_password(password)
            user.save()
            auth_login(request, user)
        else:
            user.save()

        if birthdate:
            profile.birthdate = birthdate
        if gender:
            profile.gender = gender
        if profile_pic:
            profile.profile_picture = profile_pic
        profile.save()

        messages.success(request, "Profile updated successfully.")
        return redirect("game:profile")

    # Stats
    user_games = PlayerInGame.objects.filter(user=user).select_related("game")
    total_games = user_games.count()
    total_wins = Game.objects.filter(winner__user=user).count()
    win_rate = (total_wins / total_games * 100) if total_games > 0 else 0

    # Match History
    history_qs = user_games.order_by("-game__created_at")[:10]
    history = []
    from django.utils import timezone
    
    for match in history_qs:
        game = match.game
        duration_str = "-"
        
        # Calculate duration
        start = game.created_at
        end = game.updated_at if game.status == "finished" else timezone.now()
        
        if start and end:
            diff = end - start
            total_seconds = int(diff.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            duration_str = f"{hours:02}:{minutes:02}:{seconds:02}"

        history.append({
            "game": game,
            "created_at": game.created_at,
            "duration": duration_str,
            "match_id": match.id # keep reference if needed
        })

    context = {
        "user_profile": user,
        "profile": profile,
        "total_games": total_games,
        "total_wins": total_wins,
        "win_rate": round(win_rate, 1),
        "history": history,
    }
    return render(request, "profile.html", context)


def generate_game_code(length: int = 6) -> str:
    """Generates a random alphanumeric code of given length."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

SURVIVAL_LEN = 35
CARD_DUEL_START_HP = 20
CARD_DUEL_START_HAND = 5

def build_card_duel_deck_codes() -> list[str]:
    """
    Returns a list of card type codes for a full Card Duel deck.
    """
    # full 20-card deck = all active card duel types
    # We store card codes in PlayerInGame JSON fields
    return list(
        CardDuelCardType.objects.filter(is_active=True)
        .order_by("category", "code")
        .values_list("code", flat=True)
    )

def draw_cards_from_deck(deck: list, n: int) -> tuple[list, list]:
    """
    Draws n cards from the top of the deck.
    Returns (drawn_cards, remaining_deck).
    """
    # returns (drawn, remaining_deck)
    n = max(0, int(n or 0))
    drawn = deck[:n]
    remaining = deck[n:]
    return drawn, remaining

def _tile_weights_for(game: Game):
    """
    Determines probability weights for board tile generation based on game mode and difficulty.
    """
    # Base weights (Normal)
    weights = {
        BoardTile.TileType.QUESTION: 3,
        BoardTile.TileType.TRAP: 2,
        BoardTile.TileType.HEAL: 2,
        BoardTile.TileType.BONUS: 2,
        BoardTile.TileType.WARP: 1,
        BoardTile.TileType.MASS_WARP: 1,
        BoardTile.TileType.DUEL: 1,
        BoardTile.TileType.SHOP: 1,
        BoardTile.TileType.SAFE: 1,
        BoardTile.TileType.GUN: 1,
    }

    if game.mode != Game.Mode.SURVIVAL:
        return weights
    
    if game.mode == Game.Mode.DRAFT:
        weights.pop(BoardTile.TileType.BONUS, None)
        return weights

    diff = game.survival_difficulty

    if diff == Game.SurvivalDifficulty.EASY:
        # “all tiles except mass warp and trap”
        weights.pop(BoardTile.TileType.MASS_WARP, None)
        weights.pop(BoardTile.TileType.TRAP, None)
        weights[BoardTile.TileType.BONUS] = 4  # bonus more
        weights[BoardTile.TileType.HEAL] = 3

    elif diff == Game.SurvivalDifficulty.HARD:
        weights[BoardTile.TileType.BONUS] = 1  # bonus less
        weights[BoardTile.TileType.HEAL] = 1
        weights[BoardTile.TileType.TRAP] = 4   # traps more impactful
        weights[BoardTile.TileType.QUESTION] = 4

    return weights

def enrich_draft_options(state: dict) -> dict:
    """
    Converts draft.options from [card_type_id, ...] into
    [{id, title, image_url}, ...] so the frontend can render images + names.
    """
    if not isinstance(state, dict):
        return state

    draft = state.get("draft")
    if not (draft and isinstance(draft, dict) and draft.get("active")):
        return state

    options = draft.get("options")
    if not isinstance(options, list) or not options:
        return state

    # If already enriched, do nothing
    if isinstance(options[0], dict) and "image_url" in options[0]:
        return state

    # options are SupportCardType IDs (ints)
    ids = []
    for x in options:
        try:
            ids.append(int(x))
        except Exception:
            pass

    types = SupportCardType.objects.filter(id__in=ids).only("id", "code", "name")
    by_id = {t.id: t for t in types}

    # Map SupportCardType.code -> your static image files
    CODE_TO_IMAGE = {
        "bonus_coin": "images/coin.png",
        "heal": "images/heal.png",
        "move_extra": "images/move.png",
        "reroll": "images/reroll.png",
        "shield": "images/shield.png",
        "swap_position": "images/swap.png",
        "change_question": "images/question.png", 
    }

    enriched = []
    for cid in ids:
        ct = by_id.get(cid)
        if ct:
            img = CODE_TO_IMAGE.get(ct.code, "images/question.png")
            title = ct.name or ct.code.replace("_", " ").title()
        else:
            img = "images/question.png"
            title = f"Card #{cid}"

        enriched.append({
            "id": cid,
            "title": title,
            "image_url": static(img),
        })

    draft["options"] = enriched
    state["draft"] = draft
    return state

def deal_draft_options(game, player, k=3):
    """
    Selects k unique support card options for a player to draft.
    Avoids cards the player already owns.
    """
    from .models import SupportCardType, SupportCardInstance

    owned_type_ids = set(
        SupportCardInstance.objects.filter(owner=player).values_list("card_type_id", flat=True)
    )

    all_ids = list(SupportCardType.objects.values_list("id", flat=True))

    pool = [cid for cid in all_ids if cid not in owned_type_ids]
    if len(pool) < k:
        pool = all_ids

    return random.sample(pool, min(k, len(pool)))

@login_required
@require_POST
def draft_pick(request, game_id):
    """
    API endpoint for a player to select a card during the draft phase.
    """
    from .models import Game, SupportCardType, SupportCardInstance

    game = Game.objects.select_related().get(id=game_id)

    if game.mode != Game.Mode.DRAFT:
        return JsonResponse({"detail": "Not a Draft Mode game."}, status=400)
    if game.status != Game.Status.DRAFTING:
        return JsonResponse({"detail": "Drafting is not active."}, status=400)

    # Find player record for current user
    player = game.players.filter(user=request.user).first()
    if not player:
        return JsonResponse({"detail": "You are not in this game."}, status=403)

    if player.draft_picks >= 3:
        return JsonResponse({"detail": "You already finished drafting."}, status=400)

    # Read JSON { "card_type_id": ... }
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
        card_type_id = int(data.get("card_type_id"))
    except Exception:
        return JsonResponse({"detail": "Invalid payload."}, status=400)

    # Validate choice exists in options
    options = player.draft_options or []
    if card_type_id not in options:
        return JsonResponse({"detail": "Chosen card is not in your current draft options."}, status=400)

    # Create card instance in inventory
    card_type = SupportCardType.objects.get(id=card_type_id)
    SupportCardInstance.objects.create(owner=player, card_type=card_type)

    # Progress draft
    player.draft_picks += 1

    if player.draft_picks < 3:
        player.draft_options = deal_draft_options(game, player, k=3)
    else:
        player.draft_options = []

    player.save()

    # If all players finished (3 picks), start game
    all_done = all(p.draft_picks >= 3 for p in game.players.all())
    if all_done:
        game.status = Game.Status.ACTIVE
        game.save()

    return JsonResponse({
        "ok": True,
        "picks_done": player.draft_picks,
        "game_status": game.status,
    })

def create_default_board_for_game(game: Game, enabled_tiles=None):
    """
    Generates and populates the board tiles for a game instance based on configuration.
    Handles mode-specific rules and tile weights.
    """
    # ✅ IMPORTANT: clear old tiles
    game.tiles.all().delete()

    # Decide board length
    if game.mode == Game.Mode.SURVIVAL:
        game.board_length = SURVIVAL_LEN
        game.save(update_fields=["board_length"])
        board_len = SURVIVAL_LEN
    elif game.mode == Game.Mode.DRAFT:
        game.board_length = 35
        game.save(update_fields=["board_length"])
        board_len = 35
    else:
        board_len = int(game.board_length or 36)

    enabled_tiles = enabled_tiles if enabled_tiles is not None else (game.enabled_tiles or [])

    if not enabled_tiles:
        enabled_tiles = [
            value for (value, _label) in BoardTile.TileType.choices
            if value not in (BoardTile.TileType.START, BoardTile.TileType.FINISH, BoardTile.TileType.PORTAL)
        ]

    weights_map = _tile_weights_for(game)
    # never randomly generate portal
    weights_map.pop(BoardTile.TileType.PORTAL, None)

    if game.mode == Game.Mode.DRAFT:
        weights_map.pop(BoardTile.TileType.BONUS, None)

    allowed = [t for t in weights_map.keys() if (t in enabled_tiles or t == BoardTile.TileType.SAFE)]
    weights = [weights_map[t] for t in allowed]

    tiles = []
    last_index = board_len - 1

    for pos in range(board_len):
        if pos == 0:
            tiles.append(BoardTile(game=game, position=pos, tile_type=BoardTile.TileType.START, label="START"))
            continue

        # Last tile rules
        if pos == last_index:
            if game.mode == Game.Mode.SURVIVAL:
                tiles.append(BoardTile(game=game, position=pos, tile_type=BoardTile.TileType.PORTAL, label="PORTAL"))
            else:
                tiles.append(BoardTile(game=game, position=pos, tile_type=BoardTile.TileType.FINISH, label="FINISH"))
            continue


        tile_type = random.choices(allowed, weights=weights, k=1)[0]

        value_int = None
        label = ""

        if tile_type == BoardTile.TileType.TRAP:
            if game.mode == Game.Mode.SURVIVAL and game.survival_difficulty == Game.SurvivalDifficulty.HARD:
                value_int = -random.randint(3, 5)
                label = "TRAP (HARD)"
            else:
                value_int = -random.randint(1, 2)
                label = "TRAP"

        elif tile_type == BoardTile.TileType.HEAL:
            if game.mode == Game.Mode.SURVIVAL and game.survival_difficulty == Game.SurvivalDifficulty.HARD:
                value_int = random.randint(1, 2)
                label = "HEAL (≤2)"
            else:
                value_int = random.randint(1, 3)
                label = "HEAL"

        elif tile_type == BoardTile.TileType.BONUS:
            label = "BONUS"
        elif tile_type == BoardTile.TileType.QUESTION:
            label = "Q"
        elif tile_type == BoardTile.TileType.MASS_WARP:
            label = "MASS WARP"
        elif tile_type == BoardTile.TileType.WARP:
            label = "WARP"
        elif tile_type == BoardTile.TileType.DUEL:
            label = "DUEL"
        elif tile_type == BoardTile.TileType.SHOP:
            label = "SHOP"
        elif tile_type == BoardTile.TileType.GUN:
            label = "GUN"
        elif tile_type == BoardTile.TileType.SAFE:
            label = "SAFE"

        tiles.append(BoardTile(game=game, position=pos, tile_type=tile_type, value_int=value_int, label=label))

    BoardTile.objects.bulk_create(tiles)

def home(request):
    """Renders the landing page."""
    return render(request, "home.html")


@login_required
def game_list(request):
    """
    Displays a list of games the user can join or is already part of.
    """
    waiting_games = Game.objects.filter(status=Game.Status.WAITING).order_by("-created_at")
    my_games = Game.objects.filter(players__user=request.user).distinct().order_by("-created_at")

    context = {"waiting_games": waiting_games, "my_games": my_games}
    return render(request, "game_list.html", context)


@login_required
def game_create(request):
    """
    Handles the creation of a new game via form submission.
    Initializes the game, assigns a code, and adds the creator as the first player.
    """
    if request.method == "POST":
        form = GameCreateForm(request.POST)
        if form.is_valid():
            game: Game = form.save(commit=False)

            game.enabled_tiles = form.cleaned_data.get("enabled_tiles") or []

            while True:
                candidate = generate_game_code()
                if not Game.objects.filter(code=candidate).exists():
                    game.code = candidate
                    break

            game.host = request.user
            game.save()

            # create_default_board_for_game(game, enabled_tiles=game.enabled_tiles)

            PlayerInGame.objects.create(
                game=game,
                user=request.user,
                turn_order=0,
                hp=3,
                coins=0,
                position=0,
                is_alive=True,
            )

            messages.success(request, f"Game created with code {game.code}. Share this with your friends.")
            return redirect("game:game_detail", game_id=game.id)
    else:
        form = GameCreateForm()

    return render(request, "game_create.html", {"form": form})


@login_required
def game_join(request):
    """
    Allows a user to join an existing game by entering its code.
    """
    if request.method == "POST":
        form = JoinGameForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"]
            return _join_game_logic(request, code)
    else:
        form = JoinGameForm()

    return render(request, "game_join.html", {"form": form})


@login_required
def join_game_by_code(request, code):
    """Join a game automatically via GET request (e.g., from QR code)."""
    return _join_game_logic(request, code)


def _join_game_logic(request, code):
    """Centralized logic for joining a game by its code."""
    try:
        game = Game.objects.get(code__iexact=code)
    except Game.DoesNotExist:
        messages.error(request, "Game with this code does not exist.")
        return redirect("game:game_join")

    if game.status != Game.Status.WAITING:
        messages.error(request, "This game has already started or finished.")
        return redirect("game:game_join")

    if PlayerInGame.objects.filter(game=game, user=request.user).exists():
        messages.info(request, "You are already in this game.")
        return redirect("game:game_detail", game_id=game.id)

    current_players = game.players.count()
    if current_players >= game.max_players:
        messages.error(request, "Game is full.")
        return redirect("game:game_join")

    PlayerInGame.objects.create(
        game=game,
        user=request.user,
        turn_order=current_players,
        hp=3,
        coins=0,
        position=0,
        is_alive=True,
        shield_points=0,
    )

    messages.success(request, f"You joined game {game.code}.")
    return redirect("game:game_detail", game_id=game.id)


@login_required
def game_detail(request, game_id: int):
    """
    Displays the game lobby or main detail view.
    Checks user permissions and prepares initial context.
    """
    game = get_object_or_404(Game, id=game_id)
    players = game.players.select_related("user").order_by("turn_order")
    tiles = game.tiles.order_by("position")
    
    if not players.filter(user=request.user).exists():
        if game.host != request.user:
            messages.error(request, "You are not a player in this game.")
            return redirect("game:game_list")

    is_host = (game.host == request.user)
    can_start = is_host and game.status == Game.Status.WAITING and players.count() >= 2

    state = game.to_public_state(for_user=request.user)

    context = {
        "game": game,
        "players": players,
        "is_host": is_host,
        "can_start": can_start,
        "game_state": state,
        "me_player_id": state["you_player_id"],
        "current_player_id": state["current_player_id"],
        "tiles": tiles,
    }
    return render(request, "game_detail.html", context)


def seed_support_cards():
    """Seeds the initial set of SupportCardTypes into the database."""
    SupportCardType.objects.get_or_create(
        code="move_extra",
        defaults=dict(
            name="Move extra cells",
            description="Move 1–3 extra cells.",
            effect_type=SupportCardType.EffectType.MOVE_EXTRA,
            params={},
            is_active=True,
        ),
    )
    SupportCardType.objects.get_or_create(
        code="heal",
        defaults=dict(
            name="Heal HP",
            description="Heal 2 HP (max 3).",
            effect_type=SupportCardType.EffectType.HEAL,
            params={},
            is_active=True,
        ),
    )
    SupportCardType.objects.get_or_create(
        code="shield",
        defaults=dict(
            name="Damage shield",
            description="Activate shield that blocks 2 damage.",
            effect_type=SupportCardType.EffectType.SHIELD,
            params={},
            is_active=True,
        ),
    )
    SupportCardType.objects.get_or_create(
        code="reroll",
        defaults=dict(
            name="Reroll dice",
            description="Gain 1 extra roll (keeps your turn).",
            effect_type=SupportCardType.EffectType.REROLL,
            params={},
            is_active=True,
        ),
    )
    SupportCardType.objects.get_or_create(
        code="swap_position",
        defaults=dict(
            name="Swap position",
            description="Swap with an adjacent player.",
            effect_type=SupportCardType.EffectType.SWAP_POSITION,
            params={},
            is_active=True,
        ),
    )
    SupportCardType.objects.get_or_create(
        code="change_question",
        defaults=dict(
            name="Change question",
            description="Change the current question once.",
            effect_type=SupportCardType.EffectType.CHANGE_QUESTION,
            params={},
            is_active=True,
        ),
    )
    SupportCardType.objects.get_or_create(
        code="bonus_coin",
        defaults=dict(
            name="Bonus coin",
            description="Get 1–3 coins.",
            effect_type=SupportCardType.EffectType.BONUS_COIN,
            params={},
            is_active=True,
        ),
    )


@login_required
@require_POST
def game_start(request, game_id: int):
    """
    Transitions the game from WAITING to ACTIVE (or DRAFTING).
    Initializes board, support cards, and player states.
    """
    game = get_object_or_404(Game, id=game_id)

    if request.method != "POST":
        return redirect("game:game_detail", game_id=game.id)

    if game.host != request.user:
        messages.error(request, "Only the host can start the game.")
        return redirect("game:game_detail", game_id=game.id)

    players = game.players.all()
    if players.count() < 2:
        messages.error(request, "Need at least 2 players to start the game.")
        return redirect("game:game_detail", game_id=game.id)

    # 1 Ensure support cards exist
    seed_support_cards()

    if game.mode == Game.Mode.CARD_DUEL:
        try:
            card_duel.start_game(game)
        except RuntimeError as e:
            # Dev-friendly: fail loudly instead of silently continuing to UI
            return JsonResponse({"detail": str(e)}, status=500)

        messages.success(request, "Card Duel started!")
        return redirect("game:game_board", game_id=game.id)

    
    elif game.mode in (Game.Mode.SURVIVAL, Game.Mode.DRAFT):
        create_default_board_for_game(game, enabled_tiles=game.enabled_tiles)
    else:
        game.generate_random_board()

    # 2 Start based on mode (Draft stays DRAFTING; others become ACTIVE)
    if game.mode == Game.Mode.DRAFT:
        # Draft start: give choices, reset picks, reset positions
        game.status = Game.Status.DRAFTING

        for player in game.players.all():
            player.draft_options = deal_draft_options(game, player, k=3)
            player.draft_picks = 0
            player.position = 0
            player.save()

        # Do NOT set ACTIVE here
        game.save(update_fields=["status"])

    else:
        # Standard start for Finish Line / Survival
        # NEW: Skip ORDERING, go straight to ACTIVE
        game.status = Game.Status.ACTIVE
        game.current_turn_index = 0

        # Randomize turn order
        players_list = list(game.players.all())
        random.shuffle(players_list)
        
        for idx, player in enumerate(players_list):
            player.turn_order = idx
            player.position = 0
            player.save(update_fields=["turn_order", "position"])
            
        # Clear ordering state
        game.ordering_state = None
        game.save(update_fields=["status", "current_turn_index", "ordering_state"])


    messages.success(request, "Game started! Board generated.")
    return redirect("game:game_board", game_id=game.id)


@login_required
@require_POST
@transaction.atomic
def game_delete(request, game_id: int):
    """
    Permanently deletes a game instance and all associated data.
    Only the host allowed.
    """
    game = get_object_or_404(Game, id=game_id)

    if game.host != request.user:
        messages.error(request, "You do not have permission to delete this game.")
        return redirect("game:game_list")

    game.delete()
    messages.success(request, "Game deleted successfully.")
    return redirect("game:game_list")



@login_required
@require_POST
@transaction.atomic
def game_end(request, game_id: int):
    """
    Manually forces the game to FINISHED status.
    Only the host allowed.
    """
    game = get_object_or_404(Game, id=game_id)

    if game.host != request.user:
        return JsonResponse({"detail": "Only the host can end the game."}, status=403)

    game.status = Game.Status.FINISHED
    game.pending_question = None
    game.pending_shop = None
    game.save(update_fields=["status", "pending_question", "pending_shop"])

    messages.success(request, "Game ended.")
    return redirect("game:game_detail", game_id=game.id)

@login_required
@require_GET
def game_state(request, game_id: int):
    """
    Returns the current game state as JSON for the frontend polling/updates.
    Includes player positions, stats, board state, and mode-specific data (e.g. Draft/Duel).
    """
    game = get_object_or_404(Game, id=game_id)

    players = game.players.select_related("user")
    is_player = players.filter(user=request.user).exists()
    is_host = (game.host == request.user)

    if not (is_player or is_host):
        return JsonResponse({"detail": "Forbidden"}, status=403)

    MAX_PICKS = 5
    state = game.to_public_state(for_user=request.user)
    state = enrich_draft_options(state)

    if game.mode == Game.Mode.CARD_DUEL:
        cd_payload = _cd_build_state_for_user(game, request.user)
        state["card_duel"] = cd_payload
        state["card_duel_pick"] = cd_payload.get("pick", {"active": False})
        
        me = game.players.select_related("user").filter(user=request.user).first()
        opp = game.players.exclude(user=request.user).first()

        if me:
            # Auto-heal: if picks are pending but options are empty, re-deal options
            if (me.cd_picks_done or 0) < MAX_PICKS and not (me.cd_pick_options or []):
                
                # 1. Check if deck is empty
                if not (me.cd_deck or []):
                    # 2. Try to get codes from DB
                    deck_codes = card_duel.build_deck_codes()
                    
                    # 3. IF DB IS EMPTY, SEED IT NOW
                    if not deck_codes:
                        seed_card_duel_cards() 
                        deck_codes = card_duel.build_deck_codes()

                    # 4. Rebuild player deck
                    if deck_codes:
                        import random
                        me.cd_deck = list(deck_codes)
                        random.shuffle(me.cd_deck)

                # 5. Deal options from the (now hopefully populated) deck
                if me.cd_deck:
                    me.cd_pick_options = card_duel.deal_cd_pick_options(me, k=3)
                    me.save(update_fields=["cd_pick_options", "cd_deck"])

            # Build pick payload
            if me.cd_picks_done < MAX_PICKS:
                codes = list(me.cd_pick_options or [])
                types = {t.code: t for t in CardDuelCardType.objects.filter(code__in=codes)}

                options_payload = []
                for c in codes:
                    t = types.get(c)
                    title = (t.name if t else c)
                    img = _cd_image_filename(title)
                    options_payload.append({
                        "code": c,
                        "title": title,
                        "image_url": static(f"images/CardDuelCards/{img}"),
                    })

                pick_payload = {
                    "active": True,
                    "picks_done": int(me.cd_picks_done or 0),
                    "max_picks": MAX_PICKS,
                    "options": options_payload,
                }
            else:
                pick_payload = {"active": False, "picks_done": int(me.cd_picks_done or 0), "max_picks": MAX_PICKS, "options": []}


            # Hand as enriched objects
            my_hand_codes = list(me.cd_hand or [])
            my_hand = [_cd_card_payload_from_code(c) for c in my_hand_codes]

            # Put pick in ONE consistent location: card_duel.pick
            # game/views.py  (inside Mode.CARD_DUEL: where you set state["card_duel"] = {...})

            state["card_duel"] = {
                "pick": pick_payload,  # ✅ ADD THIS LINE
                "you": {
                    "player_id": me.id,
                    "hp": int(me.hp or 0),
                    "shield": int(me.shield_points or 0),
                    "deck_count": _safe_len(me.cd_deck),
                    "discard_count": _safe_len(me.cd_discard),
                    "hand": my_hand,
                },
                "opponent": {
                    "player_id": getattr(opp, "id", None),
                    "hp": int(getattr(opp, "hp", 0) or 0) if opp else None,
                    "shield": int(getattr(opp, "shield_points", 0) or 0) if opp else None,
                    "deck_count": _safe_len(getattr(opp, "cd_deck", None)) if opp else None,
                    "discard_count": _safe_len(getattr(opp, "cd_discard", None)) if opp else None,
                    "hand_count": _safe_len(getattr(opp, "cd_hand", None)) if opp else None,
                },
                "current_turn_player_id": getattr(game, "current_player_id", None),
            }


            # keep backward-compat if frontend still reads this:
            state["card_duel_pick"] = pick_payload
        else:
            state["card_duel_pick"] = {"active": False}

    return JsonResponse(state)


@login_required
@require_POST
@transaction.atomic
def game_roll(request, game_id: int):
    """
    Executes a dice roll for the current player.
    Validates turn order and strictly blocking states (Pending Question/Shop/Duel).
    """
    game = get_object_or_404(Game, id=game_id)

    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    try:
        player = game.players.select_related("user").get(user=request.user)
    except PlayerInGame.DoesNotExist:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    if not player.is_alive:
        return JsonResponse({"detail": "You are eliminated."}, status=400)

    # If a question is pending, rolling is blocked until answered by the owner.
    if game.pending_question:
        game.sync_turn_to_pending_question()
        owner_id = game.pending_question.get("for_player_id")
        if owner_id != player.id:
            return JsonResponse({"detail": "A question is being answered by another player."}, status=403)
        return JsonResponse(
            {"detail": "Answer the question first.", "game_state": game.to_public_state(for_user=request.user)},
            status=400
        )
    
    # If a shop is pending, rolling is blocked until closed by the owner.
    if game.pending_shop:
        game.sync_turn_to_pending_shop()
        owner_id = game.pending_shop.get("for_player_id")
        if owner_id != player.id:
            return JsonResponse({"detail": "A player is currently shopping."}, status=403)
        return JsonResponse(
            {"detail": "Close the shop first.", "game_state": game.to_public_state(for_user=request.user)},
            status=400
        )
    
    if getattr(game, "pending_duel", None):
        game.sync_turn_to_pending_duel()
        pd = game.pending_duel or {}
        initiator_id = pd.get("initiator_id") or pd.get("for_player_id")
        participants = [pid for pid in [initiator_id, pd.get("opponent_id")] if pid]
        if player.id not in participants:
            return JsonResponse({"detail": "A duel is being resolved."}, status=403)
        return JsonResponse(
            {"detail": "Finish the duel first.", "game_state": game.to_public_state(for_user=request.user)},
            status=400
        )
    # If a gun action is pending, rolling is blocked until target is chosen by the owner.
    if getattr(game, "pending_gun", None):
        game.sync_turn_to_pending_gun()
        owner_id = (game.pending_gun or {}).get("for_player_id")
        if owner_id != player.id:
            return JsonResponse({"detail": "A player is choosing a gun target."}, status=403)
        return JsonResponse(
            {"detail": "Choose a target first.", "game_state": game.to_public_state(for_user=request.user)},
            status=400
        )
    # Normal turn check
    current = game.current_player
    if not current or current.id != player.id:
        return JsonResponse(
            {"detail": "It is not your turn.", "game_state": game.to_public_state(for_user=request.user)},
            status=403
        )
    if game.mode == Game.Mode.CARD_DUEL:
        return JsonResponse({"detail": "Dice is disabled in Card Duel."}, status=400)

    action_result = game.roll_and_apply_for(player)
    state = game.to_public_state(for_user=request.user)

    return JsonResponse({
        "action": "roll",
        "result": action_result,
        "game_state": state,
    })

@login_required
@require_POST
@transaction.atomic
def game_order_roll(request, game_id: int):
    """
    Handles dice rolls for determining initial turn order.
    Resolves ties by triggering rerolls for tied players.
    """
    # Lock row to avoid double-roll race conditions
    game = Game.objects.select_for_update().get(id=game_id)

    if game.status != Game.Status.ORDERING:
        return JsonResponse({"detail": "Turn order rolling is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()
    if not me:
        return JsonResponse({"detail": "You are not in this game."}, status=403)

    st = game.ordering_state or {}
    pending = list(st.get("pending_player_ids") or [])
    roll_history = dict(st.get("roll_history") or {})

    # Ensure IDs are ints in pending
    try:
        pending = [int(x) for x in pending]
    except Exception:
        pending = []

    if me.id not in pending:
        return JsonResponse({"detail": "You already rolled (or you are not in the pending group)."}, status=400)

    dice = random.randint(1, 6)

    key = str(me.id)
    if key not in roll_history or not isinstance(roll_history.get(key), list):
        roll_history[key] = []
    roll_history[key].append(int(dice))

    # remove from pending
    pending.remove(me.id)

    st["pending_player_ids"] = pending
    st["roll_history"] = roll_history
    game.ordering_state = st
    game.save(update_fields=["ordering_state"])

    # If round finished, either create a tie reroll group or finalize order
    if len(pending) == 0:
        # Build sequences: pid -> tuple([roll1, roll2, ...])
        seqs = {}
        for pid_str, seq_list in roll_history.items():
            try:
                pid_int = int(pid_str)
            except Exception:
                continue
            if isinstance(seq_list, list):
                seqs[pid_int] = tuple(int(x) for x in seq_list)

        # Group by identical sequence (ties)
        groups = {}
        for pid_int, seq in seqs.items():
            groups.setdefault(seq, []).append(pid_int)

        tied = []
        for seq, ids in groups.items():
            if len(ids) > 1:
                tied.extend(ids)

        if tied:
            # Only tied players reroll next
            st["pending_player_ids"] = tied
            game.ordering_state = st
            game.save(update_fields=["ordering_state"])

        else:
            # FINALIZE: assign turn_order by dice sequence (lexicographic desc)
            # seqs: {player_id: (roll1, roll2, ...)}
            final_sorted = sorted(seqs.items(), key=lambda kv: kv[1], reverse=True)

            # Apply turn order (0 = first)
            for idx, (pid, _seq) in enumerate(final_sorted):
                game.players.filter(id=pid).update(turn_order=idx)

            # Switch the game to ACTIVE and clear ordering state
            game.status = Game.Status.ACTIVE
            game.current_turn_index = 0
            game.ordering_state = None
            game.save(update_fields=["status", "current_turn_index", "ordering_state"])



    # Return state for UI (includes ordering payload if still ordering)
    state = game.to_public_state(for_user=request.user)
    state = enrich_draft_options(state)

    return JsonResponse(
        {
            "result": {"dice": dice},
            "game_state": state,
        }
    )

@login_required
@require_POST
@transaction.atomic
def answer_question(request, game_id: int):
    """
    Submits an answer for the pending question.
    Awards coins for correct answers or deals damage for wrong ones, then advances turn.
    """
    game = get_object_or_404(Game, id=game_id)

    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    try:
        player = game.players.select_related("user").get(user=request.user)
    except PlayerInGame.DoesNotExist:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    pq = game.pending_question
    if not pq:
        return JsonResponse({"detail": "No pending question."}, status=400)

    # ✅ authority: pending_question ownership (turn is locked here)
    if pq.get("for_player_id") != player.id:
        return JsonResponse({"detail": "It is not your turn."}, status=403)

    # keep turn index aligned (prevents drift)
    game.sync_turn_to_pending_question()

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"detail": "Invalid payload."}, status=400)

    is_timeout = bool(body.get("timeout", False))

    if is_timeout:
        choice_index = None
    else:
        try:
            choice_index = int(body.get("choice_index"))
        except Exception:
            return JsonResponse({"detail": "Invalid payload."}, status=400)


    correct_index = int(pq.get("correct_index"))
    is_correct = (False if is_timeout else (choice_index == correct_index))

    # Rewards:
    # Correct: +1 coin
    # Wrong: -1 hp (damage with shield)
    if is_correct:
        player.coins += 1
        player.save(update_fields=["coins"])
    else:
        game.apply_damage(player, 1, effects=None, source="question")

    # Clear question and advance turn
    game.pending_question = None
    game.save(update_fields=["pending_question"])
    game.advance_turn()

    state = game.to_public_state(for_user=request.user)

    return JsonResponse({
        "action": "answer_question",
        "result": {"correct": is_correct, "timeout": is_timeout},
        "game_state": state,
    })

@login_required
@require_POST
@transaction.atomic
def shop_buy(request, game_id: int):
    """
    Purchases a Support Card from the shop.
    Deducts coins and adds the card to the player's inventory.
    """
    game = get_object_or_404(Game, id=game_id)
    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()
    if not me:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    ps = game.pending_shop
    if not ps:
        return JsonResponse({"detail": "No active shop."}, status=400)
    if ps.get("for_player_id") != me.id:
        return JsonResponse({"detail": "It is not your shop."}, status=403)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
        card_type_id = int(body.get("card_type_id"))
    except Exception:
        return JsonResponse({"detail": "Invalid payload."}, status=400)

    offers = ps.get("offers") or []
    offer = next((o for o in offers if int(o.get("card_type_id")) == card_type_id), None)
    if not offer:
        return JsonResponse({"detail": "This item is not available in the shop."}, status=400)

    cost = int(offer.get("cost") or 0)
    if me.coins < cost:
        return JsonResponse({"detail": "Not enough coins."}, status=400)

    ct = SupportCardType.objects.filter(id=card_type_id, is_active=True).first()
    if not ct:
        return JsonResponse({"detail": "Card type not found."}, status=404)

    me.coins -= cost
    me.save(update_fields=["coins"])
    SupportCardInstance.objects.create(card_type=ct, owner=me)

    return JsonResponse({"game_state": game.to_public_state(for_user=request.user)})


@login_required
@require_POST
@transaction.atomic
def shop_sell(request, game_id: int):
    """
    Sells a Support Card back to the shop for half its value.
    """
    game = get_object_or_404(Game, id=game_id)
    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()
    if not me:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    ps = game.pending_shop
    if not ps:
        return JsonResponse({"detail": "No active shop."}, status=400)
    if ps.get("for_player_id") != me.id:
        return JsonResponse({"detail": "It is not your shop."}, status=403)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
        card_instance_id = int(body.get("card_instance_id"))
    except Exception:
        return JsonResponse({"detail": "Invalid payload."}, status=400)

    inst = SupportCardInstance.objects.select_related("card_type").filter(
        id=card_instance_id, owner=me, is_used=False
    ).first()
    if not inst:
        return JsonResponse({"detail": "Card not found."}, status=404)

    # sell value: ~50% of buy cost, minimum 1
    buy_cost = game.support_card_cost(inst.card_type)
    sell_value = max(1, int(buy_cost // 2))

    inst.delete()
    me.coins += sell_value
    me.save(update_fields=["coins"])

    return JsonResponse({"game_state": game.to_public_state(for_user=request.user)})


@login_required
@require_POST
@transaction.atomic
def shop_close(request, game_id: int):
    """
    Closes the shop and advances the turn.
    """
    game = get_object_or_404(Game, id=game_id)
    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()
    if not me:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    ps = game.pending_shop
    if not ps:
        return JsonResponse({"detail": "No active shop."}, status=400)
    if ps.get("for_player_id") != me.id:
        return JsonResponse({"detail": "It is not your shop."}, status=403)

    game.pending_shop = None
    game.save(update_fields=["pending_shop"])
    game.advance_turn()

    return JsonResponse({"game_state": game.to_public_state(for_user=request.user)})

@login_required
@require_POST
@transaction.atomic
def gun_attack(request, game_id: int):
    """
    Executes a Gun tile attack against a chosen target player.
    Deals damage and advances turn.
    """
    game = get_object_or_404(Game, id=game_id)
    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()
    if not me:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    pg = game.pending_gun
    if not pg:
        return JsonResponse({"detail": "No pending gun action."}, status=400)

    if pg.get("for_player_id") != me.id:
        return JsonResponse({"detail": "It is not your action."}, status=403)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
        target_id = int(body.get("target_player_id"))
    except Exception:
        return JsonResponse({"detail": "Invalid payload."}, status=400)

    if target_id == me.id:
        return JsonResponse({"detail": "You cannot target yourself."}, status=400)

    target = game.players.select_related("user").filter(id=target_id, is_alive=True).first()
    if not target:
        return JsonResponse({"detail": "Target not found or not alive."}, status=404)

    damage = int(pg.get("damage", 2) or 2)
    game.apply_damage(target, damage, effects=None, source="gun")

    # clear pending gun and advance turn
    game.pending_gun = None
    game.save(update_fields=["pending_gun"])
    game.advance_turn()

    return JsonResponse({
        "action": "gun_attack",
        "result": {"target_player_id": target.id, "damage": damage},
        "game_state": game.to_public_state(for_user=request.user),
    })

@login_required
@require_POST
@transaction.atomic
def gun_skip(request, game_id: int):
    """
    Skips the Gun tile action (no shot fired).
    Advances turn.
    """
    game = get_object_or_404(Game, id=game_id)
    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()
    if not me:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    pg = getattr(game, "pending_gun", None)
    if not pg:
        return JsonResponse({"detail": "No pending gun action."}, status=400)

    if pg.get("for_player_id") != me.id:
        return JsonResponse({"detail": "It is not your action."}, status=403)

    # Clear gun action and skip this player's turn
    game.pending_gun = None
    game.save(update_fields=["pending_gun"])
    game.advance_turn()

    return JsonResponse({
        "action": "gun_skip",
        "game_state": game.to_public_state(for_user=request.user),
    })

@login_required
def game_board(request, game_id: int):
    """
    Renders the game board UI.
    Dispatches to 'card_duel.html' if mode is Card Duel, otherwise 'game_board.html'.
    """
    game = get_object_or_404(Game, id=game_id)
    
    players_qs = game.players.select_related("user")
    is_player = players_qs.filter(user=request.user).exists()
    is_host = (game.host == request.user)

    if not (is_player or is_host):
        messages.error(request, "You are not a player in this game.")
        return redirect("game:game_list")

    if game.status not in (Game.Status.ACTIVE, Game.Status.DRAFTING, Game.Status.ORDERING):
        messages.info(request, "Game is not active yet.")
        return redirect("game:game_detail", game_id=game.id)

    state = game.to_public_state(for_user=request.user)
    state = enrich_draft_options(state)

    tiles_qs = game.tiles.order_by("position")
    players_ordered = players_qs.order_by("turn_order")

    context = {
        "game": game,
        "game_state": state,
        "me_player_id": state["you_player_id"],
        "current_player_id": state["current_player_id"],
        "players": players_ordered,
        "tiles": tiles_qs,
    }
    template = "game_board.html"
    if game.mode == Game.Mode.CARD_DUEL:
        template = "card_duel.html"

    return render(request, template, context)

@login_required
@require_POST
def use_card(request, game_id):
    """
    Activates a Support Card (Finish Line / Survival modes).
    Applies effect immediately and marks card as used.
    """
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        body = {}

    card_id = body.get("card_id")
    target_player_id = body.get("target_player_id")

    if not card_id:
        return JsonResponse({"detail": "card_id is required."}, status=400)

    game = Game.objects.select_related().get(id=game_id)

    me = game.players.select_related("user").filter(user=request.user).first()
    if not me:
        return JsonResponse({"detail": "You are not in this game."}, status=403)

    card = SupportCardInstance.objects.select_related("card_type", "owner").filter(
        id=card_id, owner=me, is_used=False
    ).first()
    if not card:
        return JsonResponse({"detail": "Card not found (or already used)."}, status=404)

    ctype = card.card_type
    et = ctype.effect_type

    if et == "move_extra":
        steps = random.randint(1, 3)
        game.apply_basic_move(me, dice_value=steps)

    elif et == "heal":
        me.hp = me.hp + 2
        me.save(update_fields=["hp"])

    elif et == "shield":
        me.shield_points = me.shield_points + 2
        me.save(update_fields=["shield_points"])

    elif et == "reroll":
        me.extra_rolls = getattr(me, "extra_rolls", 0) + 1
        me.save(update_fields=["extra_rolls"])

    elif et == "swap_position":
        candidates = (
            game.players.filter(is_alive=True)
            .exclude(id=me.id)
            .filter(position__gt=me.position)
        )

        if not candidates.exists():
            return JsonResponse({"detail": "No alive player ahead of you to swap with."}, status=400)

        target = random.choice(list(candidates))

        me_pos = me.position
        me.position = target.position
        target.position = me_pos
        me.save(update_fields=["position"])
        target.save(update_fields=["position"])


    elif et == "change_question":
        if not game.pending_question:
            return JsonResponse({"detail": "No active question to change."}, status=400)

        if game.pending_question.get("for_player_id") != me.id:
            return JsonResponse({"detail": "Not your question."}, status=403)

        if game.pending_question.get("changed_once"):
            return JsonResponse({"detail": "You already changed this question once."}, status=400)

        from .questions import generate_math_question

        new_q = generate_math_question()
        game.pending_question = {
            **new_q,
            "for_player_id": me.id,
            "changed_once": True,
        }
        game.save(update_fields=["pending_question"])

    elif et == "bonus_coin":
        coins = random.randint(1, 3)
        me.coins += coins
        me.save(update_fields=["coins"])

    else:
        return JsonResponse({"detail": f"Unsupported card effect: {et}"}, status=400)

    card.is_used = True
    card.save(update_fields=["is_used"])

    return JsonResponse({"game_state": game.to_public_state(for_user=request.user)})

NEGATIVE_STATUS_TYPES = {"poison", "burn", "weaken", "vulnerable", "silence"}

def _cd_status_has(player: PlayerInGame, status_type: str) -> bool:
    """Checks if player has a specific active status (turns > 0)."""
    for s in (player.cd_status or []):
        if isinstance(s, dict) and s.get("type") == status_type and int(s.get("turns_left") or 0) > 0:
            return True
    return False

def _cd_add_status(player: PlayerInGame, status_dict: dict) -> None:
    """
    Adds/merges a status entry to player's cd_status.
    Merging strategy: if same type exists, increase stacks and refresh turns_left to max(existing, new).
    """
    if not isinstance(status_dict, dict):
        return

    stype = status_dict.get("type")
    if not stype:
        return

    turns = int(status_dict.get("turns") or status_dict.get("turns_left") or 0)
    stacks = int(status_dict.get("stacks") or 1)

    cur = list(player.cd_status or [])
    for s in cur:
        if isinstance(s, dict) and s.get("type") == stype:
            s["stacks"] = int(s.get("stacks") or 1) + stacks
            s["turns_left"] = max(int(s.get("turns_left") or 0), turns)
            # copy other keys if missing
            for k, v in status_dict.items():
                if k not in s:
                    s[k] = v
            player.cd_status = cur
            return

    # new entry
    entry = dict(status_dict)
    entry["stacks"] = stacks
    entry["turns_left"] = turns
    player.cd_status = cur + [entry]

def _cd_cleanse(player: PlayerInGame, remove_count: int = 1, allowed_types=None) -> int:
    """
    Removes up to remove_count statuses from cd_status (negative by default).
    Returns how many were removed.
    """
    allowed = set(allowed_types) if allowed_types else NEGATIVE_STATUS_TYPES
    cur = list(player.cd_status or [])
    kept = []
    removed = 0
    for s in cur:
        if removed < remove_count and isinstance(s, dict) and s.get("type") in allowed:
            removed += 1
            continue
        kept.append(s)
    player.cd_status = kept
    return removed

def _cd_draw(player: PlayerInGame, n: int) -> int:
    """Draws n cards from the player's personal deck to hand."""
    n = max(0, int(n or 0))
    deck = list(player.cd_deck or [])
    hand = list(player.cd_hand or [])
    drawn = deck[:n]
    player.cd_hand = hand + drawn
    player.cd_deck = deck[n:]
    return len(drawn)

def _cd_last_played_payload(player: PlayerInGame):
    """Returns {code,title,image_url} for the player's last played card, or None."""
    flags = dict(getattr(player, "cd_turn_flags", None) or {})
    code = flags.get("last_played")
    if not code:
        return None
    try:
        return _cd_card_payload_from_code(str(code))
    except Exception:
        # Never break state if mapping fails
        return {"code": str(code), "title": str(code), "image_url": static("images/CardDuelCards/Strike.png")}


def _cd_build_state_for_user(game: Game, user) -> dict:
    """Builds a consistent Card Duel payload for /state/ and action endpoints."""
    MAX_PICKS = 5
    me = game.players.select_related("user").filter(user=user).first()
    opp = game.players.exclude(user=user).first()

    if not me:
        return {"pick": {"active": False}, "you": {}, "opponent": {}, "current_turn_player_id": getattr(game, "current_player_id", None)}

    # pick payload
    if me.cd_picks_done < MAX_PICKS:
        codes = list(me.cd_pick_options or [])
        types = {t.code: t for t in CardDuelCardType.objects.filter(code__in=codes)}

        options_payload = []
        for c in codes:
            t = types.get(c)
            title = (t.name if t else c)
            img = _cd_image_filename(title)
            options_payload.append({
                "code": c,
                "title": title,
                "image_url": static(f"images/CardDuelCards/{img}"),
            })

        pick_payload = {
            "active": True,
            "picks_done": int(me.cd_picks_done or 0),
            "max_picks": MAX_PICKS,
            "options": options_payload,
        }
    else:
        pick_payload = {"active": False, "picks_done": int(me.cd_picks_done or 0), "max_picks": MAX_PICKS, "options": []}

    my_hand_codes = list(me.cd_hand or [])
    my_hand = [_cd_card_payload_from_code(c) for c in my_hand_codes]

    return {
        "pick": pick_payload,
        "you": {
            "player_id": me.id,
            "hp": int(me.hp or 0),
            "shield": int(me.shield_points or 0),
            "deck_count": _safe_len(me.cd_deck),
            "discard_count": _safe_len(me.cd_discard),
            "hand": my_hand,
            "last_played": _cd_last_played_payload(me),
            "statuses": list(me.cd_status or []),
            "turn_flags": dict(me.cd_turn_flags or {}),
        },
        "opponent": {
            "player_id": getattr(opp, "id", None),
            "hp": int(getattr(opp, "hp", 0) or 0) if opp else None,
            "shield": int(getattr(opp, "shield_points", 0) or 0) if opp else None,
            "deck_count": _safe_len(getattr(opp, "cd_deck", None)) if opp else None,
            "discard_count": _safe_len(getattr(opp, "cd_discard", None)) if opp else None,
            "hand_count": _safe_len(getattr(opp, "cd_hand", None)) if opp else None,
            "last_played": _cd_last_played_payload(opp) if opp else None,
            "statuses": list(getattr(opp, "cd_status", None) or []) if opp else [],
            "turn_flags": dict(getattr(opp, "cd_turn_flags", None) or {}) if opp else {},
        },
        "turn_flags": dict(me.cd_turn_flags or {}),
        "current_turn_player_id": getattr(game, "current_player_id", None),
    }

def _cd_apply_damage(game: Game, target: PlayerInGame, amount: int, *, ignore_shield: int = 0) -> dict:
    """
    Applies damage using shield_points first (with optional shield ignore for this hit).
    Returns dict with damage breakdown.
    """
    amount = max(0, int(amount or 0))
    ignore_shield = max(0, int(ignore_shield or 0))

    shield_before = int(getattr(target, "shield_points", 0) or 0)
    shield_effective = max(0, shield_before - ignore_shield)

    # damage hits shield_effective first
    dmg_to_shield = min(shield_effective, amount)
    remaining = amount - dmg_to_shield

    # new shield = original shield minus dmg_to_shield (ignore_shield doesn't delete shield, it just bypasses)
    target.shield_points = max(0, shield_before - dmg_to_shield)

    hp_before = int(getattr(target, "hp", 0) or 0)
    if remaining > 0:
        target.hp = max(0, hp_before - remaining)

    # alive state
    if target.hp <= 0:
        target.hp = 0
        target.is_alive = False

    target.save(update_fields=["shield_points", "hp", "is_alive"])

    return {
        "amount": amount,
        "ignore_shield": ignore_shield,
        "shield_before": shield_before,
        "shield_after": target.shield_points,
        "hp_before": hp_before,
        "hp_after": target.hp,
    }


def _cd_finish_if_dead(game: Game) -> None:
    """
    If only one player alive (or someone hit 0), finish game.
    """
    alive = list(game.players.filter(is_alive=True))
    if len(alive) <= 1:
        game.status = Game.Status.FINISHED
        game.save(update_fields=["status"])


@login_required
@require_POST
@transaction.atomic
def card_duel_play_card(request, game_id: int):
    """
    Handles playing a card in Card Duel mode.
    Validates turn, resource availability, status effects (Silence/Stun), and executes the card's effect.
    """
    game = get_object_or_404(Game, id=game_id)

    if game.mode != Game.Mode.CARD_DUEL:
        return JsonResponse({"detail": "Not a Card Duel game."}, status=400)

    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()

    if me.cd_picks_done < 5:
        return JsonResponse({"detail": "Finish selecting your starting cards first."}, status=400)

    if not me:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    if not me.is_alive:
        return JsonResponse({"detail": "You are eliminated."}, status=400)

    # Turn check
    current = game.current_player
    if not current or current.id != me.id:
        return JsonResponse({"detail": "It is not your turn.", "game_state": game.to_public_state(for_user=request.user)}, status=403)

    # Parse payload: {"card_code": "..."} OR {"card_id": 123}
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        body = {}

    card_code = body.get("card_code")
    card_id = body.get("card_id")

    card_type = None
    if card_code:
        card_type = CardDuelCardType.objects.filter(code=str(card_code), is_active=True).first()
    elif card_id is not None:
        try:
            card_type = CardDuelCardType.objects.filter(id=int(card_id), is_active=True).first()
        except Exception:
            card_type = None

    if not card_type:
        return JsonResponse({"detail": "Card not found."}, status=404)

    # Must have it in hand (we store codes by default)
    hand = list(me.cd_hand or [])
    if card_type.code not in hand:
        return JsonResponse({"detail": "That card is not in your hand."}, status=400)

    # Enforce turn limits & Status Blocks
    flags = dict(me.cd_turn_flags or {})
    action_used = bool(flags.get("action_used", False))
    bonus_used = bool(flags.get("bonus_used", False))

    is_bonus = (card_type.category == CardDuelCardType.Category.BONUS)

    # 1) Check Silence (blocks ALL cards)
    if _cd_status_has(me, "silence"):
        return JsonResponse({"detail": "You are silenced and cannot play cards this turn."}, status=400)

    # 2) Check Stun (blocks ACTION cards only)
    if not is_bonus and _cd_status_has(me, "stun"):
        return JsonResponse({"detail": "You are stunned and cannot play Action cards (Bonus cards allowed)."}, status=400)

    if is_bonus:
        if bonus_used:
            return JsonResponse({"detail": "Bonus card already used this turn."}, status=400)
    else:
        if action_used:
            return JsonResponse({"detail": "Action card already used this turn."}, status=400)

    # Opponent (2-player assumption)
    opp = game.players.filter(is_alive=True).exclude(id=me.id).first()
    if not opp:
        # no opponent alive -> finish
        _cd_finish_if_dead(game)
        return JsonResponse({"detail": "No opponent available.", "game_state": game.to_public_state(for_user=request.user)}, status=400)

    # Move card from hand -> discard
    hand.remove(card_type.code)
    me.cd_hand = hand
    me.cd_discard = list(me.cd_discard or []) + [card_type.code]

    # Resolve effect
    result = {"played": card_type.code, "effect_type": card_type.effect_type, "details": {}}
    params = dict(card_type.params or {})

    # Pre-modifiers from statuses (minimal implementation)
    # - vulnerable: target takes +damage_taken_up per stack
    # - weaken: attacker damage reduced on next attack
    damage_bonus = 0
    if card_type.effect_type == CardDuelCardType.EffectType.DAMAGE:
        # apply vulnerable on opponent
        for s in (opp.cd_status or []):
            if isinstance(s, dict) and s.get("type") == "vulnerable" and int(s.get("turns_left") or 0) > 0:
                damage_bonus += int(s.get("damage_taken_up") or 0) * int(s.get("stacks") or 1)

        # apply weaken on me (consumed once)
        weaken_down = 0
        damage_bonus_status = 0
        new_status = []
        for s in (me.cd_status or []):
            stype = s.get("type")
            stacks = int(s.get("stacks") or 1)
            turns = int(s.get("turns_left") or 0)
            
            if turns > 0:
                if stype == "weaken":
                    weaken_down = max(weaken_down, int(s.get("damage_down_next") or 0) * stacks)
                    # consume weaken immediately
                    continue
                if stype == "battle_focus":
                    damage_bonus_status += int(s.get("damage_bonus") or 0) * stacks
            
            new_status.append(s)
            
        if weaken_down:
            me.cd_status = new_status
            me.save(update_fields=["cd_status"])

        result["details"]["weaken_down"] = weaken_down
        result["details"]["vulnerable_bonus"] = damage_bonus
        result["details"]["battle_focus_bonus"] = damage_bonus_status

    # Execute by effect_type
    et = card_type.effect_type

    if et == CardDuelCardType.EffectType.HEAL:
        amt = int(params.get("amount") or 0)
        
        # Check Amplify
        amplify_bonus = 0
        new_status = []
        for s in (me.cd_status or []):
            stype = s.get("type")
            if stype == "amplify_heal" and int(s.get("turns_left") or 0) > 0:
                amplify_bonus += int(s.get("heal_bonus") or 0)
                # consume? usually yes for "next heal"
                if s.get("consume_on_heal"):
                    continue
            new_status.append(s)
            
        if amplify_bonus > 0:
            me.cd_status = new_status
            me.save(update_fields=["cd_status"])
            
        total_heal = amt + amplify_bonus
        me.hp = max(0, int(me.hp or 0) + total_heal)
        me.save(update_fields=["hp"])
        result["details"] = {"healed": total_heal, "base": amt, "amplify": amplify_bonus, "hp_after": me.hp}

    elif et == CardDuelCardType.EffectType.SHIELD:
        amt = int(params.get("amount") or 0)
        me.shield_points = int(getattr(me, "shield_points", 0) or 0) + amt
        me.save(update_fields=["shield_points"])
        result["details"] = {"shield_gained": amt, "shield_after": me.shield_points}

    elif et == CardDuelCardType.EffectType.DRAW:
        amt = int(params.get("amount") or 0)
        drew = _cd_draw(me, amt)

        # track draws this turn (optional, but useful for debugging/rules)
        flags["draws_this_turn"] = int(flags.get("draws_this_turn") or 0) + int(drew)

        result["details"] = {"draw_requested": amt, "drawn": drew, "hand_count": len(me.cd_hand or [])}

        apply_status = params.get("apply_status")
        if isinstance(apply_status, dict):
            _cd_add_status(me, apply_status)
            me.save(update_fields=["cd_status"])
            result["details"]["applied_status"] = apply_status


    elif et == CardDuelCardType.EffectType.APPLY_STATUS:
        # default target: opponent unless params says self
        st = params.get("status") or {}
        target = params.get("target") or "opponent"
        if target == "self":
            _cd_add_status(me, st)
            me.save(update_fields=["cd_status"])
            result["details"] = {"target": "self", "status": st}
        else:
            _cd_add_status(opp, st)
            opp.save(update_fields=["cd_status"])
            result["details"] = {"target": "opponent", "status": st}

    elif et == CardDuelCardType.EffectType.CLEANSE:
        target = params.get("target") or "self"
        remove_count = int(params.get("remove_count") or 1)
        types = params.get("types") or None
        if target == "opponent":
            removed = _cd_cleanse(opp, remove_count=remove_count, allowed_types=types)
            opp.save(update_fields=["cd_status"])
            result["details"] = {"target": "opponent", "removed": removed}
        else:
            removed = _cd_cleanse(me, remove_count=remove_count, allowed_types=types)
            me.save(update_fields=["cd_status"])
            result["details"] = {"target": "self", "removed": removed}

    elif et == CardDuelCardType.EffectType.GAMBLE:
        win_chance = float(params.get("win_chance", 0.5))
        import random
        is_win = random.random() < win_chance
        
        outcome_def = params.get("win") if is_win else params.get("loss")
        outcome_type = outcome_def.get("type", "")
        outcome_val = int(outcome_def.get("amount", 0))
        
        detail_msg = ""
        if outcome_type == "shield":
            my_shield = int(getattr(me, "shield_points", 0) or 0)
            me.shield_points = my_shield + outcome_val
            me.save(update_fields=["shield_points"])
            detail_msg = f"Won gamble: Gained {outcome_val} shield"
        elif outcome_type == "damage_self":
            # Direct damage to self
            dmg_info = _cd_apply_damage(game, me, outcome_val, ignore_shield=0) # Self damage usually hits shield or not? Assume hits shield.
            detail_msg = f"Lost gamble: Took {outcome_val} damage"
        else:
            detail_msg = f"Gamble result: {outcome_type} {outcome_val} (Not implemented)"
            
        result["details"] = {"gamble_win": is_win, "message": detail_msg}

    elif et == CardDuelCardType.EffectType.ANTIDOTE:
        # Cleanse specific types + Heal
        target_types = params.get("types", []) # ["poison", "burn"]
        heal_amt = int(params.get("heal", 0))
        
        cleaned_count = _cd_cleanse(me, remove_count=99, allowed_types=target_types)
        
        if heal_amt > 0:
            me.hp = max(0, int(me.hp or 0) + heal_amt)
            me.save(update_fields=["hp", "cd_status"]) # cleansed status + hp
            result["details"] = {"cleansed": cleaned_count, "healed": heal_amt}
        else:
            me.save(update_fields=["cd_status"])
            result["details"] = {"cleansed": cleaned_count}

        amt = int(params.get("amount") or 0)
        before = int(getattr(opp, "shield_points", 0) or 0)
        opp.shield_points = max(0, before - amt)
        opp.save(update_fields=["shield_points"])
        result["details"] = {"removed": min(before, amt), "shield_after": opp.shield_points}

    elif et == CardDuelCardType.EffectType.SWAP_SHIELD:
        my_shield = int(getattr(me, "shield_points", 0) or 0)
        op_shield = int(getattr(opp, "shield_points", 0) or 0)
        me.shield_points = op_shield
        opp.shield_points = my_shield
        me.save(update_fields=["shield_points"])
        opp.save(update_fields=["shield_points"])
        result["details"] = {"swapped": True, "my_shield": me.shield_points, "op_shield": opp.shield_points}

    elif et == CardDuelCardType.EffectType.HEAL_AND_SHIELD:
        heal_amt = int(params.get("heal", 2) or 2)
        shield_amt = int(params.get("shield", 2) or 2)
        me.hp = max(0, int(me.hp or 0) + heal_amt)
        me.shield_points = int(getattr(me, "shield_points", 0) or 0) + shield_amt
        me.save(update_fields=["hp", "shield_points"])
        result["details"] = {"healed": heal_amt, "shield_gained": shield_amt}

    elif et == CardDuelCardType.EffectType.DISCARD_AND_DRAW:
        # "Change (replace) up to 2 cards" -> Implementation: Discard 2 random cards (if have them), Draw 2.
        # Since we played the cycle card already, hand has N cards.
        # We discard min(N, amount) random cards, then draw that many.
        amount = int(params.get("amount", 2) or 2)
        
        current_hand = list(me.cd_hand or [])
        to_discard_count = min(len(current_hand), amount)
        
        discarded_codes = []
        if to_discard_count > 0:
            import random
            random.shuffle(current_hand)
            discarded_codes = current_hand[:to_discard_count]
            kept = current_hand[to_discard_count:]
            me.cd_hand = kept
            me.cd_discard = list(me.cd_discard or []) + discarded_codes
        
        drawn = _cd_draw(me, to_discard_count) # Draw back same number
        
        # Save happens at end of function usually, but _cd_draw saves hand/deck? 
        # _cd_draw modifies object but doesn't save.
        
        result["details"] = {
            "discarded_count": to_discard_count, 
            "drawn_count": drawn,
            "discarded": discarded_codes # optional info
        }

    elif et == CardDuelCardType.EffectType.DAMAGE:
        amt = int(params.get("amount") or 0)
        ignore_shield = int(params.get("ignore_shield") or 0)

        # add vulnerable bonus
        # subtract weaken penalty (flat)
        # subtract weaken_curse penalty (percent)
        weaken_down = int(result["details"].get("weaken_down") or 0)
        
        # Check for Weaken Curse (percent reduction)
        weaken_percent = 0
        new_status = []
        for s in (me.cd_status or []):
            if isinstance(s, dict) and s.get("type") == "weaken_curse" and int(s.get("turns_left") or 0) > 0:
                weaken_percent = max(weaken_percent, int(s.get("damage_percent") or 0)) 
                # consume? typically "next attack". Yes.
                continue
            new_status.append(s)
        
        if weaken_percent > 0:
            me.cd_status = new_status
            me.save(update_fields=["cd_status"])
        
        # 1. Base + Vulnerable + Battle Focus
        dmg_calc = amt + int(damage_bonus) + int(result["details"].get("battle_focus_bonus") or 0)
        
        # 2. Apply Percent Reduction
        if weaken_percent > 0:
            # "deals 50% less damage" -> damage * (1 - 0.5)
            # rounded down? user said "(damage is reduced by half)"
            # integer division
            reduction = (dmg_calc * weaken_percent) // 100
            dmg_calc -= reduction
            result["details"]["weaken_curse_reduction"] = reduction
            
        # 3. Apply Flat Reduction (Weaken)
        dmg_calc -= weaken_down
        
        final_amt = max(0, dmg_calc)

        # Check Counter Stance (Reflect) on Opponent
        reflected_amt = 0
        new_opp_status = []
        opp_status_changed = False
        
        for s in (opp.cd_status or []):
            if isinstance(s, dict) and s.get("type") == "counter_stance" and int(s.get("turns_left") or 0) > 0:
                # Found counter stance
                r_val = int(s.get("reflect_amount") or 0)
                reflected_amt += r_val
                
                # Consume if consume_on_hit is True (default yes for this card)
                if s.get("consume_on_hit"):
                    opp_status_changed = True
                    continue # remove from list
            new_opp_status.append(s)
            
        if opp_status_changed:
            opp.cd_status = new_opp_status
            opp.save(update_fields=["cd_status"])
            
        if reflected_amt > 0:
            # Deal damage back to ME (Attacker)
            # Should this reflect PREVENT damage to opponent? 
            # "Reflect 3 damage". Usually implies PARRY + RETURN.
            # I will reduce final_amt by reflected_amt (to min 0)
            # And deal reflected_amt to ME.
            
            # Reduce incoming
            # final_amt = max(0, final_amt - reflected_amt) # Optional: User didn't say prevent, but "Reflect" implies it.
            # Only doing Damage to Attacker per "Reflect 3 damage once" description which focuses on the damage dealt back.
            # But "Reflect" strongly implies prevention. I will NOT prevent for now to be safe (unless requested), 
            # actually "Reflect" usually prevents. let's Prevent.
            # Wait, "Counter Stance" description: "Reflect 3 damage once".
            # If I hit for 5, Reflect 3. Opponent takes 2? I take 3? Yes, this seems fair.
            
            # Reflect only up to incoming damage? Or flat 3? "Reflect 3 damage".
            # Any damage triggers 3 reflection.
            # I'll effectively prevent 3 and deal 3 back.
            prevented = min(final_amt, reflected_amt) # Prevent up to reflect amount
            # final_amt -= prevented 
            # Actually, "Reflect 3" might mean "Deal 3 back", not "Block 3".
            # "Counter" usually means "Retaliate". 
            # I will just Deal 3 back and NOT prevent, to avoid nerfing damage too much unless specified.
            # Re-read: "Reflect 3 damage once (the next time you take damage)."
            # Implementation: Deal 3 to Me. Status removed.
            
            _cd_apply_damage(game, me, reflected_amt, ignore_shield=0)
            result["details"]["reflected_damage"] = reflected_amt
            result["details"]["message"] = f"Opponent Counter Stance triggered! You took {reflected_amt} damage."
        
        dmg_info = _cd_apply_damage(game, opp, final_amt, ignore_shield=ignore_shield)
        result["details"].update({"base": amt, "final": final_amt, **dmg_info})

        # embedded status (venom strike, flame jab, etc.)
        apply_status = params.get("apply_status")
        if isinstance(apply_status, dict):
            _cd_add_status(opp, apply_status)
            opp.save(update_fields=["cd_status"])
            result["details"]["applied_status"] = apply_status

    else:
        return JsonResponse({"detail": f"Unsupported Card Duel effect: {et}"}, status=400)

    

    # Mark turn flag
    if is_bonus:
        flags["bonus_used"] = True
    else: 
        flags["action_used"] = True
    flags["last_played"] = card_type.code
    me.cd_turn_flags = flags

    me.save(update_fields=["cd_hand", "cd_deck", "cd_discard", "cd_turn_flags", "cd_status"])

    # End game if someone died
    _cd_finish_if_dead(game)

    state = game.to_public_state(for_user=request.user)
    state = enrich_draft_options(state)
    if game.mode == Game.Mode.CARD_DUEL:
        # include duel payload for this user (same structure you added earlier)
        state["card_duel"] = {
            "hand": list(me.cd_hand or []),
            "deck_count": len(me.cd_deck or []),
            "discard_count": len(me.cd_discard or []),
            "status": list(me.cd_status or []),
            "turn_flags": dict(me.cd_turn_flags or {}),
        }
    
    state["card_duel"] = _cd_build_state_for_user(game, request.user)
    state["card_duel_pick"] = state["card_duel"].get("pick", {"active": False})

    return JsonResponse({"ok": True, "result": result, "game_state": state})

def _cd_tick_statuses_start_of_turn(player: PlayerInGame) -> dict:
    """
    Applies start-of-turn effects and decreases turns_left.
    Supported:
      - poison: tick_damage
      - burn: tick_damage
      - regen: tick_heal
      - focus: extra_draw (handled by returning draw_bonus)
      - bless/vulnerable/silence/weaken: only duration decrement here
    Returns: {"damage_taken": X, "healed": Y, "draw_bonus": Z, "expired": [types...]}
    """
    cur = list(player.cd_status or [])
    new_list = []
    dmg = 0
    heal = 0
    draw_bonus = 0
    expired = []

    for s in cur:
        if not isinstance(s, dict):
            continue

        turns_left = int(s.get("turns_left") or s.get("turns") or 0)
        if turns_left <= 0:
            continue

        stype = s.get("type")
        stacks = int(s.get("stacks") or 1)

        # Apply tick effects at start of turn
        if stype == "poison":
            dmg += int(s.get("tick_damage") or 1) * stacks
        elif stype == "burn":
            dmg += int(s.get("tick_damage") or 2) * stacks
        elif stype == "regen":
            heal += int(s.get("tick_heal") or 1) * stacks
        elif stype == "focus":
            draw_bonus += int(s.get("extra_draw") or 1) * stacks

        # decrement duration
        turns_left -= 1
        s["turns_left"] = turns_left

        if turns_left > 0:
            new_list.append(s)
        else:
            if stype:
                expired.append(stype)

    player.cd_status = new_list
    return {"damage_taken": dmg, "healed": heal, "draw_bonus": draw_bonus, "expired": expired}


def _cd_apply_bless_damage_reduction(defender: PlayerInGame, incoming: int) -> int:
    """
    Bless reduces incoming damage by N per stack (damage_reduce).
    """
    incoming = max(0, int(incoming or 0))
    reduce_total = 0
    for s in (defender.cd_status or []):
        if isinstance(s, dict) and s.get("type") == "bless" and int(s.get("turns_left") or 0) > 0:
            reduce_total += int(s.get("damage_reduce") or 0) * int(s.get("stacks") or 1)
    return max(0, incoming - reduce_total)


@login_required
@require_POST
@transaction.atomic
def card_duel_end_turn(request, game_id: int):
    """
    Ends the current player's turn in Card Duel.
    Handles start-of-turn effects for the next player (ticks, damage/heal).
    """
    game = get_object_or_404(Game, id=game_id)

    if game.mode != Game.Mode.CARD_DUEL:
        return JsonResponse({"detail": "Not a Card Duel game."}, status=400)

    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()
    if me.cd_picks_done < 5:
        return JsonResponse({"detail": "Finish selecting your starting cards first."}, status=400)

    if not me:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    # Turn check
    current = game.current_player
    if not current or current.id != me.id:
        return JsonResponse(
            {"detail": "It is not your turn.", "game_state": game.to_public_state(for_user=request.user)},
            status=403,
        )

    # Must have played at least one card? (optional rule)
    # If you want to allow pass, remove this block.
    flags = dict(me.cd_turn_flags or {})
    if not flags.get("action_used") and not flags.get("bonus_used"):
        # allow pass if you want -> comment out to force play
        pass

    # Advance turn index to next alive player (2-player but safe)
    players_ordered = list(game.players.order_by("turn_order"))
    if not players_ordered:
        return JsonResponse({"detail": "No players."}, status=400)

    # determine next alive index
    n = len(players_ordered)
    cur_idx = int(game.current_turn_index or 0) % n

    next_idx = None
    for step in range(1, n + 1):
        cand = players_ordered[(cur_idx + step) % n]
        if cand.is_alive:
            next_idx = (cur_idx + step) % n
            break

    if next_idx is None:
        # nobody alive -> finish
        game.status = Game.Status.FINISHED
        game.save(update_fields=["status"])
        return JsonResponse({"ok": True, "game_state": game.to_public_state(for_user=request.user)})

    # Set next turn
    game.current_turn_index = next_idx
    game.save(update_fields=["current_turn_index"])

    # Start-of-turn processing for the next player
    next_player = players_ordered[next_idx]
    start_info = _cd_tick_statuses_start_of_turn(next_player)

    # Apply tick heal
    if start_info["healed"] > 0:
        next_player.hp = max(0, int(next_player.hp or 0) + int(start_info["healed"]))

    # Apply tick damage with Bless reduction
    if start_info["damage_taken"] > 0:
        reduced = _cd_apply_bless_damage_reduction(next_player, int(start_info["damage_taken"]))
        if reduced > 0:
            # shield-aware damage
            _cd_apply_damage(game, next_player, reduced, ignore_shield=0)
        start_info["damage_taken_final"] = reduced
    else:
        start_info["damage_taken_final"] = 0

    # Draw 1 + focus bonus
    draw_total = 1 + int(start_info.get("draw_bonus") or 0)
    drawn = _cd_draw(next_player, draw_total)
    start_info["draw_total"] = draw_total
    start_info["drawn"] = drawn

    # Reset next player's turn flags
    prev_last = (next_player.cd_turn_flags or {}).get("last_played")
    next_player.cd_turn_flags = {
        "action_used": False,
        "bonus_used": False,
        "draws_this_turn": 0,
        "last_played": prev_last,
    }

    # Persist status list (duration decremented) + hp changes + deck/hand changes + flags
    next_player.save(update_fields=["cd_status", "hp", "cd_deck", "cd_hand", "cd_turn_flags"])

    # End game if someone died from tick damage
    _cd_finish_if_dead(game)

    # Build response state
    state = game.to_public_state(for_user=request.user)
    state = enrich_draft_options(state)
    if game.mode == Game.Mode.CARD_DUEL:
        # include duel payload for the requester
        state["card_duel"] = {
            "hand": list(me.cd_hand or []),
            "deck_count": len(me.cd_deck or []),
            "discard_count": len(me.cd_discard or []),
            "status": list(me.cd_status or []),
            "turn_flags": dict(me.cd_turn_flags or {}),
        }

    return JsonResponse(
        {
            "ok": True,
            "result": {
                "next_player_id": next_player.id,
                "start_of_turn": start_info,
            },
            "game_state": state,
        }
    )

@login_required
@require_POST
@transaction.atomic
def card_duel_pick(request, game_id: int):
    """
    Handles the initial draft phase picking logic for Card Duel.
    Adds chosen card to hand and deals new options if needed.
    """
    game = Game.objects.select_for_update().get(id=game_id)

    if game.mode != Game.Mode.CARD_DUEL:
        return JsonResponse({"detail": "Not a Card Duel game."}, status=400)
    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = game.players.select_related("user").filter(user=request.user).first()
    if not me:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    MAX_PICKS = 5
    if me.cd_picks_done >= MAX_PICKS:
        return JsonResponse({"detail": "You already finished selecting cards."}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
        code = str(data.get("code") or "").strip()
    except Exception:
        return JsonResponse({"detail": "Invalid payload."}, status=400)

    options = list(me.cd_pick_options or [])
    if code not in options:
        return JsonResponse({"detail": "Chosen card is not in your current options."}, status=400)

    # Add chosen card to hand
    me.cd_hand = list(me.cd_hand or [])
    me.cd_hand.append(code)

    # Return unchosen cards back into deck
    rest = [c for c in options if c != code]
    me.cd_deck = list(me.cd_deck or []) + rest
    random.shuffle(me.cd_deck)

    # Progress
    me.cd_picks_done += 1
    if me.cd_picks_done < MAX_PICKS:
        # Deal next 3 reserved options
        me.cd_pick_options = card_duel.deal_cd_pick_options(me, k=3)
    else:
        me.cd_pick_options = []

    me.save(update_fields=["cd_hand", "cd_deck", "cd_picks_done", "cd_pick_options"])
    state = game.to_public_state(for_user=request.user)
    state = enrich_draft_options(state)
    state["card_duel"] = _cd_build_state_for_user(game, request.user)
    state["card_duel_pick"] = state["card_duel"].get("pick", {"active": False})
    return JsonResponse({"ok": True, "game_state": state})



# ---------- helpers ----------

def _cd_card_payload_from_code(code: str):
    """
    Converts a stored Card Duel card code (e.g. CD_STRIKE_5) into a dict:
    {code, title, image_url}
    """
    from .models import CardDuelCardType  # adjust import if your models path differs

    t = CardDuelCardType.objects.filter(code=code).first()
    title = t.name if t else code
    img = _cd_image_filename(title)
    return {
        "code": code,
        "title": title,
        "image_url": static(f"images/CardDuelCards/{img}"),
    }

def _safe_len(x):
    return len(x) if x else 0

def _cd_image_filename(card_name: str) -> str:
    """
    Maps card names from seed data to actual filenames in static/images/CardDuelCards/
    """
    name = (card_name or "").strip()
    
    # Mapping of card names to their image files based on FUNCTION/EFFECT
    # Each card is mapped to an image that represents what it DOES
    mapping = {
        # === PLUS STATUS CARDS (Buffs/Healing) ===
        "Battle Focus": "BattleFocus.png",        # +2 damage for 2 turns
        "Iron Skin": "IronSkin.png",              # Gain 6 shield
        "Purify Aura": "PurifyAura.png",          # Remove all negative effects
        "Regen Brew": "RegenBrew.png",            # Heal 2 HP for 2 turns (regen)
        "Heal": "RestoreHp.png",                  # Restore 5 HP instantly
        
        # === MINUS STATUS CARDS (Debuffs/Damage over time) ===
        "Poison": "PoisonNeedle.png",             # 1 damage for 3 turns
        "Burn": "BurningMark.png",                # 2 damage for 2 turns
        "Weaken": "WeakenCurse.png",              # Target deals 2 less damage
        "Vulnerable": "StunShock.png",            # Target takes +1 damage (using stun image)
        "Silence Seal": "SilenceSeal.png",        # Block ALL cards for 1 turn
        "Stun Shock": "StunShock.png",            # Block action cards for 1 turn
        
        # === NEUTRAL CARDS (Utility) ===
        "Adrenaline": "Adrenaline.png",           # Draw +1 card next turn
        "Card Cycle": "CardCycle.png",            # Change up to 2 cards in hand
        "Guard Swap": "GuardSwap.png",            # Swap shields with enemy
        "Quick Fix": "QuickFix.png",              # Heal 2 + Shield 2
        "Weaken Curse": "WeakenCurse.png",        # Enemy deals 50% less damage
        
        # === BONUS CARDS (Special effects) ===
        "Amplify": "Amplify.png",                 # Next heal +3 HP
        "Antidote Kit": "AntidoteKit.png",        # Remove poison & burn, heal 1
        "Counter Stance": "CounterStance.png",    # Reflect 3 damage once
        "Gamble Coin": "GambleCoin.png",          # 50% shield +8 OR take 3 damage
        "Lucky Draw": "LuckyDraw.png",            # Draw 2 cards
        
        # === LEGACY BONUS CARDS (Attack + Status) ===
        "Venom Strike": "PoisonNeedle.png",       # Deal 3 damage + poison (function: poison attack)
        "Flame Jab": "BurningMark.png",           # Deal 3 damage + burn (function: burn attack)
        "Holy Light": "RestoreHp.png",            # Heal 3 + regen (function: healing)
        "Crippling Shot": "WeakenCurse.png",      # Deal 4 damage + weaken (function: weaken attack)
        
        # === OTHER ATTACK CARDS ===
        "Pierce": "Strike.png",                   # Attack card (piercing damage)
        "Strike": "Strike.png",                   # Basic attack
        "Sunder": "StunShock.png",                # Attack with stun effect
        
        # === LEGACY CARDS (from old database) ===
        "Cleanse": "AntidoteKit.png",             # Remove negative effects (similar to Purify Aura)
        "Tactical Draw": "CardCycle.png",         # Draw/cycle cards
        "Bless": "PurifyAura.png",                # Buff/blessing effect
        "Focus": "BattleFocus.png",               # Focus/concentration buff
        "Regen": "RegenBrew.png",                 # Regeneration effect
        "Shield Up": "IronSkin.png",              # Shield/defense buff
    }
    
    if name in mapping:
        return mapping[name]

    # Fallback to simple removal of spaces if not found
    base = re.sub(r"[^A-Za-z0-9]+", " ", name).title().replace(" ", "")
    return f"{base}.png"

def _json_ok(game, request, extra=None):
    payload = {"ok": True, "game_state": game.to_public_state(for_user=request.user)}
    if extra:
        payload.update(extra)
    return JsonResponse(payload)


def _json_err(game, request, msg, status=400, extra=None):
    payload = {"ok": False, "detail": msg}
    if game is not None:
        payload["game_state"] = game.to_public_state(for_user=request.user)
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)


def _get_me(game, request):
    # Your project uses game.players with user relation (see to_public_state)
    return game.players.select_related("user").filter(user=request.user).first()


def _interaction_bonus(my_choice: str, opp_choice: str) -> int:
    # Attack > Bluff, Bluff > Defend, Defend > Attack
    if my_choice == opp_choice:
        return 0
    if my_choice == "attack" and opp_choice == "bluff":
        return 1
    if my_choice == "bluff" and opp_choice == "defend":
        return 1
    if my_choice == "defend" and opp_choice == "attack":
        return 1
    return 0


def _prediction_points(my_prediction: str, opp_choice: str) -> int:
    return 1 if my_prediction == opp_choice else 0


def _compute_scores(a_choice, a_pred, b_choice, b_pred):
    a = _prediction_points(a_pred, b_choice) + _interaction_bonus(a_choice, b_choice)
    b = _prediction_points(b_pred, a_choice) + _interaction_bonus(b_choice, a_choice)
    return a, b


def _end_turn_safely(game):
    """Advance turn while skipping eliminated players."""
    if hasattr(game, "advance_turn") and callable(getattr(game, "advance_turn")):
        game.advance_turn()
        return

    game.current_turn_index = (int(game.current_turn_index or 0) + 1) % max(game.players.count(), 1)
    game.save(update_fields=["current_turn_index"])


def _apply_hp_damage_with_shield(player, dmg: int) -> bool:
    """
    Returns True if blocked by shield_points, else False.
    Uses your existing shield_points attribute seen in to_public_state().
    """
    if dmg <= 0:
        return False

    shield = int(getattr(player, "shield_points", 0) or 0)
    if shield > 0:
        player.shield_points = max(0, shield - dmg)
        player.save(update_fields=["shield_points"])
        return True

    # apply hp
    player.hp = max(0, player.hp - dmg)
    if player.hp <= 0:
        player.hp = 0
        player.is_alive = False
        player.save(update_fields=["hp", "is_alive"])
    else:
        player.save(update_fields=["hp"])
    return False


# =========================================================
# 1) Select opponent (initiator only)
# =========================================================
@require_POST
@transaction.atomic
def duel_select_opponent(request, game_id):
    """
    Initiator selects the opponent for the duel.
    """
    game = get_object_or_404(Game, id=game_id)
    me = _get_me(game, request)
    if me is None:
        return _json_err(None, request, "Not in this game.", status=403)

    pd = game.pending_duel or None
    if not pd or pd.get("type") != "prediction":
        return _json_err(game, request, "No active duel.", status=409)

    initiator_id = pd.get("initiator_id") or pd.get("for_player_id")
    if me.id != initiator_id:
        return _json_err(game, request, "Only the duel initiator can choose the opponent.", status=403)

    if pd.get("status") != "choose_opponent":
        return _json_err(game, request, "Duel is not in opponent selection phase.", status=409)

    opponent_id = request.POST.get("opponent_id")
    if not opponent_id:
        return _json_err(game, request, "Missing opponent_id.", status=400)

    try:
        opponent_id_int = int(opponent_id)
    except ValueError:
        return _json_err(game, request, "Invalid opponent_id.", status=400)

    opponent = game.players.select_related("user").filter(id=opponent_id_int, is_alive=True).first()
    if opponent is None or opponent.id == me.id:
        return _json_err(game, request, "Invalid opponent.", status=400)

    # Set opponent + move to commit phase
    pd["opponent_id"] = opponent.id
    pd["status"] = "commit"
    pd.setdefault("choices", {})
    pd.setdefault("predictions", {})

    game.pending_duel = pd
    game.save(update_fields=["pending_duel"])

    return _json_ok(game, request, extra={"phase": "commit"})


# =========================================================
# 2) Commit (hidden choice) with costs
# =========================================================
@require_POST
@transaction.atomic
def duel_commit(request, game_id):
    """
    Players commit their action (Attack/Defend/Bluff).
    Deducts coins (Defend) or uses card (Bluff) as cost.
    """
    game = get_object_or_404(Game, id=game_id)
    me = _get_me(game, request)
    if me is None:
        return _json_err(None, request, "Not in this game.", status=403)

    pd = game.pending_duel or None
    if not pd or pd.get("type") != "prediction":
        return _json_err(game, request, "No active duel.", status=409)

    if pd.get("status") != "commit":
        return _json_err(game, request, "Duel is not in commit phase.", status=409)

    initiator_id = pd.get("initiator_id") or pd.get("for_player_id")
    opponent_id = pd.get("opponent_id")
    if me.id not in [initiator_id, opponent_id]:
        return _json_err(game, request, "You are not a duel participant.", status=403)

    choice = (request.POST.get("choice") or "").strip().lower()
    if choice not in ["attack", "defend", "bluff"]:
        return _json_err(game, request, "Invalid choice.", status=400)

    choices = pd.setdefault("choices", {})
    me_key = str(me.id)

    if me_key in choices:
        return _json_err(game, request, "You already committed.", status=409)

    # ---- costs ----
    if choice == "defend":
        if me.coins < 1:
            return _json_err(game, request, "Not enough coins for Defend.", status=400)
        me.coins -= 1
        me.save(update_fields=["coins"])

    if choice == "bluff":
        # "any support card": consume any unused card from inventory
        card = me.cards.select_related("card_type").filter(is_used=False).first()
        if card is None:
            return _json_err(game, request, "Bluff requires any support card.", status=400)
        card.is_used = True
        card.save(update_fields=["is_used"])

    choices[me_key] = choice
    pd["choices"] = choices

    # advance if both committed
    if str(initiator_id) in choices and str(opponent_id) in choices:
        pd["status"] = "predict"

    game.pending_duel = pd
    game.save(update_fields=["pending_duel"])

    return _json_ok(game, request, extra={"phase": pd.get("status")})


# =========================================================
# 3) Predict (then compute winner/draw; winner chooses reward)
# =========================================================
@require_POST
@transaction.atomic
def duel_predict(request, game_id):
    """
    Players predict the opponent's action.
    Computes scores and determines winner/draw if both predicted.
    """
    game = get_object_or_404(Game, id=game_id)
    me = _get_me(game, request)
    if me is None:
        return _json_err(None, request, "Not in this game.", status=403)

    pd = game.pending_duel or None
    if not pd or pd.get("type") != "prediction":
        return _json_err(game, request, "No active duel.", status=409)

    if pd.get("status") != "predict":
        return _json_err(game, request, "Duel is not in predict phase.", status=409)

    initiator_id = pd.get("initiator_id") or pd.get("for_player_id")
    opponent_id = pd.get("opponent_id")
    if me.id not in [initiator_id, opponent_id]:
        return _json_err(game, request, "You are not a duel participant.", status=403)

    pred = (request.POST.get("prediction") or "").strip().lower()
    if pred not in ["attack", "defend", "bluff"]:
        return _json_err(game, request, "Invalid prediction.", status=400)

    predictions = pd.setdefault("predictions", {})
    me_key = str(me.id)
    if me_key in predictions:
        return _json_err(game, request, "You already predicted.", status=409)

    predictions[me_key] = pred
    pd["predictions"] = predictions

    # if both predicted -> resolve
    if str(initiator_id) in predictions and str(opponent_id) in predictions:
        choices = pd.get("choices") or {}
        if str(initiator_id) not in choices or str(opponent_id) not in choices:
            return _json_err(game, request, "Missing duel choices.", status=409)

        a_choice = choices[str(initiator_id)]
        b_choice = choices[str(opponent_id)]
        a_pred = predictions[str(initiator_id)]
        b_pred = predictions[str(opponent_id)]

        a_score, b_score = _compute_scores(a_choice, a_pred, b_choice, b_pred)

        reveal = {
            "initiator_choice": a_choice,
            "opponent_choice": b_choice,
            "initiator_prediction": a_pred,
            "opponent_prediction": b_pred,
            "scores": {"initiator": a_score, "opponent": b_score},
        }

        pd["reveal"] = reveal

        if a_score == b_score:
            pd["is_draw"] = True
            pd["winner_id"] = None
            pd["loser_id"] = None
            pd["status"] = "resolved"

            # clear duel + end turn
            game.pending_duel = None
            game.save(update_fields=["pending_duel"])
            _end_turn_safely(game)
            return _json_ok(game, request, extra={"resolved": True, "draw": True})

        # winner exists -> winner must choose reward
        if a_score > b_score:
            winner_id, loser_id = initiator_id, opponent_id
        else:
            winner_id, loser_id = opponent_id, initiator_id

        pd["is_draw"] = False
        pd["winner_id"] = int(winner_id)
        pd["loser_id"] = int(loser_id)
        pd["status"] = "winner_choice"

    game.pending_duel = pd
    game.save(update_fields=["pending_duel"])
    return _json_ok(game, request, extra={"phase": pd.get("status")})


# =========================================================
# 4) Winner chooses reward (applies effects, clears duel, ends turn)
# =========================================================
@require_POST
@transaction.atomic
def duel_choose_reward(request, game_id):
    """
    Winner selects a reward (coins, damage, pushback, steal card).
    Applies the effect and ends the turn.
    """
    game = get_object_or_404(Game, id=game_id)
    me = _get_me(game, request)
    if me is None:
        return _json_err(None, request, "Not in this game.", status=403)

    pd = game.pending_duel or None
    if not pd or pd.get("type") != "prediction":
        return _json_err(game, request, "No active duel.", status=409)

    if pd.get("status") != "winner_choice":
        return _json_err(game, request, "Duel is not waiting for winner choice.", status=409)

    winner_id = pd.get("winner_id")
    loser_id = pd.get("loser_id")
    if not winner_id or not loser_id:
        return _json_err(game, request, "Duel winner/loser not set.", status=409)

    if me.id != int(winner_id):
        return _json_err(game, request, "Only the duel winner can choose the reward.", status=403)

    action = (request.POST.get("action") or "").strip().lower()
    if action not in ["coins", "hp", "push_back", "steal_card"]:
        return _json_err(game, request, "Invalid action.", status=400)

    winner = game.players.filter(id=int(winner_id)).first()
    loser = game.players.filter(id=int(loser_id)).first()
    if winner is None or loser is None:
        return _json_err(game, request, "Players not found.", status=409)

    # Effects object (same style as your engine)
    effects = {
        "coins_delta": 0,
        "hp_delta": 0,
        "extra": {
            "duel": {
                "type": "prediction",
                "winner_id": winner.id,
                "loser_id": loser.id,
                "reward_action": action,
                "reveal": pd.get("reveal"),
            }
        },
    }

    if action == "coins":
        winner.coins += 3
        winner.save(update_fields=["coins"])
        effects["coins_delta"] = 3

    elif action == "hp":
        blocked = _apply_hp_damage_with_shield(loser, 1)
        effects["extra"]["duel"]["hp_blocked_by_shield"] = blocked
        effects["extra"]["duel"]["loser_hp_after"] = loser.hp

    elif action == "push_back":
        loser.position = max(0, int(loser.position or 0) - 1)
        loser.save(update_fields=["position"])
        effects["extra"]["duel"]["loser_pushed_back"] = 1
        effects["extra"]["duel"]["loser_position_after"] = loser.position

    elif action == "steal_card":
        stolen = loser.cards.select_related("card_type").filter(is_used=False).order_by("?").first()
        if stolen:
            # Your inventory relation is me.cards, so card likely has FK to player model named "player"
            # We try common names safely.
            if hasattr(stolen, "player_id"):
                stolen.player = winner
            elif hasattr(stolen, "owner_id"):
                stolen.owner = winner
            else:
                return _json_err(game, request, "Card model has no owner/player field.", status=500)

            stolen.save()
            effects["extra"]["duel"]["stolen_card_id"] = stolen.id
            effects["extra"]["duel"]["stolen_card_code"] = stolen.card_type.code
        else:
            effects["extra"]["duel"]["no_card_to_steal"] = True

    # Clear duel and end turn
    game.pending_duel = None
    game.save(update_fields=["pending_duel"])
    _end_turn_safely(game)

    return _json_ok(game, request, extra={"effects": effects, "resolved": True})

@login_required
@require_POST
@transaction.atomic
def duel_skip(request, game_id: int):
    """
    Skips the current duel phase (if allowed/safe to skip).
    Only participants or initiator can skip.
    """
    game = get_object_or_404(Game, id=game_id)
    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    me = _get_me(game, request)
    if me is None:
        return JsonResponse({"detail": "You are not in this game."}, status=403)

    pd = getattr(game, "pending_duel", None)
    if not pd:
        return JsonResponse({"detail": "No pending duel."}, status=400)

    # Only a duel participant (or initiator) can skip/close it
    initiator_id = pd.get("initiator_id") or pd.get("for_player_id")
    opponent_id = pd.get("opponent_id")

    participants = {str(x) for x in [initiator_id, opponent_id] if x}
    if str(me.id) not in participants:
        return JsonResponse({"detail": "It is not your duel."}, status=403)

    # Clear duel and skip/advance turn (same behavior style as gun_skip)
    game.pending_duel = None
    game.save(update_fields=["pending_duel"])

    # Prefer your helper (handles end_turn if you have it)
    _end_turn_safely(game)

    return JsonResponse({
        "action": "duel_skip",
        "game_state": game.to_public_state(for_user=request.user),
    })



# ============================
# GAME CHAT API
# ============================

@login_required
@require_GET
def game_chat_messages(request, game_id: int):
    """
    Returns the last 50 chat messages for the game.
    """
    game = get_object_or_404(Game, id=game_id)

    # only players or host can read chat
    is_player = game.players.filter(user=request.user).exists()
    is_host = (game.host == request.user)
    if not (is_player or is_host):
        return JsonResponse({"detail": "Forbidden"}, status=403)

    messages_qs = game.chat_messages.select_related("user").order_by("created_at")[:50]

    data = [
        {
            "id": m.id,
            "user": m.user.username,
            "message": m.message,
            "created_at": m.created_at.isoformat(),
            "is_you": (m.user_id == request.user.id),
        }
        for m in messages_qs
    ]

    return JsonResponse({"messages": data})


@login_required
@require_POST
@transaction.atomic
def game_chat_send(request, game_id: int):
    """
    Sends a new chat message to the game.
    """
    game = get_object_or_404(Game, id=game_id)

    # only players or host can send
    is_player = game.players.filter(user=request.user).exists()
    is_host = (game.host == request.user)
    if not (is_player or is_host):
        return JsonResponse({"detail": "Forbidden"}, status=403)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
        text = (body.get("message") or "").strip()
    except Exception:
        return JsonResponse({"detail": "Invalid payload"}, status=400)

    if not text:
        return JsonResponse({"detail": "Message is empty"}, status=400)

    if len(text) > 500:
        return JsonResponse({"detail": "Message too long"}, status=400)

    msg = GameChatMessage.objects.create(
        game=game,
        user=request.user,
        message=text,
    )

    return JsonResponse({
        "id": msg.id,
        "user": msg.user.username,
        "message": msg.message,
        "created_at": msg.created_at.isoformat(),
        "is_you": True,
    })


def faq(request):
    """FAQ page view"""
    return render(request, "faq.html")
