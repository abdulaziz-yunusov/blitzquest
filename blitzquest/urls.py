from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from game import views as game_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth routes
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(template_name='registration/login.html'),
        name='login',
    ),
    path(
        'accounts/logout/',
        auth_views.LogoutView.as_view(next_page='game:home'),
        name='logout',
    ),
    path(
        'accounts/signup/',
        game_views.signup,
        name='signup',
    ),

    # Game routes
    path('', include('game.urls')),
]
