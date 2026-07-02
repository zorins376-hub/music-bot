"""
morning_mix.py — Daily personalized mix sent to active users at 8 AM UTC.

Engagement feature: brings users back to the bot daily with a curated mix
based on their recent listening history.
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, desc

logger = logging.getLogger(__name__)

_MIX_HOUR_UTC = 5   # 8:00 in MSK / 8:00 in Bishkek (UTC+3 / UTC+6 — pick a middle ground)
_ACTIVE_WINDOW_DAYS = 14   # Send only to users active in last 2 weeks
_HISTORY_LOOKBACK_DAYS = 30
_MIX_SIZE = 5


async def start_morning_mix_scheduler(bot) -> None:
    """Start the background morning-mix loop. Call from on_startup."""
    asyncio.create_task(_mix_loop(bot))


async def _mix_loop(bot) -> None:
    """Run forever, sending mixes at _MIX_HOUR_UTC daily."""
    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=_MIX_HOUR_UTC, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Morning mix next run in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            await _send_morning_mixes(bot)
        except Exception as e:
            logger.error("Morning mix send failed: %s", e)


async def _build_user_mix(session, user_id: int) -> list[tuple[str, str]]:
    """Build a personalized mix for a user.
    Returns list of (artist, title) tuples."""
    from bot.models.track import ListeningHistory, Track

    cutoff = datetime.now(timezone.utc) - timedelta(days=_HISTORY_LOOKBACK_DAYS)

    # Get top artists from user's recent listening history
    stmt = (
        select(Track.artist, func.count(ListeningHistory.id).label("plays"))
        .join(Track, ListeningHistory.track_id == Track.id)
        .where(ListeningHistory.user_id == user_id)
        .where(ListeningHistory.created_at >= cutoff)
        .where(Track.artist.is_not(None))
        .group_by(Track.artist)
        .order_by(desc("plays"))
        .limit(10)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []

    top_artists = [r.artist for r in rows]

    # Sample one popular track from each top artist (skip already-played-today)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_track_ids = set()
    today_stmt = (
        select(ListeningHistory.track_id)
        .where(ListeningHistory.user_id == user_id)
        .where(ListeningHistory.created_at >= today)
        .where(ListeningHistory.track_id.is_not(None))
    )
    for tid in (await session.execute(today_stmt)).scalars():
        today_track_ids.add(tid)

    picks: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    random.shuffle(top_artists)
    for artist in top_artists:
        if len(picks) >= _MIX_SIZE:
            break
        tr_stmt = (
            select(Track.artist, Track.title, Track.id)
            .where(Track.artist == artist)
            .where(Track.id.notin_(today_track_ids) if today_track_ids else True)
            .order_by(desc(Track.id))
            .limit(8)
        )
        tracks = (await session.execute(tr_stmt)).all()
        random.shuffle(list(tracks))
        for tr in tracks:
            key = f"{tr.artist}|{tr.title}".lower().strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            picks.append((tr.artist, tr.title))
            break
    return picks


async def _send_morning_mixes(bot) -> None:
    """Send personalized morning mixes to active users."""
    from bot.models.base import async_session
    from bot.models.user import User
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    active_cutoff = datetime.now(timezone.utc) - timedelta(days=_ACTIVE_WINDOW_DAYS)
    bot_me = await bot.me()
    bot_username = bot_me.username

    async with async_session() as session:
        active_users = await session.execute(
            select(User.id, User.language, User.first_name)
            .where(User.last_active >= active_cutoff)
            .where(User.morning_mix_enabled.is_(True))
        )
        users = list(active_users)

    logger.info("Morning mix: %d active users to process", len(users))
    sent = skipped = errors = 0

    for u in users:
        try:
            async with async_session() as session:
                mix = await _build_user_mix(session, u.id)
            if not mix:
                skipped += 1
                continue

            lines = [f"🌅 <b>Доброе утро, {u.first_name or 'дружище'}!</b>", "",
                     "Собрал свежий микс по твоим вкусам:", ""]
            buttons = []
            from base64 import urlsafe_b64encode
            for i, (artist, title) in enumerate(mix, 1):
                lines.append(f"<b>{i}.</b> {artist} — {title}")
                query = f"{artist} {title}"
                b64 = urlsafe_b64encode(query.encode()).decode().rstrip("=")
                deep_link = f"https://t.me/{bot_username}?start=s_{b64}"
                buttons.append([InlineKeyboardButton(text=f"▶ {i}", url=deep_link)])
            lines.append("")
            lines.append("<i>Кликни на номер чтобы послушать. Отключить: /settings</i>")
            text = chr(10).join(lines)

            kb_rows = []
            for i in range(0, len(buttons), 5):
                kb_rows.append([b[0] for b in buttons[i:i+5]])

            await bot.send_message(
                u.id, text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
                disable_web_page_preview=True,
            )
            sent += 1
            await asyncio.sleep(0.05)  # rate-limit
        except Exception as e:
            errors += 1
            err_str = str(e).lower()
            if "blocked" in err_str or "deactivated" in err_str:
                logger.debug("Morning mix: user %s blocked bot", u.id)
            else:
                logger.warning("Morning mix to %s failed: %s", u.id, str(e)[:120])

    logger.info("Morning mix done: sent=%d skipped=%d errors=%d", sent, skipped, errors)
