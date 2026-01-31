from .models import CardDuelCardType
from django.templatetags.static import static


CARD_DUEL_CARDS = [
    # =========================
    # 5 + Status cards
    # =========================
    {
        "code": "BattleFocus",
        "name": "Battle Focus",
        "description": "Gain Battle Focus: +2 damage for 2 turns.",
        "category": CardDuelCardType.Category.PLUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "battle_focus", "turns": 2, "damage_bonus": 2, "stacks": 1}},
    },
    {
        "code": "IronSkin",
        "name": "Iron Skin",
        "description": "Gain 6 shield.",
        "category": CardDuelCardType.Category.PLUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.SHIELD,
        "params": {"amount": 6},
    },
    {
        "code": "PurifyAura",
        "name": "Purify Aura",
        "description": "Remove all negative effects from yourself.",
        "category": CardDuelCardType.Category.PLUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.CLEANSE,
        "params": {"target": "self", "remove_count": 100, "types": ["poison", "burn", "weaken", "vulnerable", "silence", "stun", "weaken_curse"]},
    },
    {
        "code": "RegenBrew",
        "name": "Regen Brew",
        "description": "Gain Regen: heal 2 at the start of your next 2 turns.",
        "category": CardDuelCardType.Category.PLUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "regen", "turns": 2, "tick_heal": 2, "stacks": 1}},
    },
    {
        "code": "Heal",
        "name": "Heal",
        "description": "Restore 5 HP.",
        "category": CardDuelCardType.Category.PLUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.HEAL,
        "params": {"amount": 5},
    },

    # =========================
    # 5 - Status cards
    # =========================
    {
        "code": "Poison",
        "name": "Poison",
        "description": "Apply Poison: target takes 1 damage at the start of their next 3 turns.",
        "category": CardDuelCardType.Category.MINUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "poison", "turns": 3, "tick_damage": 1, "stacks": 1}},
    },
    {
        "code": "Burn",
        "name": "Burn",
        "description": "Apply Burn: target takes 2 damage at the start of their next 2 turns.",
        "category": CardDuelCardType.Category.MINUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "burn", "turns": 2, "tick_damage": 2, "stacks": 1}},
    },
    {
        "code": "Weaken",
        "name": "Weaken",
        "description": "Apply Weaken: target deals 2 less damage on their next attack card.",
        "category": CardDuelCardType.Category.MINUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "weaken", "turns": 1, "damage_down_next": 2, "stacks": 1}},
    },
    {
        "code": "Vulnerable",
        "name": "Vulnerable",
        "description": "Apply Vulnerable: target takes +1 damage for their next 2 turns.",
        "category": CardDuelCardType.Category.MINUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "vulnerable", "turns": 2, "damage_taken_up": 1, "stacks": 1}},
    },
    {
        "code": "Silence",
        "name": "Silence Seal",
        "description": "Apply Silence: target cannot play ANY card on their next turn.",
        "category": CardDuelCardType.Category.MINUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "silence", "turns": 1, "block_all": True, "stacks": 1}},
    },
    {
        "code": "Stun",
        "name": "Stun Shock",
        "description": "Apply Stun: target cannot play an Action card on their next turn (Bonus cards allowed).",
        "category": CardDuelCardType.Category.MINUS_STATUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "stun", "turns": 1, "block_action": True, "stacks": 1}},
    },

    # =========================
    # 5 Neutral cards
    # =========================
    {
        "code": "Adrenaline",
        "name": "Adrenaline",
        "description": "Draw +1 card next turn.",
        "category": CardDuelCardType.Category.NEUTRAL,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "focus", "turns": 1, "extra_draw": 1, "stacks": 1}},
    },
    {
        "code": "CardCycle",
        "name": "Card Cycle",
        "description": "Change (replace) up to 2 cards in your hand.",
        "category": CardDuelCardType.Category.NEUTRAL,
        "effect_type": CardDuelCardType.EffectType.DISCARD_AND_DRAW,
        "params": {"amount": 2},
    },
    {
        "code": "GuardSwap",
        "name": "Guard Swap",
        "description": "Swap shields between you and the enemy.",
        "category": CardDuelCardType.Category.NEUTRAL,
        "effect_type": CardDuelCardType.EffectType.SWAP_SHIELD,
        "params": {},
    },
    {
        "code": "QuickFix",
        "name": "Quick Fix",
        "description": "Heal 2 and gain 2 shield.",
        "category": CardDuelCardType.Category.NEUTRAL,
        "effect_type": CardDuelCardType.EffectType.HEAL_AND_SHIELD,
        "params": {"heal": 2, "shield": 2},
    },
    {
        "code": "WeakenCurse",
        "name": "Weaken Curse",
        "description": "Enemy deals 50% less damage (rounded down) on their next attack.",
        "category": CardDuelCardType.Category.NEUTRAL,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        # note: using a new status 'weaken_percent' to distinguish from flat weaken if desired,
        # or just reuse 'weaken' with damage_percent param.
        "params": {"status": {"type": "weaken_curse", "turns": 1, "damage_percent": 50, "stacks": 1}},
    },

    # =========================
    # 5 Bonus cards (status + effects)
    # =========================
    {
        "code": "Amplify",
        "name": "Amplify",
        "description": "Your next heal restores +3 additional HP.",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "amplify_heal", "turns": 99, "heal_bonus": 3, "stacks": 1, "consume_on_heal": True}},
    },
    {
        "code": "AntidoteKit",
        "name": "Antidote Kit",
        "description": "Remove Poison and Burn effects, then heal 1 HP.",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.ANTIDOTE,
        "params": {"heal": 1, "types": ["poison", "burn"]},
    },
    {
        "code": "CounterStance",
        "name": "Counter Stance",
        "description": "Reflect 3 damage once (the next time you take damage).",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.APPLY_STATUS,
        "params": {"status": {"type": "counter_stance", "turns": 99, "reflect_amount": 3, "stacks": 1, "consume_on_hit": True}},
    },
    {
        "code": "GambleCoin",
        "name": "Gamble Coin",
        "description": "50% chance to gain 8 shield, 50% chance to take 3 damage.",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.GAMBLE,
        "params": {"win": {"type": "shield", "amount": 8}, "loss": {"type": "damage_self", "amount": 3}, "win_chance": 0.5},
    },
    {
        "code": "LuckyDraw",
        "name": "Lucky Draw",
        "description": "Draw 2 cards.",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.DRAW,
        "params": {"amount": 2},
    },

    # =========================
    # Legacy Bonus cards (Restored)
    # =========================
    {
        "code": "VenomStrike",
        "name": "Venom Strike",
        "description": "Deal 3 damage and apply Poison (1 dmg for 3 turns).",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.DAMAGE,
        "params": {"amount": 3, "apply_status": {"type": "poison", "turns": 3, "tick_damage": 1, "stacks": 1}},
    },
    {
        "code": "FlameJab",
        "name": "Flame Jab",
        "description": "Deal 3 damage and apply Burn (2 dmg for 2 turns).",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.DAMAGE,
        "params": {"amount": 3, "apply_status": {"type": "burn", "turns": 2, "tick_damage": 2, "stacks": 1}},
    },
    {
        "code": "HolyLight",
        "name": "Holy Light",
        "description": "Heal 3 and gain Regen (heal 1 for 3 turns).",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.HEAL,
        "params": {"amount": 3, "apply_status": {"type": "regen", "turns": 3, "tick_heal": 1, "stacks": 1}},
    },
    {
        "code": "CripplingShot",
        "name": "Crippling Shot",
        "description": "Deal 4 damage and apply Weaken (-2 on next attack).",
        "category": CardDuelCardType.Category.BONUS,
        "effect_type": CardDuelCardType.EffectType.DAMAGE,
        "params": {"amount": 4, "apply_status": {"type": "weaken", "turns": 1, "damage_down_next": 2, "stacks": 1}},
    },
]

CARD_DUEL_IMAGE_BY_CODE = {
    # PLUS / POSITIVE
    "CD_HEAL_5": "RestoreHp.png",
    "CD_IRON_SKIN": "IronSkin.png",
    "CD_REGEN_BREW": "RegenBrew.png",
    "CD_BATTLE_FOCUS": "BattleFocus.png",
    "CD_PURIFY_AURA": "PurifyAura.png",

    # MINUS / NEGATIVE
    "CD_POISON_1x3": "PoisonNeedle.png",
    "CD_BURN_2x2": "BurningMark.png",
    "CD_WEAKEN_2": "WeakenCurse.png",
    "CD_VULNERABLE_1x2": "CounterStance.png",  # closest match you currently have
    "CD_SILENCE_1": "SilenceSeal.png",
    "CD_STUN_1": "StunShock.png",

    # NEUTRAL
    "CD_ADRENALINE_1": "Adrenaline.png",
    "CardCycle": "CardCycle.png",
    "GuardSwap": "GuardSwap.png",
    "QuickFix": "RegenBrew.png",
    "WeakenCurse": "WeakenCurse.png",

    # BONUS
    "Amplify": "Amplify.png",
    "AntidoteKit": "AntidoteKit.png",
    "CounterStance": "CounterStance.png",
    "GambleCoin": "GambleCoin.png",
    "LuckyDraw": "LuckyDraw.png",
    "VenomStrike": "PoisonNeedle.png",
    "FlameJab": "BurningMark.png",
    "HolyLight": "RegenBrew.png",
    "CripplingShot": "WeakenCurse.png",
}

def seed_card_duel_cards() -> None:
    """
    Idempotent seed function for Card Duel cards.
    - Creates missing cards.
    - Updates fields (name, description, category, effect_type, params) if changed.
    - Does NOT automatically deactivate cards (is_active defaults to True).
    """
    for card in CARD_DUEL_CARDS:
        code = card["code"]
        defaults = {
            "name": card["name"],
            "description": card["description"],
            "category": card["category"],
            "effect_type": card["effect_type"],
            "params": card["params"],
            "is_active": True,
        }
        CardDuelCardType.objects.update_or_create(code=code, defaults=defaults)

def cd_image_url_for_code(code: str) -> str:
    """
    Returns the static URL for a card's image based on its code.

    Args:
        code (str): The card code.

    Returns:
        str: The static URL string for the image.
    """
    filename = CARD_DUEL_IMAGE_BY_CODE.get(code, "back.png")
    return static(f"images/CardDuelCards/{filename}")
