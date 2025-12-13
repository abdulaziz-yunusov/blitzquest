import secrets
import string

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST
from django.db import transaction


from .models import Game, PlayerInGame, BoardTile
from .forms import GameCreateForm, JoinGameForm

def signup(request):
    """
    Simple user registration using Django's built-in UserCreationForm.
    After signup, user is logged in and redirected to home.
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


def generate_game_code(length: int = 6) -> str:
    """Generate a random alphanumeric game code like ABC123."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_default_board_for_game(game: Game):
    """
    Create a simple default board:
    - position 0: START
    - last tile: FINISH
    - some tiles as HEAL/TRAP/DUEL/QUESTION for testing.
    You can adjust this later to match your PPT design exactly.
    """
    tiles = []
    last_index = game.board_length - 1

    for pos in range(game.board_length):
        if pos == 0:
            tile_type = BoardTile.TileType.START
        elif pos == last_index:
            tile_type = BoardTile.TileType.FINISH
        else:
            # Simple pattern: every 5th = HEAL, 7th = TRAP, 9th = DUEL, others = QUESTION
            if pos % 9 == 0:
                tile_type = BoardTile.TileType.DUEL
            elif pos % 7 == 0:
                tile_type = BoardTile.TileType.TRAP
            elif pos % 5 == 0:
                tile_type = BoardTile.TileType.HEAL
            else:
                tile_type = BoardTile.TileType.QUESTION

        tiles.append(BoardTile(game=game, position=pos, tile_type=tile_type))

    BoardTile.objects.bulk_create(tiles)


def home(request):
    """
    Landing page.
    Shows quick links and some basic info.
    """
    return render(request, "home.html")


@login_required
def game_list(request):
    """
    List games you can see: waiting and maybe your active ones.
    """
    waiting_games = Game.objects.filter(status=Game.Status.WAITING).order_by("-created_at")
    my_games = Game.objects.filter(players__user=request.user).distinct().order_by("-created_at")

    context = {
        "waiting_games": waiting_games,
        "my_games": my_games,
    }
    return render(request, "game_list.html", context)


@login_required
def game_create(request):
    """
    Create a new game; user becomes host and first player.
    """
    if request.method == "POST":
        form = GameCreateForm(request.POST)
        if form.is_valid():
            game: Game = form.save(commit=False)

            # Generate a unique code
            code = None
            while True:
                candidate = generate_game_code()
                if not Game.objects.filter(code=candidate).exists():
                    code = candidate
                    break

            game.code = code
            game.host = request.user
            game.save()

            # Create basic board tiles
            create_default_board_for_game(game)

            # Create first player in game (host)
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
    Join an existing waiting game by code.
    """
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

            # Check if already in this game
            if PlayerInGame.objects.filter(game=game, user=request.user).exists():
                messages.info(request, "You are already in this game.")
                return redirect("game:game_detail", game_id=game.id)

            # Check room
            current_players = game.players.count()
            if current_players >= game.max_players:
                messages.error(request, "Game is full.")
                return redirect("game:game_join")

            # Assign turn_order as current count
            PlayerInGame.objects.create(
                game=game,
                user=request.user,
                turn_order=current_players,
                hp=3,
                coins=0,
                position=0,
                is_alive=True,
            )

            messages.success(request, f"You joined game {game.code}.")
            return redirect("game:game_detail", game_id=game.id)
    else:
        form = JoinGameForm()

    return render(request, "game_join.html", {"form": form})


@login_required
def game_detail(request, game_id: int):
    """
    Acts as lobby (when waiting) and later as main board screen (when active).
    """
    game = get_object_or_404(Game, id=game_id)
    players = game.players.select_related("user").order_by("turn_order")
    tiles = game.tiles.order_by("position")

    # Ensure only participants (or host) can see this game
    if not players.filter(user=request.user).exists():
        # If user is host but not in players for some reason, allow
        if game.host != request.user:
            messages.error(request, "You are not a player in this game.")
            return redirect("game:game_list")

    is_host = (game.host == request.user)
    can_start = (
        is_host
        and game.status == Game.Status.WAITING
        and players.count() >= 2
    )

    # Use model helper to build a full state dict
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

    # 1) generate a fresh random board
    game.generate_random_board()

    # 2) reset turn index and status
    game.current_turn_index = 0
    game.status = Game.Status.ACTIVE
    game.save(update_fields=["current_turn_index", "status"])

    messages.success(request, "Game started! Board generated.")
    return redirect("game:game_board", game_id=game.id)

@login_required
def game_delete(request, game_id: int):
    """
    Host can delete a game (only when not active).
    """
    game = get_object_or_404(Game, id=game_id)

    if request.user != game.host:
        messages.error(request, "Only the host can delete this game.")
        return redirect("game:game_detail", game_id=game.id)

    if request.method == "POST":
        if game.status == Game.Status.ACTIVE:
            messages.error(request, "You cannot delete an active game. End it first.")
            return redirect("game:game_detail", game_id=game.id)

        game_code = game.code
        game.delete()
        messages.success(request, f"Game {game_code} has been deleted.")
        return redirect("game:game_list")

    # If someone hits this URL via GET, just bounce back
    return redirect("game:game_detail", game_id=game.id)

@login_required
def game_end(request, game_id: int):
    """
    Host can manually end an active game.
    Optionally assign winner if only one player is alive.
    """
    game = get_object_or_404(Game, id=game_id)

    if request.user != game.host:
        messages.error(request, "Only the host can end this game.")
        return redirect("game:game_detail", game_id=game.id)

    if request.method == "POST":
        if game.status != Game.Status.ACTIVE:
            messages.error(request, "Only active games can be ended.")
            return redirect("game:game_detail", game_id=game.id)

        # Simple optional winner detection: if only one alive, mark them as winner
        alive_players = game.players.filter(is_alive=True).order_by("turn_order")
        if alive_players.count() == 1:
            game.winner = alive_players.first()
        else:
            # No clear single winner; leave winner as-is (can be null)
            game.winner = game.winner

        game.status = Game.Status.FINISHED
        game.save()

        messages.success(request, "Game has been ended.")
        return redirect("game:game_detail", game_id=game.id)

    # Any GET to this URL just returns to detail
    return redirect("game:game_detail", game_id=game.id)
@login_required
@require_GET
def game_state(request, game_id: int):
    """
    Lightweight JSON endpoint with full game state.
    Intended for polling / AJAX / future real-time UI.
    """
    game = get_object_or_404(Game, id=game_id)

    # Permission: must be host or participant
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
    """
    Server-side dice roll + move for the current player.
    Validations:
      - game must be ACTIVE
      - user must be a participant
      - it must be this user's turn
    Returns JSON with roll result and updated game state.
    """
    game = get_object_or_404(Game, id=game_id)

    if game.status != Game.Status.ACTIVE:
        return JsonResponse({"detail": "Game is not active."}, status=400)

    try:
        player = game.players.select_related("user").get(user=request.user)
    except PlayerInGame.DoesNotExist:
        return JsonResponse({"detail": "You are not a player in this game."}, status=403)

    if game.current_player is None or game.current_player.id != player.id:
        return JsonResponse({"detail": "It is not your turn."}, status=403)

    # Perform dice roll + movement + turn advance
    action_result = game.roll_and_apply_for(player)

    # Get updated full state for UI
    state = game.to_public_state(for_user=request.user)

    payload = {
        "action": "roll",
        "result": action_result,
        "game_state": state,
    }
    return JsonResponse(payload)
@login_required
def game_board(request, game_id: int):
    """
    Full-screen board view with dice, tokens, live state, and
    server-rendered tiles/players.

    Only host or players in this game may enter.
    """
    game = get_object_or_404(Game, id=game_id)

    # --- permission check ---
    players_qs = game.players.select_related("user")
    is_player = players_qs.filter(user=request.user).exists()
    is_host = (game.host == request.user)

    if not (is_player or is_host):
        messages.error(request, "You are not a player in this game.")
        return redirect("game:game_list")

    # --- ensure game is active ---
    if game.status != Game.Status.ACTIVE:
        messages.info(request, "Game is not active yet.")
        return redirect("game:game_detail", game_id=game.id)

    # --- full public state for JS (live board, turns, etc.) ---
    state = game.to_public_state(for_user=request.user)

    # --- tiles + players for server-rendered parts of the board ---
    tiles_qs = game.tiles.order_by("position")
    players_ordered = players_qs.order_by("turn_order")

    context = {
        "game": game,
        "game_state": state,                  # JSON-friendly state for JS
        "me_player_id": state["you_player_id"],
        "current_player_id": state["current_player_id"],
        "players": players_ordered,           # for template loops
        "tiles": tiles_qs,                    # for template loops (e.g. 40 tiles)
    }
    return render(request, "game_board.html", context)