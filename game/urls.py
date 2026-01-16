from django.urls import path
from . import views

app_name = "game"

urlpatterns = [
    # Home / auth
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
    path("password_reset/", views.password_reset_request, name="password_reset_request"),
    path("password_reset/confirm/", views.password_reset_confirm, name="password_reset_confirm"),
    path("profile/", views.profile, name="profile"),

    # Game management
    path("games/", views.game_list, name="game_list"),
    path("games/create/", views.game_create, name="game_create"),
    path("games/join/", views.game_join, name="game_join"),
    path("join/<str:code>/", views.join_game_by_code, name="join_game_by_code"),
    path("games/<int:game_id>/", views.game_detail, name="game_detail"),
    path("games/<int:game_id>/start/", views.game_start, name="game_start"),
    path("games/<int:game_id>/delete/", views.game_delete, name="game_delete"),
    path("games/<int:game_id>/end/", views.game_end, name="game_end"),

    # Board / state / dice
    path("games/<int:game_id>/board/", views.game_board, name="game_board"),
    path("games/<int:game_id>/state/", views.game_state, name="game_state"),
    path("games/<int:game_id>/roll/", views.game_roll, name="game_roll"),
    path("games/<int:game_id>/order_roll/", views.game_order_roll, name="game_order_roll"),

    # Questions
    path("games/<int:game_id>/answer_question/", views.answer_question, name="answer_question"),

    # Support cards
    path("games/<int:game_id>/use_card/", views.use_card, name="use_card"),

    # Shop
    path("games/<int:game_id>/shop/buy/", views.shop_buy, name="shop_buy"),
    path("games/<int:game_id>/shop/sell/", views.shop_sell, name="shop_sell"),
    path("games/<int:game_id>/shop/close/", views.shop_close, name="shop_close"),

    # Duel
    path("games/<int:game_id>/duel/select_opponent/", views.duel_select_opponent, name="duel_select_opponent"),
    path("games/<int:game_id>/duel/commit/", views.duel_commit, name="duel_commit"),
    path("games/<int:game_id>/duel/predict/", views.duel_predict, name="duel_predict"),
    path("games/<int:game_id>/duel/choose_reward/", views.duel_choose_reward, name="duel_choose_reward"),
    path("games/<int:game_id>/duel/skip/", views.duel_skip, name="duel_skip"),

    # Draft
    path("games/<int:game_id>/draft/pick/", views.draft_pick, name="draft_pick"),

    # Gun
    path("games/<int:game_id>/gun/attack/", views.gun_attack, name="gun_attack"),
    path("games/<int:game_id>/gun/skip/", views.gun_skip, name="game_gun_skip"),

    # Chat
    path("games/<int:game_id>/chat/messages/", views.game_chat_messages, name="game_chat_messages"),
    path("games/<int:game_id>/chat/send/", views.game_chat_send, name="game_chat_send"),
]
