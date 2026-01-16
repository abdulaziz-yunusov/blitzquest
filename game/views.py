import secrets
import string
import json
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login, get_user_model
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.templatetags.static import static

from django.db import transaction
from django.http import HttpResponse



from .forms import GameCreateForm, JoinGameForm

from .models import (
    Game,
    PlayerInGame,
    BoardTile,
    SupportCardInstance,
    SupportCardType,
    GameChatMessage,   # ✅ CHAT
)


def signup(request):
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


def generate_game_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

SURVIVAL_LEN = 35

def _tile_weights_for(game: Game):
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
    return render(request, "home.html")


@login_required
def game_list(request):
    waiting_games = Game.objects.filter(status=Game.Status.WAITING).order_by("-created_at")
    my_games = Game.objects.filter(players__user=request.user).distinct().order_by("-created_at")

    context = {"waiting_games": waiting_games, "my_games": my_games}
    return render(request, "game_list.html", context)


@login_required
def game_create(request):
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
    if request.method == "POST":
        form = JoinGameForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"]

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
    else:
        form = JoinGameForm()

    return render(request, "game_join.html", {"form": form})


@login_required
def game_detail(request, game_id: int):
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

    # 1) Ensure support cards exist
    seed_support_cards()

    # 2) Generate the board (same rule you had)
    if game.mode in (Game.Mode.SURVIVAL, Game.Mode.DRAFT):
        create_default_board_for_game(game, enabled_tiles=game.enabled_tiles)
    else:
        game.generate_random_board()

    # 3) Start based on mode (Draft stays DRAFTING; others become ACTIVE)
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
    game = get_object_or_404(Game, id=game_id)

    players = game.players.select_related("user")
    is_player = players.filter(user=request.user).exists()
    is_host = (game.host == request.user)

    if not (is_player or is_host):
        return JsonResponse({"detail": "Forbidden"}, status=403)

    state = game.to_public_state(for_user=request.user)
    state = enrich_draft_options(state)
    return JsonResponse(state)


@login_required
@require_POST
@transaction.atomic
def game_roll(request, game_id: int):
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
    return render(request, "game_board.html", context)


@login_required
@require_POST
def use_card(request, game_id):
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

# ---------- helpers ----------

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
