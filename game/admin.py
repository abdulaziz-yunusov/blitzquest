from django.contrib import admin
from .models import (
    Game,
    PlayerInGame,
    BoardTile,
    Question,
    SupportCardType,
    SupportCardInstance,
    GameLog,
)


class PlayerInGameInline(admin.TabularInline):
    model = PlayerInGame
    extra = 0


class BoardTileInline(admin.TabularInline):
    model = BoardTile
    extra = 0


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("code", "status", "mode", "max_players", "board_length", "created_at")
    list_filter = ("status", "mode", "created_at")
    search_fields = ("code",)
    inlines = [PlayerInGameInline, BoardTileInline]


@admin.register(PlayerInGame)
class PlayerInGameAdmin(admin.ModelAdmin):
    list_display = ("game", "user", "turn_order", "hp", "coins", "position", "is_alive")
    list_filter = ("game", "is_alive")
    search_fields = ("user__username", "game__code")


@admin.register(BoardTile)
class BoardTileAdmin(admin.ModelAdmin):
    list_display = ("game", "position", "tile_type", "label", "value_int")
    list_filter = ("tile_type", "game")
    search_fields = ("game__code",)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "kanji", "text_short", "difficulty", "category", "created_at")
    list_filter = ("difficulty", "category")
    search_fields = ("text", "kanji", "category")

    def text_short(self, obj):
        return (obj.text[:50] + "...") if len(obj.text) > 50 else obj.text
    text_short.short_description = "Question"


@admin.register(SupportCardType)
class SupportCardTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "effect_type", "is_active")
    list_filter = ("effect_type", "is_active")
    search_fields = ("name", "code")


@admin.register(SupportCardInstance)
class SupportCardInstanceAdmin(admin.ModelAdmin):
    list_display = ("card_type", "owner", "is_used", "created_at", "used_at")
    list_filter = ("is_used", "card_type")
    search_fields = ("owner__user__username", "card_type__name")


@admin.register(GameLog)
class GameLogAdmin(admin.ModelAdmin):
    list_display = ("game", "player", "action_type", "created_at")
    list_filter = ("action_type", "game")
    search_fields = ("game__code", "player__user__username")
    readonly_fields = ("created_at",)
