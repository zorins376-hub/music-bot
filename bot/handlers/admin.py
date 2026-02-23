import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select, update

from bot.config import settings
from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import Track
from bot.models.user import User
from bot.services.cache import cache

logger = logging.getLogger(__name__)

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return

    user = await get_or_create_user(message.from_user)
    lang = user.language
    args = message.text.split(maxsplit=2)
    subcmd = args[1].lower() if len(args) > 1 else "stats"

    # /admin stats
    if subcmd == "stats":
        async with async_session() as session:
            user_count = await session.scalar(select(func.count()).select_from(User))
            track_count = await session.scalar(select(func.count()).select_from(Track))
            total_req = await session.scalar(select(func.sum(User.request_count)))
            premium_count = await session.scalar(
                select(func.count()).select_from(User).where(User.is_premium == True)  # noqa: E712
            )

        lines = [
            t(lang, "stats_header"),
            t(lang, "stats_users", count=user_count or 0),
            f"◇ Premium: {premium_count or 0}",
            t(lang, "stats_tracks", count=track_count or 0),
            t(lang, "stats_requests", count=total_req or 0),
        ]
        await message.answer("\n".join(lines), parse_mode="HTML")

    # /admin ban <user_id>
    elif subcmd == "ban":
        if len(args) < 3:
            await message.answer("Использование: /admin ban <user_id>")
            return
        try:
            target_id = int(args[2])
        except ValueError:
            await message.answer("user_id должен быть числом")
            return

        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == target_id).values(is_banned=True)
            )
            await session.commit()

        await message.answer(f"Пользователь {target_id} заблокирован.")
        logger.info("Admin %s banned user %s", message.from_user.id, target_id)

    # /admin unban <user_id>
    elif subcmd == "unban":
        if len(args) < 3:
            await message.answer("Использование: /admin unban <user_id>")
            return
        target_id = int(args[2])
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == target_id).values(is_banned=False)
            )
            await session.commit()
        await message.answer(f"Пользователь {target_id} разблокирован.")

    # /admin broadcast <текст>
    elif subcmd == "broadcast":
        if len(args) < 3:
            await message.answer("Использование: /admin broadcast <текст>")
            return
        text = args[2]
        await _broadcast(bot, message, text)

    # /admin premium <user_id>  — выдать premium вручную
    elif subcmd == "premium":
        if len(args) < 3:
            await message.answer("Использование: /admin premium <user_id>")
            return
        try:
            target_id = int(args[2])
        except ValueError:
            await message.answer("user_id должен быть числом")
            return
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == target_id).values(is_premium=True)
            )
            await session.commit()
        await message.answer(f"Premium выдан пользователю {target_id}.")

    # /admin queue — текущая очередь эфира
    elif subcmd == "queue":
        import json
        lines = ["<b>◆ Очередь эфира:</b>\n"]
        for channel in ("tequila", "fullmoon"):
            queue_key = f"radio:queue:{channel}"
            items = await cache.redis.lrange(queue_key, 0, 4)
            lines.append(f"<b>{channel.upper()}</b> ({len(items)} в очереди):")
            for i, raw in enumerate(items, 1):
                try:
                    item = json.loads(raw)
                    lines.append(f"  {i}. {item.get('artist', '?')} — {item.get('title', '?')}")
                except Exception:
                    lines.append(f"  {i}. (ошибка)")
            if not items:
                lines.append("  (пусто)")
            lines.append("")
        await message.answer("\n".join(lines), parse_mode="HTML")

    # /admin skip — пропустить текущий трек
    elif subcmd == "skip":
        await cache.redis.publish("radio:cmd", "skip")
        await message.answer("▸▸ Команда skip отправлена в эфир.")

    # /admin mode <режим>
    elif subcmd == "mode":
        if len(args) < 3:
            await message.answer(
                "Использование: /admin mode <night|energy|hybrid>\n"
                "◑ night — FULLMOON (deep/ambient)\n"
                "▸ energy — TEQUILA (энергичные)\n"
                "✦ hybrid — AUTO MIX (оба канала)"
            )
            return
        mode = args[2].lower()
        if mode not in ("night", "energy", "hybrid"):
            await message.answer("Режимы: night, energy, hybrid")
            return
        await cache.redis.set("radio:mode", mode)
        labels = {"night": "◑ Night Radio", "energy": "▸ Energy Boost", "hybrid": "✦ Hybrid"}
        await message.answer(f"Режим эфира: {labels[mode]}")
        logger.info("Admin %s changed radio mode to %s", message.from_user.id, mode)

    else:
        await message.answer(
            "<b>Команды админа:</b>\n"
            "/admin stats — статистика\n"
            "/admin ban &lt;user_id&gt; — бан\n"
            "/admin unban &lt;user_id&gt; — разбан\n"
            "/admin broadcast &lt;текст&gt; — рассылка\n"
            "/admin premium &lt;user_id&gt; — выдать premium\n"
            "/admin queue — очередь эфира\n"
            "/admin skip — пропустить трек\n"
            "/admin mode &lt;режим&gt; — режим эфира (night/energy/hybrid)",
            parse_mode="HTML",
        )


async def _broadcast(bot: Bot, admin_msg: Message, text: str) -> None:
    """Broadcast to all users with Telegram-friendly rate limiting."""
    import asyncio
    async with async_session() as session:
        result = await session.execute(
            select(User.id).where(User.is_banned == False)  # noqa: E712
        )
        user_ids = [row[0] for row in result.all()]

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 msg/sec, safe for Telegram limits

    await admin_msg.answer(
        f"Broadcast done.\nSent: {sent}\nFailed: {failed}"
    )
