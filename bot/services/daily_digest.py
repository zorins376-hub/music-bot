"""
daily_digest.py — Send daily stats digest to admins at 23:00 UTC.

G-03: Scheduled task that summarizes the day's activity.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

_DIGEST_HOUR = 23  # UTC


async def start_digest_scheduler(bot) -> None:
    """Start the background digest loop. Call from on_startup."""
    asyncio.create_task(_digest_loop(bot))


async def _digest_loop(bot) -> None:
    """Run forever, sending digest at _DIGEST_HOUR:00 UTC daily."""
    while True:
        now = datetime.now(timezone.utc)
        # Calculate next run
        target = now.replace(hour=_DIGEST_HOUR, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Daily digest next run in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            await _send_digest(bot)
        except Exception as e:
            logger.error("Digest send failed: %s", e)


async def _send_digest(bot) -> None:
    """Build and send the digest message to all admins."""
    from bot.config import settings
    from bot.models.base import async_session
    from bot.models.user import User
    from bot.models.track import Track, ListeningHistory, Payment

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as session:
        new_users = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.created_at >= today_start)
        ) or 0

        active_users = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.last_active >= today_start)
        ) or 0

        plays_today = await session.scalar(
            select(func.count()).select_from(ListeningHistory)
            .where(ListeningHistory.action == "play", ListeningHistory.created_at >= today_start)
        ) or 0

        premium_today = await session.scalar(
            select(func.count()).select_from(Payment)
            .where(Payment.created_at >= today_start)
        ) or 0

        revenue_today = await session.scalar(
            select(func.sum(Payment.amount))
            .where(Payment.created_at >= today_start)
        ) or 0

        # Top queries
        top_q_r = await session.execute(
            select(ListeningHistory.query, func.count().label("cnt"))
            .where(
                ListeningHistory.action == "search",
                ListeningHistory.created_at >= today_start,
                ListeningHistory.query.is_not(None),
            )
            .group_by(ListeningHistory.query)
            .order_by(func.count().desc())
            .limit(5)
        )
        top_queries = top_q_r.all()

    date_str = now.strftime("%d.%m.%Y")
    lines = [
        f"◆ <b>Дайджест за {date_str}</b>",
        "",
        f"▸ Новых юзеров: <b>{new_users}</b>",
        f"▸ Активных: <b>{active_users}</b>",
        f"▸ Треков скачано: <b>{plays_today}</b>",
        f"▸ Premium оформлено: <b>{premium_today}</b>",
        f"▸ Доход: <b>{revenue_today} Stars</b>",
    ]

    if top_queries:
        lines.append("")
        lines.append("<b>Топ запросы:</b>")
        for i, (query, cnt) in enumerate(top_queries, 1):
            lines.append(f"{i}. {(query or '?')[:40]} — {cnt} раз")

    text = "\n".join(lines)

    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            logger.debug("Could not send digest to admin %s", admin_id)
