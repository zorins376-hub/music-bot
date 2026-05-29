"""
Modernize music bot with new Telegram features:
1. Message Effects (🔥, ❤️, 🎉) on track delivery
2. Bot Reactions (🎵) on user search requests
3. Genre-aware random effects
4. Set persistent menu button
"""
import sys
from pathlib import Path

# ─── 1. Create helper module for effects ────────────────────────────────────
EFFECTS_FILE = Path("/root/music-bot/bot/services/message_effects.py")
EFFECTS_CODE = '''"""Telegram Message Effects + Bot Reactions for modern UX.

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
'''

# ─── 2. Patch search.py to use effects on track delivery + reactions ────────
SEARCH = Path("/root/music-bot/bot/handlers/search.py")
src = SEARCH.read_text()
orig = src

# 2a. Add import at the top
if "from bot.services.message_effects import" not in src:
    OLD_IMPORT = "from bot.utils import fmt_duration"
    NEW_IMPORT = (
        "from bot.utils import fmt_duration\n"
        "from bot.services.message_effects import effect_for_private, safe_react"
    )
    src = src.replace(OLD_IMPORT, NEW_IMPORT, 1)

# 2b. In _do_search: react with 🎵 on user's request message
OLD_DOSEARCH = '''async def _do_search(message: Message, query: str) -> None:
    try:
        user = await get_or_create_user(message.from_user)
    except Exception:
        await message.answer("⚠️ Сервис временно недоступен. Попробуй снова.")
        return'''

NEW_DOSEARCH = '''async def _do_search(message: Message, query: str) -> None:
    try:
        user = await get_or_create_user(message.from_user)
    except Exception:
        await message.answer("⚠️ Сервис временно недоступен. Попробуй снова.")
        return
    # 🎵 React to the user message so they know we picked up the request
    try:
        import asyncio as _asyncio
        _asyncio.create_task(safe_react(message.bot, message.chat.id, message.message_id, "🎵"))
    except Exception:
        pass'''

if NEW_DOSEARCH not in src and OLD_DOSEARCH in src:
    src = src.replace(OLD_DOSEARCH, NEW_DOSEARCH, 1)

# 2c. Group auto-play: add message_effect_id when sending the final audio
# (effects only work in private chats — group will get None which is fine)
OLD_GROUP_SEND = '''        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            reply_markup=_wt_kb,
        )'''

NEW_GROUP_SEND = '''        _eff = effect_for_private(track_info, message.chat.type == "private")
        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            reply_markup=_wt_kb,
            **({"message_effect_id": _eff} if _eff else {}),
        )'''

if NEW_GROUP_SEND not in src and OLD_GROUP_SEND in src:
    src = src.replace(OLD_GROUP_SEND, NEW_GROUP_SEND, 1)

# 2d. DM handle_track_select: add effect to main audio send
# Find the pattern in handle_track_select - the big sent = await callback.message.answer_audio block
# We'll patch the most common ones
OLD_DM_SEND = '''            sent = await callback.message.answer_audio(
                audio=FSInputFile(mp3_path),
                title=track_info["title"],
                performer=track_info["uploader"],
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            )

            await cache.set_file_id(video_id, sent.audio.file_id, bitrate)'''

NEW_DM_SEND = '''            _eff_dm = effect_for_private(track_info, callback.message.chat.type == "private")
            sent = await callback.message.answer_audio(
                audio=FSInputFile(mp3_path),
                title=track_info["title"],
                performer=track_info["uploader"],
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
                **({"message_effect_id": _eff_dm} if _eff_dm else {}),
            )

            await cache.set_file_id(video_id, sent.audio.file_id, bitrate)'''

if NEW_DM_SEND not in src and OLD_DM_SEND in src:
    src = src.replace(OLD_DM_SEND, NEW_DM_SEND, 1)

# 2e. WrongTrackPick send: add effect
OLD_WTP_SEND = '''        sent = await callback.bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(sent_path),
            title=sent_track.get("title", ""),
            performer=sent_track.get("uploader", ""),
            duration=int(sent_track["duration"]) if sent_track.get("duration") else None,
            caption=_track_caption(lang, sent_track, bitrate, ad_free=_af),
        )'''

NEW_WTP_SEND = '''        _eff_wtp = effect_for_private(sent_track, callback.message.chat.type == "private")
        sent = await callback.bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(sent_path),
            title=sent_track.get("title", ""),
            performer=sent_track.get("uploader", ""),
            duration=int(sent_track["duration"]) if sent_track.get("duration") else None,
            caption=_track_caption(lang, sent_track, bitrate, ad_free=_af),
            **({"message_effect_id": _eff_wtp} if _eff_wtp else {}),
        )'''

if NEW_WTP_SEND not in src and OLD_WTP_SEND in src:
    src = src.replace(OLD_WTP_SEND, NEW_WTP_SEND, 1)

# ─── 3. Patch main.py to set persistent menu button ─────────────────────────
MAIN = Path("/root/music-bot/bot/main.py")
main_src = MAIN.read_text()
orig_main = main_src

OLD_CMD = '''        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
    except Exception as e:
        logger.warning("Failed to set bot commands (non-fatal): %s", e)'''

NEW_CMD = '''        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
        # Modern UI: set persistent menu button (the icon next to the message input)
        try:
            from aiogram.types import MenuButtonCommands
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
            logger.info("Set persistent menu button (MenuButtonCommands)")
        except Exception as _mb_err:
            logger.debug("Could not set menu button: %s", _mb_err)
    except Exception as e:
        logger.warning("Failed to set bot commands (non-fatal): %s", e)'''

if NEW_CMD not in main_src and OLD_CMD in main_src:
    main_src = main_src.replace(OLD_CMD, NEW_CMD, 1)


# ─── Write everything ───────────────────────────────────────────────────────
import ast

EFFECTS_FILE.write_text(EFFECTS_CODE)
ast.parse(EFFECTS_CODE)  # verify
print(f"+ Created: {EFFECTS_FILE} ({len(EFFECTS_CODE)} bytes)")

ast.parse(src)
SEARCH.with_suffix(".py.bak_modern").write_text(orig)
SEARCH.write_text(src)
print(f"+ Patched: {SEARCH} (delta {len(src) - len(orig):+d} bytes)")

ast.parse(main_src)
MAIN.with_suffix(".py.bak_modern").write_text(orig_main)
MAIN.write_text(main_src)
print(f"+ Patched: {MAIN} (delta {len(main_src) - len(orig_main):+d} bytes)")

print()
print("Features added:")
print("  🎵 Bot reaction on user search request (group + DM)")
print("  🔥 Message effect on track delivery (DM only — TG limitation)")
print("  ❤️ Smart effect by genre: love→❤️, party→🎉, rap→🔥")
print("  📱 Persistent menu button (Commands)")
print("Restart: docker compose restart bot")
