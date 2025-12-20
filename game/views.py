import secrets
import string
import json
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST
from django.db import transaction
from django.http import HttpResponse


from .models import Game, PlayerInGame, BoardTile, SupportCardInstance, SupportCardType
from .forms import GameCreateForm, JoinGameForm


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


def generate_game_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_default_board_for_game(game: Game, enabled_tiles=None):
    enabled_tiles = enabled_tiles if enabled_tiles is not None else (game.enabled_tiles or [])

    if not enabled_tiles:
        enabled_tiles = [
            value for (value, _label) in BoardTile.TileType.choices
            if value not in (BoardTile.TileType.START, BoardTile.TileType.FINISH, BoardTile.TileType.SAFE)
        ]

    tiles = []
    last_index = game.board_length - 1

    for pos in range(game.board_length):
        if pos == 0:
            tile_type = BoardTile.TileType.START
        elif pos == last_index:
            tile_type = BoardTile.TileType.FINISH
        else:
            tile_type = random.choice(enabled_tiles)

        tiles.append(BoardTile(game=game, position=pos, tile_type=tile_type))

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

            create_default_board_for_game(game, enabled_tiles=game.enabled_tiles)

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

    seed_support_cards()
    game.generate_random_board()

    game.current_turn_index = 0
    game.status = Game.Status.ACTIVE
    game.save(update_fields=["current_turn_index", "status"])

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
    game.save(update_fields=["status", "pending_question"])

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
        body = json.loads(request.body.decode("utf-8"))
        choice_index = int(body.get("choice_index"))
    except Exception:
        return JsonResponse({"detail": "Invalid payload."}, status=400)

    correct_index = int(pq.get("correct_index"))
    is_correct = (choice_index == correct_index)

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
        "result": {"correct": is_correct},
        "game_state": state,
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

    if game.status != Game.Status.ACTIVE:
        messages.info(request, "Game is not active yet.")
        return redirect("game:game_detail", game_id=game.id)

    state = game.to_public_state(for_user=request.user)

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
        me.hp = min(3, me.hp + 2)
        me.save(update_fields=["hp"])

    elif et == "shield":
        me.shield_points = me.shield_points + 2
        me.save(update_fields=["shield_points"])

    elif et == "reroll":
        me.extra_rolls = getattr(me, "extra_rolls", 0) + 1
        me.save(update_fields=["extra_rolls"])

    elif et == "swap_position":
        if not target_player_id:
            return JsonResponse({"detail": "target_player_id is required for swap."}, status=400)

        target = game.players.filter(id=target_player_id, is_alive=True).first()
        if not target:
            return JsonResponse({"detail": "Target player not found."}, status=404)

        if abs(target.position - me.position) != 1:
            return JsonResponse({"detail": "Target player must be adjacent."}, status=400)

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
