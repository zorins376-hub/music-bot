"""Add bot self-reactions to delivered tracks (auto-like by genre)."""
import sys
from pathlib import Path

EFFECTS_FILE = Path("/root/music-bot/bot/services/message_effects.py")
esrc = EFFECTS_FILE.read_text()
eorig = esrc

# Add a helper that picks a reaction emoji by genre (same logic as effects)
if "def pick_reaction_for_track" not in esrc:
    ADDITION = '''

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
'''
    esrc = esrc + ADDITION

import ast
ast.parse(esrc)
EFFECTS_FILE.with_suffix(".py.bak_rx").write_text(eorig)
EFFECTS_FILE.write_text(esrc)
print(f"+ Extended {EFFECTS_FILE}")

# ─── Patch search.py to call react_to_own_track after each track send ───────
SEARCH = Path("/root/music-bot/bot/handlers/search.py")
src = SEARCH.read_text()
orig = src

# Import
if "react_to_own_track" not in src:
    src = src.replace(
        "from bot.services.message_effects import effect_for_private, safe_react",
        "from bot.services.message_effects import effect_for_private, safe_react, react_to_own_track",
        1,
    )

# 1. Group auto-play — after sending audio
OLD_GRP = '''        _eff = effect_for_private(track_info, message.chat.type == "private")
        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            reply_markup=_wt_kb,
            **({"message_effect_id": _eff} if _eff else {}),
        )
        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)'''

NEW_GRP = '''        _eff = effect_for_private(track_info, message.chat.type == "private")
        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            reply_markup=_wt_kb,
            **({"message_effect_id": _eff} if _eff else {}),
        )
        # Bot self-reacts to the delivered track (auto-like by genre)
        asyncio.create_task(react_to_own_track(message.bot, message.chat.id, sent.message_id, track_info))
        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)'''

if NEW_GRP not in src and OLD_GRP in src:
    src = src.replace(OLD_GRP, NEW_GRP, 1)
    print("+ Group: self-reaction on delivered track")

# 2. DM handle_track_select — main download path
OLD_DM = '''            _eff_dm = effect_for_private(track_info, callback.message.chat.type == "private")
            sent = await callback.message.answer_audio(
                audio=FSInputFile(mp3_path),
                title=track_info["title"],
                performer=track_info["uploader"],
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
                **({"message_effect_id": _eff_dm} if _eff_dm else {}),
            )

            await cache.set_file_id(video_id, sent.audio.file_id, bitrate)'''

NEW_DM = '''            _eff_dm = effect_for_private(track_info, callback.message.chat.type == "private")
            sent = await callback.message.answer_audio(
                audio=FSInputFile(mp3_path),
                title=track_info["title"],
                performer=track_info["uploader"],
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
                **({"message_effect_id": _eff_dm} if _eff_dm else {}),
            )
            # Bot self-reacts to the delivered track (auto-like by genre)
            asyncio.create_task(react_to_own_track(callback.message.bot, callback.message.chat.id, sent.message_id, track_info))

            await cache.set_file_id(video_id, sent.audio.file_id, bitrate)'''

if NEW_DM not in src and OLD_DM in src:
    src = src.replace(OLD_DM, NEW_DM, 1)
    print("+ DM: self-reaction on delivered track")

# 3. WrongTrackPick — final send
OLD_WTP = '''        _eff_wtp = effect_for_private(sent_track, callback.message.chat.type == "private")
        sent = await callback.bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(sent_path),
            title=sent_track.get("title", ""),
            performer=sent_track.get("uploader", ""),
            duration=int(sent_track["duration"]) if sent_track.get("duration") else None,
            caption=_track_caption(lang, sent_track, bitrate, ad_free=_af),
            **({"message_effect_id": _eff_wtp} if _eff_wtp else {}),
        )'''

NEW_WTP = '''        _eff_wtp = effect_for_private(sent_track, callback.message.chat.type == "private")
        sent = await callback.bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(sent_path),
            title=sent_track.get("title", ""),
            performer=sent_track.get("uploader", ""),
            duration=int(sent_track["duration"]) if sent_track.get("duration") else None,
            caption=_track_caption(lang, sent_track, bitrate, ad_free=_af),
            **({"message_effect_id": _eff_wtp} if _eff_wtp else {}),
        )
        # Bot self-reacts to delivered track
        asyncio.create_task(react_to_own_track(callback.bot, chat_id, sent.message_id, sent_track))'''

if NEW_WTP not in src and OLD_WTP in src:
    src = src.replace(OLD_WTP, NEW_WTP, 1)
    print("+ WrongTrackPick: self-reaction on delivered track")

ast.parse(src)
SEARCH.with_suffix(".py.bak_rx").write_text(orig)
SEARCH.write_text(src)
print(f"+ Patched: {SEARCH}")
print(f"Restart: docker compose restart bot")
