"""Telegram Message Effects + Bot Reactions for modern UX.

Message effects (Bot API 7.0+) play a visual animation when the bot sends a
message in a PRIVATE chat (not in groups). The effect_id values below are the
official Telegram-issued IDs as of 2026.

Bot reactions (Bot API 7.0+) let the bot add an emoji reaction to a message.
"""
from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)

# Official Telegram effect IDs (work only in PRIVATE chats)
EFFECT_FIRE = "5104841245755180586"        # 🔥
EFFECT_THUMBS_UP = "5107584321108051014"   # 👍
EFFECT_HEART = "5159385139981059251"       # ❤️
EFFECT_PARTY = "5046509860389126442"       # 🎉
EFFECT_THUMBS_DOWN = "5104858069142078462" # 👎
EFFECT_POOP = "5046589136895476101"        # 💩

# Effects safe to use for happy events (track delivery, etc.)
HAPPY_EFFECTS = [EFFECT_FIRE, EFFECT_HEART, EFFECT_PARTY, EFFECT_THUMBS_UP]


def pick_effect_for_track(track_info: dict) -> Optional[str]:
    """Pick a message effect based on track metadata (genre, mood, etc.).

    Returns an effect_id string or None. Effects only work in private chats,
    so always pass None when sending to a group.
    """
    title = (track_info.get("title") or "").lower()
    uploader = (track_info.get("uploader") or "").lower()
    combined = f"{title} {uploader}"

    # Romance / love → ❤️
    love_keywords = ("love", "люб", "сердц", "heart", "amor", "romance", "kiss", "целу")
    if any(kw in combined for kw in love_keywords):
        return EFFECT_HEART

    # Party / dance / club → 🎉
    party_keywords = (
        "party", "вечерин", "club", "dance", "танц", "remix", "hardstyle",
        "drop", "edm", "rave", "house", "тусов",
    )
    if any(kw in combined for kw in party_keywords):
        return EFFECT_PARTY

    # Rap / hip-hop / hard → 🔥
    hard_keywords = (
        "рэп", "rap", "hip hop", "hip-hop", "trap", "drill",
        "хип-хоп", "оксимирон", "скриптонит", "хаски",
    )
    if any(kw in combined for kw in hard_keywords):
        return EFFECT_FIRE

    # Default: weighted random — fire most often (matches our brand)
    return random.choices(
        HAPPY_EFFECTS,
        weights=[0.5, 0.2, 0.2, 0.1],  # 50% fire, 20% heart, 20% party, 10% thumbs
        k=1,
    )[0]


async def safe_react(bot, chat_id: int, message_id: int, emoji: str = "🎵") -> None:
    """Set a bot emoji-reaction on the user's message. Silent on failure."""
    try:
        from aiogram.types import ReactionTypeEmoji
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
            is_big=False,
        )
    except Exception as e:
        logger.debug("safe_react failed (chat=%s msg=%s): %s", chat_id, message_id, e)


def effect_for_private(track_info: dict, is_private: bool) -> Optional[str]:
    """Return effect_id only for private chats (effects don't work in groups)."""
    if not is_private:
        return None
    return pick_effect_for_track(track_info)


# Valid Telegram reaction emojis (subset of the default reactions set).
# These work in ALL chats (group + private), unlike message effects.
REACTION_FIRE = "🔥"
REACTION_HEART = "❤"        # plain heart (not ❤️ which is variant selector)
REACTION_PARTY = "🎉"
REACTION_NOTE = "🎵"
REACTION_THUMBS = "👍"
REACTION_DANCE = "🕊"        # used as elegant default
REACTION_MIND_BLOWN = "🤯"


def pick_reaction_for_track(track_info: dict) -> str:
    """Pick a reaction emoji to put on the delivered audio message."""
    title = (track_info.get("title") or "").lower()
    uploader = (track_info.get("uploader") or "").lower()
    combined = f"{title} {uploader}"

    love_keywords = ("love", "люб", "сердц", "heart", "amor", "romance", "kiss", "целу")
    if any(kw in combined for kw in love_keywords):
        return REACTION_HEART

    party_keywords = (
        "party", "вечерин", "club", "dance", "танц", "remix", "hardstyle",
        "drop", "edm", "rave", "house", "тусов",
    )
    if any(kw in combined for kw in party_keywords):
        return REACTION_PARTY

    hard_keywords = (
        "рэп", "rap", "hip hop", "hip-hop", "trap", "drill",
        "хип-хоп", "оксимирон", "скриптонит", "хаски", "фараон", "pharaoh",
    )
    if any(kw in combined for kw in hard_keywords):
        return REACTION_FIRE

    import random
    return random.choices(
        [REACTION_FIRE, REACTION_HEART, REACTION_PARTY, REACTION_NOTE, REACTION_THUMBS],
        weights=[0.35, 0.20, 0.20, 0.15, 0.10],
        k=1,
    )[0]


async def react_to_own_track(bot, chat_id: int, message_id: int, track_info: dict) -> None:
    """Bot puts a genre-aware reaction on its own delivered audio message."""
    emoji = pick_reaction_for_track(track_info)
    await safe_react(bot, chat_id, message_id, emoji)
