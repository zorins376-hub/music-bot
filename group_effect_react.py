"""Add message_effect + self-reaction to group _group_auto_play send."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")
src = TARGET.read_text()
orig = src

OLD = '''        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            reply_markup=_build_wrong_track_kb(alt_sid),
        )
        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
        await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])'''

NEW = '''        _eff_grp = effect_for_private(track_info, message.chat.type == "private")
        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            reply_markup=_build_wrong_track_kb(alt_sid),
            **({"message_effect_id": _eff_grp} if _eff_grp else {}),
        )
        # Bot self-reacts to the delivered track (auto-like by genre 🔥/❤/🎉/🎵)
        asyncio.create_task(react_to_own_track(message.bot, message.chat.id, sent.message_id, track_info))
        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
        await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])'''

if NEW in src:
    print("Already applied")
    sys.exit(0)
if OLD not in src:
    print("FATAL: anchor not found")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)
import ast
ast.parse(src)

bak = TARGET.with_suffix(".py.bak_grp_react")
bak.write_text(orig)
TARGET.write_text(src)
print(f"+ Group: effect + self-reaction on delivered track")
print(f"Patched: {TARGET}")
