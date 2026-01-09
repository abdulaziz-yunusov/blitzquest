from django.urls import path
from . import views

app_name = "game"

urlpatterns = [
<<<<<<< HEAD
    # Auth / landing
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
=======
    # home page
    path('', views.home, name='home'),
    # game management endpoints
    path('games/', views.game_list, name='game_list'),
    # create game endpoint
    path('games/create/', views.game_create, name='game_create'),
    # join game endpoint
    path('games/join/', views.game_join, name='game_join'),
    # game detail endpoint
    path('games/<int:game_id>/', views.game_detail, name='game_detail'),
    # start game endpoint
    path('games/<int:game_id>/start/', views.game_start, name='game_start'),
    # delete game endpoint
    path('games/<int:game_id>/delete/', views.game_delete, name='game_delete'),
    # end game endpoint
    path('games/<int:game_id>/end/', views.game_end, name='game_end'),
    # pure JSON endpoint
    path('games/<int:game_id>/state/', views.game_state, name='game_state'),
    # turn-order roll endpoint
    path('games/<int:game_id>/order_roll/', views.game_order_roll, name='game_order_roll'),
    # dice roll endpoint
    path('games/<int:game_id>/roll/', views.game_roll, name='game_roll'),
    # game board view
    path('games/<int:game_id>/board/', views.game_board, name='game_board'),
    # answer question
    path('games/<int:game_id>/answer_question/', views.answer_question, name='answer_question'),
    # use card endpoint
    path('games/<int:game_id>/use_card/', views.use_card, name='use_card'),
    # shop buy endpoint
    path('games/<int:game_id>/shop/buy/', views.shop_buy, name='shop_buy'),
    # shop sell endpoint
    path('games/<int:game_id>/shop/sell/', views.shop_sell, name='shop_sell'),
    # shop close endpoint
    path('games/<int:game_id>/shop/close/', views.shop_close, name='shop_close'),
    # duel select opponent endpoint
    path('games/<int:game_id>/duel/select_opponent/', views.duel_select_opponent, name='duel_select_opponent'),
    # duel commit endpoint
    path('games/<int:game_id>/duel/commit/', views.duel_commit, name='duel_commit'),
    # duel predict endpoint
    path('games/<int:game_id>/duel/predict/', views.duel_predict, name='duel_predict'),
    # duel choose reward endpoint
    path('games/<int:game_id>/duel/choose_reward/', views.duel_choose_reward, name='duel_choose_reward'),
    # duel skip endpoint
    path("games/<int:game_id>/duel/skip/", views.duel_skip, name="duel_skip"),
    # draft pick endpoint
    path('games/<int:game_id>/draft/pick/', views.draft_pick, name='draft_pick'),
    # gun attack endpoint
    path('games/<int:game_id>/gun/attack/', views.gun_attack, name='gun_attack'),
    # gun skip endpoint
    path('games/<int:game_id>/gun/skip/', views.gun_skip, name='gun_skip'),
]
>>>>>>> 58428d0 (Adding players turn order by dice)

    # Game management
    path("games/", views.game_list, name="game_list"),
    path("games/create/", views.game_create, name="game_create"),
    path("games/join/", views.game_join, name="game_join"),
    path("games/<int:game_id>/", views.game_detail, name="game_detail"),
    path("games/<int:game_id>/start/", views.game_start, name="game_start"),
    path("games/<int:game_id>/delete/", views.game_delete, name="game_delete"),
    path("games/<int:game_id>/end/", views.game_end, name="game_end"),

    # Board / state / actions
    path("games/<int:game_id>/board/", views.game_board, name="game_board"),
    path("games/<int:game_id>/state/", views.game_state, name="game_state"),
    path("games/<int:game_id>/roll/", views.game_roll, name="game_roll"),
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

    # Draft mode
    path("games/<int:game_id>/draft/pick/", views.draft_pick, name="draft_pick"),

    # Gun
    path("games/<int:game_id>/gun/attack/", views.gun_attack, name="gun_attack"),
    path("games/<int:game_id>/gun/skip/", views.gun_skip, name="gun_skip"),

    # ✅ Chat
    path("games/<int:game_id>/chat/messages/", views.game_chat_messages, name="game_chat_messages"),
    path("games/<int:game_id>/chat/send/", views.game_chat_send, name="game_chat_send"),
]
