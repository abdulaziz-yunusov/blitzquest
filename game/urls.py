from django.urls import path
from . import views

app_name = "game"

urlpatterns = [
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
    # dice roll endpoint
    path('games/<int:game_id>/roll/', views.game_roll, name='game_roll'),
    # game board view
    path('games/<int:game_id>/board/', views.game_board, name='game_board'),
]

