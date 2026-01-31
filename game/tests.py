from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from unittest.mock import patch

from .models import Game, PlayerInGame, BoardTile, SupportCardInstance, SupportCardType


class ViewsBasicTests(TestCase):
    """
    Basic integration tests for game views and logic.
    Covers game creation, joining, starting, card usage, and permission checks.
    """
    def setUp(self):
        """Set up test client and initial users."""
        self.client = Client()
        self.user = User.objects.create_user(username="u1", password="pass1234")
        self.other = User.objects.create_user(username="u2", password="pass1234")

    def login(self, who=None):
        """Helper to log in a user (defaults to self.user)."""
        who = who or self.user
        self.client.login(username=who.username, password="pass1234")

    def create_waiting_game(self, host=None, players=1):
        """
        Helper to create a game in WAITING status with players.
        
        Args:
            host (User): The game host.
            players (int): Number of players to add (including host).
            
        Returns:
            Game: The created game instance.
        """
        host = host or self.user
        game = Game.objects.create(
            host=host,
            code="ABC123",
            status=Game.Status.WAITING,
            board_length=10,
            max_players=4,
        )
        # create a simple board with start, safe, and finish to allow movement
        for i in range(10):
            if i == 0:
                t = BoardTile.TileType.START
            elif i == 9:
                t = BoardTile.TileType.FINISH
            else:
                t = BoardTile.TileType.SAFE
            BoardTile.objects.create(game=game, position=i, tile_type=t)
        # add host as player 0
        PlayerInGame.objects.create(
            game=game, user=host, turn_order=0, hp=3, coins=0, position=0, is_alive=True
        )
        # optionally add second player (for start and active tests)
        if players > 1:
            PlayerInGame.objects.create(
                game=game, user=self.other, turn_order=1, hp=3, coins=0, position=0, is_alive=True
            )
        return game

    def test_game_join_rejects_full_game(self):
        """Ensure joining a full game is rejected with a redirect."""
        # Should return redirect with error message when game is full
        game = self.create_waiting_game(players=1)
        game.max_players = 1
        game.save(update_fields=["max_players"])

        self.login(self.other)
        resp = self.client.post(reverse("game:game_join"), {"code": game.code})
        self.assertEqual(resp.status_code, 302)

    def test_game_start_only_host_can_start(self):
        """Ensure only the host can start the game."""
        # Non-host cannot start the game
        game = self.create_waiting_game(players=2)
        self.login(self.other)
        resp = self.client.post(reverse("game:game_start", args=[game.id]))
        self.assertEqual(resp.status_code, 302)
        game.refresh_from_db()
        self.assertNotEqual(game.status, Game.Status.ACTIVE)

    @patch("blitzquest.game.views.random.randint", return_value=2)
    def test_use_card_move_extra_advances_position(self, mock_rand):
        """Test that using a 'move_extra' card correctly updates player position."""
        # Using move_extra should move player forward deterministically by mocked value
        game = self.create_waiting_game(players=2)
        game.status = Game.Status.ACTIVE
        game.current_turn_index = 0
        game.save(update_fields=["status", "current_turn_index"])

        # give user a move_extra card
        sct = SupportCardType.objects.create(
            code="move_extra",
            name="Move extra",
            effect_type=SupportCardType.EffectType.MOVE_EXTRA,
            params={},
        )
        me = PlayerInGame.objects.get(game=game, user=self.user)
        card = SupportCardInstance.objects.create(card_type=sct, owner=me, is_used=False)

        self.login(self.user)
        url = reverse("game:use_card", args=[game.id])
        resp = self.client.post(url, data={"card_id": card.id}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        me.refresh_from_db()
        self.assertEqual(me.position, 2)

    def test_answer_question_enforces_owner_only(self):
        """Ensure only the targeted player can answer a pending question."""
        # Only the player for whom question is pending can answer
        game = self.create_waiting_game(players=2)
        game.status = Game.Status.ACTIVE
        me = PlayerInGame.objects.get(game=game, user=self.user)
        game.pending_question = {"for_player_id": me.id, "correct_index": 0}
        game.save(update_fields=["status", "pending_question"])

        self.login(self.other)
        url = reverse("game:answer_question", args=[game.id])
        resp = self.client.post(url, data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_game_roll_blocks_when_shop_pending_for_other(self):
        """Ensure rolling is blocked for non-active players if a modal (shop) is pending."""
        # Rolling should be blocked for non-owner when shop is pending
        game = self.create_waiting_game(players=2)
        game.status = Game.Status.ACTIVE
        other_p = PlayerInGame.objects.get(game=game, user=self.other)
        game.pending_shop = {"for_player_id": other_p.id}
        game.current_turn_index = 1  # make it other's turn
        game.save(update_fields=["status", "pending_shop", "current_turn_index"])

        self.login(self.user)
        url = reverse("game:game_roll", args=[game.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 403)
