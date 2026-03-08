import io
import json
import logging

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select, update

from bot.config import settings
from bot.db import get_admin_logs, get_or_create_user, is_admin, log_admin_action, upsert_track
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory, Payment, Track
from bot.models.user import User
from bot.services.cache import cache

logger = logging.getLogger(__name__)

router = Router()

_USERS_PER_PAGE = 10

# Admin state for forwarding audio → LIVE
# {user_id: {"label": str, "count": int, "track_ids": list[int]}}
_admin_fwd_state: dict[int, dict] = {}

_LIVE_TRACKS_PER_PAGE = 8


class AdmUserCb(CallbackData, prefix="au"):
    act: str   # list / prem / unprem
    uid: int = 0
    p: int = 0  # page


class AdmTrackCb(CallbackData, prefix="at"):
    act: str     # list / del
    ch: str = "" # tequila / fullmoon
    tid: int = 0 # track id
    p: int = 0   # page


def _is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


async def _resolve_user(identifier: str):
    """Resolve user by ID or @username. Returns (User, error_text)."""
    identifier = identifier.strip().lstrip("@")
    async with async_session() as session:
        # Try as numeric ID first
        try:
            uid = int(identifier)
            user = await session.get(User, uid)
            if user:
                return user, None
            return None, f"Пользователь {uid} не найден в базе."
        except ValueError:
            pass
        # Try as username (case-insensitive)
        result = await session.execute(
            select(User).where(func.lower(User.username) == identifier.lower())
        )
        user = result.scalar_one_or_none()
        if user:
            return user, None
        return None, f"Пользователь @{identifier} не найден в базе."


async def _build_detailed_stats() -> str:
    """Build a detailed admin stats message."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    async with async_session() as session:
        # ── Users ─────────────────────────────────
        user_total = await session.scalar(
            select(func.count()).select_from(User)
        ) or 0
        users_today = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.created_at >= today_start)
        ) or 0
        users_week = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.created_at >= week_ago)
        ) or 0

        # ── DAU / WAU / MAU ───────────────────────
        dau = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.last_active >= today_start)
        ) or 0
        wau = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.last_active >= week_ago)
        ) or 0
        mau = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.last_active >= month_ago)
        ) or 0
        banned_count = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.is_banned == True)  # noqa: E712
        ) or 0

        # ── Premium ───────────────────────────────
        premium_total = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.is_premium == True)  # noqa: E712
        ) or 0
        admin_premium = await session.scalar(
            select(func.count()).select_from(User)
            .where(User.is_premium == True, User.premium_until == None)  # noqa: E711,E712
        ) or 0
        paid_premium = premium_total - admin_premium

        # ── Revenue (Stars) ───────────────────────
        total_revenue = await session.scalar(
            select(func.sum(Payment.amount))
        ) or 0
        payment_count = await session.scalar(
            select(func.count()).select_from(Payment)
        ) or 0
        revenue_month = await session.scalar(
            select(func.sum(Payment.amount))
            .where(Payment.created_at >= month_ago)
        ) or 0

        # ── Tracks & Downloads ────────────────────
        track_total = await session.scalar(
            select(func.count()).select_from(Track)
        ) or 0
        total_downloads = await session.scalar(
            select(func.sum(Track.downloads))
        ) or 0
        total_requests = await session.scalar(
            select(func.sum(User.request_count))
        ) or 0

        # ── Listening events ──────────────────────
        plays_today = await session.scalar(
            select(func.count()).select_from(ListeningHistory)
            .where(ListeningHistory.action == "play", ListeningHistory.created_at >= today_start)
        ) or 0
        plays_week = await session.scalar(
            select(func.count()).select_from(ListeningHistory)
            .where(ListeningHistory.action == "play", ListeningHistory.created_at >= week_ago)
        ) or 0
        searches_today = await session.scalar(
            select(func.count()).select_from(ListeningHistory)
            .where(ListeningHistory.action == "search", ListeningHistory.created_at >= today_start)
        ) or 0
        likes = await session.scalar(
            select(func.count()).select_from(ListeningHistory)
            .where(ListeningHistory.action == "like")
        ) or 0
        dislikes = await session.scalar(
            select(func.count()).select_from(ListeningHistory)
            .where(ListeningHistory.action == "dislike")
        ) or 0

        # ── Source breakdown ──────────────────────
        source_result = await session.execute(
            select(ListeningHistory.source, func.count().label("cnt"))
            .where(ListeningHistory.action == "play")
            .group_by(ListeningHistory.source)
        )
        source_stats = {row[0] or "unknown": row[1] for row in source_result.all()}
        total_plays_all = sum(source_stats.values()) or 1

        # ── Top-10 queries today ──────────────────
        top_queries_r = await session.execute(
            select(ListeningHistory.query, func.count().label("cnt"))
            .where(
                ListeningHistory.action == "search",
                ListeningHistory.created_at >= today_start,
                ListeningHistory.query.is_not(None),
            )
            .group_by(ListeningHistory.query)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_queries = top_queries_r.all()

        # ── Top 5 tracks ─────────────────────────
        top_tracks_result = await session.execute(
            select(Track.artist, Track.title, Track.downloads)
            .order_by(Track.downloads.desc())
            .limit(5)
        )
        top_tracks = top_tracks_result.all()

        # ── Languages ─────────────────────────────
        lang_result = await session.execute(
            select(User.language, func.count())
            .group_by(User.language)
        )
        lang_stats = {row[0]: row[1] for row in lang_result.all()}

    # Format message
    lines = [
        "<b>◆ Подробная статистика бота</b>",
        "",
        "<b>◎ Пользователи:</b>",
        f"  Всего: <b>{user_total}</b>",
        f"  Новых сегодня: <b>{users_today}</b>",
        f"  Новых за неделю: <b>{users_week}</b>",
        f"  DAU: <b>{dau}</b> | WAU: <b>{wau}</b> | MAU: <b>{mau}</b>",
        f"  Забанено: <b>{banned_count}</b>",
        "",
        "<b>◇ Premium:</b>",
        f"  Всего: <b>{premium_total}</b>",
        f"  Оплаченных: <b>{paid_premium}</b>",
        f"  Админских: <b>{admin_premium}</b>",
        "",
        "<b>★ Доход (Telegram Stars):</b>",
        f"  Всего заработано: <b>{total_revenue} ★</b>",
        f"  Кол-во оплат: <b>{payment_count}</b>",
        f"  За последний месяц: <b>{revenue_month} ★</b>",
        "",
        "<b>♪ Треки:</b>",
        f"  В базе: <b>{track_total}</b>",
        f"  Скачиваний всего: <b>{total_downloads or 0}</b>",
        f"  Запросов всего: <b>{total_requests or 0}</b>",
        "",
        "<b>▸ Активность:</b>",
        f"  Прослушиваний сегодня: <b>{plays_today}</b>",
        f"  Прослушиваний за неделю: <b>{plays_week}</b>",
        f"  Поисков сегодня: <b>{searches_today}</b>",
        f"  Лайков: <b>{likes}</b> | Дизлайков: <b>{dislikes}</b>",
        "",
        "<b>📊 Источники (play):</b>",
    ]
    for src, cnt in sorted(source_stats.items(), key=lambda x: -x[1]):
        pct = cnt * 100 / total_plays_all
        lines.append(f"  {src}: <b>{cnt}</b> ({pct:.1f}%)")

    lines.append("")
    lines.append("<b>○ Языки:</b>")
    for lang_code, count in sorted(lang_stats.items(), key=lambda x: -x[1]):
        flag = {"ru": "🇷🇺", "kg": "🇰🇬", "en": "🇬🇧"}.get(lang_code, "?")
        lines.append(f"  {flag} {lang_code}: <b>{count}</b>")

    if top_queries:
        lines.append("")
        lines.append("<b>🔍 Топ запросы сегодня:</b>")
        for i, (query, cnt) in enumerate(top_queries, 1):
            lines.append(f"  {i}. {(query or '?')[:40]} ({cnt})")

    if top_tracks:
        lines.append("")
        lines.append("<b>◆ Топ-5 треков:</b>")
        for i, (artist, title, downloads) in enumerate(top_tracks, 1):
            lines.append(f"  {i}. {artist or '?'} — {title or '?'} ({downloads} скач.)")

    return "\n".join(lines)


async def _export_stats_csv(message: Message) -> None:
    """Export users, tracks and recent activity as CSV."""
    import csv
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    buf = io.StringIO()
    writer = csv.writer(buf)

    async with async_session() as session:
        # ── Users sheet ──
        buf.write("# USERS\n")
        writer.writerow(["id", "username", "first_name", "language", "quality",
                         "is_premium", "is_banned", "request_count", "created_at", "last_active"])
        users = (await session.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
        for u in users:
            writer.writerow([
                u.id, u.username or "", u.first_name or "", u.language,
                u.quality, u.is_premium, u.is_banned, u.request_count,
                str(u.created_at)[:19], str(u.last_active)[:19],
            ])

        # ── Tracks sheet ──
        buf.write("\n# TRACKS\n")
        writer.writerow(["id", "source_id", "source", "artist", "title",
                         "genre", "duration", "downloads", "created_at"])
        tracks = (await session.execute(
            select(Track).order_by(Track.downloads.desc()).limit(500)
        )).scalars().all()
        for tr in tracks:
            writer.writerow([
                tr.id, tr.source_id, tr.source, tr.artist or "",
                tr.title or "", tr.genre or "", tr.duration or "",
                tr.downloads, str(tr.created_at)[:19],
            ])

        # ── Recent activity ──
        buf.write("\n# LISTENING_HISTORY (last 7 days)\n")
        writer.writerow(["user_id", "track_id", "action", "source", "query", "created_at"])
        events = (await session.execute(
            select(ListeningHistory)
            .where(ListeningHistory.created_at >= week_ago)
            .order_by(ListeningHistory.created_at.desc())
            .limit(2000)
        )).scalars().all()
        for ev in events:
            writer.writerow([
                ev.user_id, ev.track_id or "", ev.action,
                ev.source or "", (ev.query or "")[:80],
                str(ev.created_at)[:19],
            ])

    data = buf.getvalue().encode("utf-8")
    doc = BufferedInputFile(data, filename=f"stats_{now.strftime('%Y%m%d_%H%M')}.csv")
    await message.answer_document(doc, caption="📊 Экспорт статистики")


def _admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◎ Статистика", callback_data="adm:stats"),
                InlineKeyboardButton(text="◈ Рассылка", callback_data="adm:broadcast"),
            ],
            [
                InlineKeyboardButton(text="◇ Дать Premium", callback_data="adm:premium"),
                InlineKeyboardButton(text="✖ Бан", callback_data="adm:ban"),
            ],
            [
                InlineKeyboardButton(text="◎ Пользователи", callback_data=AdmUserCb(act="list").pack()),
            ],
            [
                InlineKeyboardButton(text="▸ Очередь эфира", callback_data="adm:queue"),
                InlineKeyboardButton(text="▸▸ Скип трек", callback_data="adm:skip"),
            ],
            [
                InlineKeyboardButton(text="◈ Загрузить треки", callback_data="adm:load"),
                InlineKeyboardButton(text="♪ Треки LIVE", callback_data="adm:trackmenu"),
            ],
            [
                InlineKeyboardButton(text="◑ Режим эфира", callback_data="adm:mode"),
                InlineKeyboardButton(text="≡ Настройки", callback_data="adm:settings"),
            ],
            [
                InlineKeyboardButton(text="◁ Назад", callback_data="adm:back"),
            ],
        ]
    )


# ── Admin content settings (stored in Redis) ──────────────────────────────────

_SETTINGS_KEYS = {
    "max_results": {"label": "Макс. результатов", "default": "10", "options": ["5", "10", "15", "20"]},
    "max_duration": {"label": "Макс. длина трека (сек)", "default": "600", "options": ["300", "600", "900", "1200"]},
    "default_bitrate": {"label": "Битрейт по умолч.", "default": "192", "options": ["128", "192", "320"]},
    "search_source": {"label": "Источник поиска", "default": "all", "options": ["all", "youtube", "soundcloud"]},
}


async def _get_setting(key: str) -> str:
    val = await cache.redis.get(f"bot:setting:{key}")
    if val:
        return val if isinstance(val, str) else val.decode()
    return _SETTINGS_KEYS[key]["default"]


async def _set_setting(key: str, value: str) -> None:
    await cache.redis.set(f"bot:setting:{key}", value)


async def _build_settings_text() -> str:
    lines = ["<b>≡ Настройки контента</b>\n"]
    for key, meta in _SETTINGS_KEYS.items():
        val = await _get_setting(key)
        lines.append(f"  {meta['label']}: <b>{val}</b>")
    lines.append("\nНажми на параметр чтобы изменить:")
    return "\n".join(lines)


def _build_settings_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, meta in _SETTINGS_KEYS.items():
        rows.append([InlineKeyboardButton(
            text=f"≡ {meta['label']}",
            callback_data=f"adm:set:{key}",
        )])
    rows.append([InlineKeyboardButton(text="◁ Админ-панель", callback_data="action:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return

    user = await get_or_create_user(message.from_user)
    lang = user.language
    args = message.text.split(maxsplit=2)
    subcmd = args[1].lower() if len(args) > 1 else "stats"

    # /admin стоп — exit forward mode
    if subcmd in ("стоп", "stop"):
        uid = message.from_user.id
        if uid in _admin_fwd_state:
            _admin_fwd_state.pop(uid)
            await message.answer("✓ Режим пересылки отключён.")
        else:
            await message.answer("Режим пересылки не активен.")
        return

    # /admin stats
    if subcmd == "stats":
        text = await _build_detailed_stats()
        await message.answer(text, parse_mode="HTML")

    # /admin ban <user_id | @username>
    elif subcmd == "ban":
        if len(args) < 3:
            await message.answer("Использование: /admin ban <user_id или @username>")
            return
        target, err = await _resolve_user(args[2])
        if not target:
            await message.answer(err)
            return

        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == target.id).values(is_banned=True)
            )
            await session.commit()

        label = f"@{target.username}" if target.username else str(target.id)
        await message.answer(f"Пользователь {label} заблокирован.")
        logger.info("Admin %s banned user %s", message.from_user.id, target.id)
        await log_admin_action(message.from_user.id, "ban", target.id)

    # /admin unban <user_id | @username>
    elif subcmd == "unban":
        if len(args) < 3:
            await message.answer("Использование: /admin unban <user_id или @username>")
            return
        target, err = await _resolve_user(args[2])
        if not target:
            await message.answer(err)
            return
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == target.id).values(is_banned=False)
            )
            await session.commit()
        label = f"@{target.username}" if target.username else str(target.id)
        await message.answer(f"Пользователь {label} разблокирован.")
        await log_admin_action(message.from_user.id, "unban", target.id)

    # /admin broadcast <текст>
    elif subcmd == "broadcast":
        if len(args) < 3:
            await message.answer("Использование: /admin broadcast <текст>")
            return
        text = args[2]
        await _broadcast(bot, message, text)
        await log_admin_action(message.from_user.id, "broadcast", details=text[:200])

    # /admin premium <user_id | @username>  — выдать premium вручную
    elif subcmd == "premium":
        if len(args) < 3:
            await message.answer("Использование: /admin premium <user_id или @username>")
            return
        target, err = await _resolve_user(args[2])
        if not target:
            await message.answer(err)
            return
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == target.id).values(is_premium=True)
            )
            await session.commit()
        label = f"@{target.username}" if target.username else str(target.id)
        await message.answer(f"Premium выдан пользователю {label}.")
        await log_admin_action(message.from_user.id, "premium", target.id)

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

    # /admin tracks tequila|fullmoon — manage tracks
    elif subcmd == "tracks":
        if len(args) < 3 or args[2].lower() not in ("tequila", "fullmoon"):
            await message.answer(
                "Использование:\n"
                "<code>/admin tracks tequila</code>\n"
                "<code>/admin tracks fullmoon</code>",
                parse_mode="HTML",
            )
            return
        label = args[2].lower()
        text, kb = await _build_tracks_list(label, page=0)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

    # /admin load @channel tequila|fullmoon — загрузить треки из TG-канала
    elif subcmd == "load":
        if len(args) < 4:
            await message.answer(
                "Использование:\n"
                "<code>/admin load @channel_name tequila</code>\n"
                "<code>/admin load @channel_name fullmoon</code>",
                parse_mode="HTML",
            )
            return
        channel_ref = args[2]
        label = args[3].lower()
        if label not in ("tequila", "fullmoon"):
            await message.answer("Метка канала: tequila или fullmoon")
            return
        await _load_channel_tracks(bot, message, channel_ref, label)

    # /admin audit — last 20 admin actions
    elif subcmd == "audit":
        logs = await get_admin_logs(limit=20)
        if not logs:
            await message.answer("Журнал пуст.")
            return
        lines = ["<b>📋 Журнал действий:</b>\n"]
        for entry in logs:
            ts = entry.created_at.strftime("%d.%m %H:%M") if entry.created_at else "?"
            target = f" → {entry.target_user_id}" if entry.target_user_id else ""
            detail = f" | {entry.details[:60]}" if entry.details else ""
            lines.append(f"<code>{ts}</code> [{entry.action}] admin:{entry.admin_id}{target}{detail}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    # /admin export — CSV stats export
    elif subcmd == "export":
        await _export_stats_csv(message)

    else:
        await message.answer(
            "<b>Команды админа:</b>\n"
            "/admin stats — статистика\n"
            "/admin ban &lt;id или @username&gt; — бан\n"
            "/admin unban &lt;id или @username&gt; — разбан\n"
            "/admin broadcast &lt;текст&gt; — рассылка\n"
            "/admin premium &lt;id или @username&gt; — выдать premium\n"
            "/admin queue — очередь эфира\n"
            "/admin skip — пропустить трек\n"
            "/admin mode &lt;режим&gt; — режим эфира\n"
            "/admin tracks &lt;tequila|fullmoon&gt; — управление треками\n"
            "/admin load &lt;@channel&gt; &lt;tequila|fullmoon&gt; — загрузить из канала\n"
            "/admin audit — журнал действий\n"
            "/admin export — экспорт статистики CSV",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "action:admin")
async def handle_admin_panel(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    try:
        await callback.message.edit_text(
            "<b>◆ Админ-панель</b>\n\nВыбери действие:",
            reply_markup=_admin_panel_keyboard(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "<b>◆ Админ-панель</b>\n\nВыбери действие:",
            reply_markup=_admin_panel_keyboard(),
            parse_mode="HTML",
        )


_back_to_panel_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="◁ Админ-панель", callback_data="action:admin")],
])


@router.callback_query(lambda c: c.data == "adm:stats")
async def handle_adm_stats(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    text = await _build_detailed_stats()
    try:
        await callback.message.edit_text(text, reply_markup=_back_to_panel_kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=_back_to_panel_kb, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "adm:skip")
async def handle_adm_skip(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    await cache.redis.publish("radio:cmd", "skip")
    try:
        await callback.message.edit_text(
            "▸▸ Команда skip отправлена в эфир.",
            reply_markup=_back_to_panel_kb,
        )
    except Exception:
        await callback.message.answer("▸▸ Команда skip отправлена в эфир.", reply_markup=_back_to_panel_kb)


@router.callback_query(lambda c: c.data == "adm:queue")
async def handle_adm_queue(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
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
    try:
        await callback.message.edit_text(
            "\n".join(lines), reply_markup=_back_to_panel_kb, parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            "\n".join(lines), reply_markup=_back_to_panel_kb, parse_mode="HTML"
        )


@router.callback_query(lambda c: c.data == "adm:back")
async def handle_adm_back(callback: CallbackQuery) -> None:
    await callback.answer()
    from bot.handlers.start import _main_menu
    user = await get_or_create_user(callback.from_user)
    try:
        await callback.message.edit_text(
            t(user.language, "start_message", name=callback.from_user.first_name or ""),
            reply_markup=_main_menu(user.language, _is_admin(callback.from_user.id)),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            t(user.language, "start_message", name=callback.from_user.first_name or ""),
            reply_markup=_main_menu(user.language, _is_admin(callback.from_user.id)),
            parse_mode="HTML",
        )


# ── Admin user list with premium toggle ────────────────────────────────────────


async def _build_user_list_kb(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    async with async_session() as session:
        total = await session.scalar(select(func.count()).select_from(User)) or 0
        result = await session.execute(
            select(User)
            .order_by(User.created_at.desc())
            .offset(page * _USERS_PER_PAGE)
            .limit(_USERS_PER_PAGE)
        )
        users = list(result.scalars().all())

    rows = []
    for u in users:
        name = u.username or u.first_name or str(u.id)
        label = f"{'\u25c7' if u.is_premium else '\u25cb'} @{name}" if u.username else f"{'\u25c7' if u.is_premium else '\u25cb'} {name}"
        if u.is_premium:
            btn_text = "\u2717"
            btn_cb = AdmUserCb(act="unprem", uid=u.id, p=page).pack()
        else:
            btn_text = "\u25c7"
            btn_cb = AdmUserCb(act="prem", uid=u.id, p=page).pack()
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"noop:u{u.id}"),
            InlineKeyboardButton(text=btn_text, callback_data=btn_cb),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="\u25c1", callback_data=AdmUserCb(act="list", p=page - 1).pack(),
        ))
    total_pages = (total + _USERS_PER_PAGE - 1) // _USERS_PER_PAGE
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop:pg"))
    if (page + 1) * _USERS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(
            text="\u25b7", callback_data=AdmUserCb(act="list", p=page + 1).pack(),
        ))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="\u25c1 \u041d\u0430\u0437\u0430\u0434", callback_data="action:admin")])

    text = f"<b>\u25ce \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438</b> ({total})\n\n\u25c7 = Premium \u00b7 \u25cb = Free\n\u041d\u0430\u0436\u043c\u0438 \u25c7 \u0447\u0442\u043e\u0431\u044b \u0432\u044b\u0434\u0430\u0442\u044c, \u2717 \u0447\u0442\u043e\u0431\u044b \u0441\u043d\u044f\u0442\u044c."
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(AdmUserCb.filter(F.act == "list"))
async def handle_user_list(callback: CallbackQuery, callback_data: AdmUserCb) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    text, kb = await _build_user_list_kb(callback_data.p)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(AdmUserCb.filter(F.act == "prem"))
async def handle_grant_premium(callback: CallbackQuery, callback_data: AdmUserCb) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == callback_data.uid).values(is_premium=True)
        )
        await session.commit()
    await log_admin_action(callback.from_user.id, "premium", callback_data.uid)
    await callback.answer("\u25c7 Premium \u0432\u044b\u0434\u0430\u043d", show_alert=False)
    text, kb = await _build_user_list_kb(callback_data.p)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(AdmUserCb.filter(F.act == "unprem"))
async def handle_revoke_premium(callback: CallbackQuery, callback_data: AdmUserCb) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == callback_data.uid).values(is_premium=False, premium_until=None)
        )
        await session.commit()
    await log_admin_action(callback.from_user.id, "unprem", callback_data.uid)
    await callback.answer("\u2717 Premium \u0441\u043d\u044f\u0442", show_alert=False)
    text, kb = await _build_user_list_kb(callback_data.p)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(lambda c: c.data and c.data.startswith("adm:set:"))
async def handle_adm_set(callback: CallbackQuery) -> None:
    """Cycle through setting options."""
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    key = callback.data.split("adm:set:", 1)[1]
    if key not in _SETTINGS_KEYS:
        await callback.answer("Неизвестный параметр")
        return
    meta = _SETTINGS_KEYS[key]
    current = await _get_setting(key)
    opts = meta["options"]
    idx = opts.index(current) if current in opts else 0
    new_val = opts[(idx + 1) % len(opts)]
    await _set_setting(key, new_val)
    await callback.answer(f"{meta['label']}: {new_val}")
    text = await _build_settings_text()
    kb = _build_settings_keyboard()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(lambda c: c.data and c.data.startswith("adm:"))
async def handle_adm_prompt(callback: CallbackQuery) -> None:
    """Handle admin buttons that need text input — show instructions."""
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    prompts = {
        "adm:broadcast": "Для рассылки используй:\n<code>/admin broadcast текст</code>",
        "adm:premium": "Для выдачи Premium:\n<code>/admin premium @username</code>\nили\n<code>/admin premium user_id</code>",
        "adm:ban": "Для бана:\n<code>/admin ban @username</code>\nДля разбана:\n<code>/admin unban @username</code>\n\nМожно также по ID.",
        "adm:mode": "Для смены режима:\n<code>/admin mode night|energy|hybrid</code>",
        "adm:load": None,  # handled separately below
        "adm:trackmenu": None,  # handled separately below
        "adm:settings": None,  # handled separately above
    }
    if callback.data == "adm:settings":
        text = await _build_settings_text()
        kb = _build_settings_keyboard()
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        return
    if callback.data == "adm:trackmenu":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="● TEQUILA", callback_data=AdmTrackCb(act="list", ch="tequila").pack()),
                InlineKeyboardButton(text="◑ FULLMOON", callback_data=AdmTrackCb(act="list", ch="fullmoon").pack()),
            ],
        ])
        await callback.message.answer(
            "♪ <b>Треки LIVE</b>\n\nВыбери канал для просмотра и управления:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return
    if callback.data == "adm:load":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="● TEQUILA", callback_data="adm:fwd:tequila"),
                InlineKeyboardButton(text="◑ FULLMOON", callback_data="adm:fwd:fullmoon"),
            ],
            [
                InlineKeyboardButton(text="✖ Отмена", callback_data="adm:fwd:cancel"),
            ],
        ])
        await callback.message.answer(
            "◈ <b>Загрузка треков для LIVE</b>\n\n"
            "Выбери канал, затем <b>пересылай аудио</b> сюда.\n"
            "Когда закончишь — нажми <b>✓ Готово</b>.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return
    text = prompts.get(callback.data, "Используй команду /admin")
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("adm:fwd:"))
async def handle_fwd_select(callback: CallbackQuery) -> None:
    """Admin selects which LIVE channel to forward audio to."""
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    choice = callback.data.split(":")[-1]  # tequila / fullmoon / cancel / done
    uid = callback.from_user.id
    if choice == "cancel":
        _admin_fwd_state.pop(uid, None)
        await callback.message.edit_text("✖ Режим пересылки отменён.")
        return
    if choice == "done":
        state = _admin_fwd_state.pop(uid, None)
        cnt = state["count"] if state else 0
        label = state["label"] if state else "?"
        label_name = "TEQUILA" if label == "tequila" else "FULLMOON"
        await callback.message.edit_text(
            f"✓ <b>Загрузка завершена!</b>\n\n"
            f"♪ Добавлено треков: <b>{cnt}</b> → {label_name} LIVE\n\n"
            f"Управлять треками: /admin tracks {label}",
            parse_mode="HTML",
        )
        return
    _admin_fwd_state[uid] = {"label": choice, "count": 0, "track_ids": []}
    label_name = "TEQUILA" if choice == "tequila" else "FULLMOON"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✓ Готово", callback_data="adm:fwd:done")],
        [InlineKeyboardButton(text="✖ Отмена", callback_data="adm:fwd:cancel")],
    ])
    await callback.message.edit_text(
        f"● Режим загрузки: <b>{label_name}</b>\n\n"
        f"Пересылай аудио сюда — бот сохранит их для {label_name} LIVE.\n"
        f"Добавлено: <b>0</b> треков\n\n"
        f"Когда закончишь — нажми <b>✓ Готово</b>",
        parse_mode="HTML",
        reply_markup=kb,
    )


class _AdminForwardFilter(BaseFilter):
    """Match only when admin is in forward-audio mode."""
    async def __call__(self, message: Message) -> bool:
        return (
            message.audio is not None
            and message.chat.type == "private"
            and message.from_user.id in _admin_fwd_state
            and _is_admin(message.from_user.id)
        )


@router.message(_AdminForwardFilter())
async def handle_forwarded_audio(message: Message) -> None:
    """Save forwarded audio to LIVE when admin is in forward mode."""
    uid = message.from_user.id
    state = _admin_fwd_state.get(uid)
    if not state:
        return
    label = state["label"]
    audio = message.audio
    fwd_chat = message.forward_from_chat
    if fwd_chat:
        source_id = f"tg_{fwd_chat.id}_{message.forward_from_message_id}"
    else:
        source_id = f"tg_fwd_{uid}_{message.message_id}"
    track = await upsert_track(
        source_id=source_id,
        title=audio.title or audio.file_name or "Unknown",
        artist=audio.performer or "",
        duration=audio.duration,
        file_id=audio.file_id,
        source="channel",
        channel=label,
    )
    state["count"] += 1
    state["track_ids"].append(track.id)
    label_name = "TEQUILA" if label == "tequila" else "FULLMOON"
    await message.reply(
        f"✓ [{state['count']}] <b>{audio.performer or ''} — {audio.title or 'Unknown'}</b> → {label_name}",
        parse_mode="HTML",
    )
    logger.info("Admin %s forwarded audio %s → %s (count=%d)", uid, source_id, label, state["count"])


# ── Track management (list + delete) ────────────────────────────────────

async def _build_tracks_list(channel: str, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    """Build a paginated track list for the given channel with delete buttons."""
    label_name = "TEQUILA" if channel == "tequila" else "FULLMOON"
    async with async_session() as session:
        total = await session.scalar(
            select(func.count()).select_from(Track).where(Track.channel == channel)
        ) or 0
        result = await session.execute(
            select(Track)
            .where(Track.channel == channel)
            .order_by(Track.created_at.desc())
            .offset(page * _LIVE_TRACKS_PER_PAGE)
            .limit(_LIVE_TRACKS_PER_PAGE)
        )
        tracks = list(result.scalars().all())

    lines = [f"♪ <b>{label_name} LIVE</b> — треков: {total}\n"]
    rows = []
    for tr in tracks:
        dur = f"{tr.duration // 60}:{tr.duration % 60:02d}" if tr.duration else "?:??"
        lines.append(f"  {tr.artist or '?'} — {tr.title or '?'} ({dur})")
        rows.append([
            InlineKeyboardButton(
                text=f"✖ {tr.artist or '?'} — {(tr.title or '?')[:30]}",
                callback_data=AdmTrackCb(act="del", ch=channel, tid=tr.id, p=page).pack(),
            )
        ])

    if not tracks:
        lines.append("  (пусто)")

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◁ Назад",
            callback_data=AdmTrackCb(act="list", ch=channel, p=page - 1).pack(),
        ))
    if (page + 1) * _LIVE_TRACKS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(
            text="Далее ▷",
            callback_data=AdmTrackCb(act="list", ch=channel, p=page + 1).pack(),
        ))
    if nav:
        rows.append(nav)

    # Add more tracks button
    rows.append([
        InlineKeyboardButton(text="◈ Добавить ещё", callback_data="adm:load"),
    ])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(AdmTrackCb.filter(F.act == "list"))
async def handle_track_list_page(callback: CallbackQuery, callback_data: AdmTrackCb) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    text, kb = await _build_tracks_list(callback_data.ch, callback_data.p)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(AdmTrackCb.filter(F.act == "del"))
async def handle_track_delete(callback: CallbackQuery, callback_data: AdmTrackCb) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        track = await session.get(Track, callback_data.tid)
        if track:
            await session.delete(track)
            await session.commit()
            await callback.answer(f"✖ Удалён: {track.artist} — {track.title}", show_alert=False)
        else:
            await callback.answer("Трек не найден", show_alert=False)
    text, kb = await _build_tracks_list(callback_data.ch, callback_data.p)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


async def _load_channel_tracks(bot: Bot, admin_msg: Message, channel_ref: str, label: str) -> None:
    """Read audio messages from a Telegram channel and save them to DB + Redis queue."""
    import asyncio

    status = await admin_msg.answer(
        f"◈ Загружаю аудио из канала <b>{channel_ref}</b> → <b>{label.upper()}</b>...",
        parse_mode="HTML",
    )

    try:
        chat = await bot.get_chat(channel_ref)
    except Exception as e:
        await status.edit_text(f"✖ Не удалось найти канал {channel_ref}: {e}")
        return

    chat_id = chat.id
    saved, skipped, errors = 0, 0, 0

    # Scan messages sequentially from ID 1 upward.
    # Stop after 30 consecutive failures (end of channel).
    msg_id = 0
    consecutive_fails = 0
    max_consecutive_fails = 30

    while consecutive_fails < max_consecutive_fails:
        msg_id += 1
        try:
            fwd = await bot.forward_message(
                chat_id=admin_msg.from_user.id,
                from_chat_id=chat_id,
                message_id=msg_id,
                disable_notification=True,
            )
            consecutive_fails = 0  # reset on success

            if fwd.audio:
                audio = fwd.audio
                source_id = f"tg_{chat_id}_{msg_id}"
                title = audio.title or audio.file_name or "Unknown"
                artist = audio.performer or ""

                track = await upsert_track(
                    source_id=source_id,
                    title=title,
                    artist=artist,
                    duration=audio.duration,
                    file_id=audio.file_id,
                    source="channel",
                    channel=label,
                )

                # Add to radio queue
                await cache.redis.rpush(
                    f"radio:queue:{label}",
                    json.dumps({
                        "track_id": track.id,
                        "file_id": audio.file_id,
                        "title": title,
                        "artist": artist,
                        "duration": audio.duration,
                        "channel": label,
                    }),
                )
                saved += 1
            else:
                skipped += 1

            # Delete the forwarded message to keep admin chat clean
            try:
                await bot.delete_message(admin_msg.from_user.id, fwd.message_id)
            except Exception:
                pass

            await asyncio.sleep(0.1)  # rate limit

        except Exception:
            consecutive_fails += 1
            errors += 1
            await asyncio.sleep(0.05)

        # Progress update every 50 messages
        if msg_id % 50 == 0:
            try:
                await status.edit_text(
                    f"◈ Прогресс: сообщение #{msg_id}\n"
                    f"♪ Аудио: {saved} · Пропущено: {skipped} · Ошибок: {errors}",
                )
            except Exception:
                pass

    if saved == 0 and msg_id <= max_consecutive_fails:
        await status.edit_text(
            "✖ Канал пуст или бот не имеет доступа к сообщениям.\n"
            "Проверь что бот добавлен в канал как администратор!",
        )
        return

    await status.edit_text(
        f"✓ <b>Загрузка завершена!</b>\n\n"
        f"Канал: {channel_ref} → {label.upper()}\n"
        f"♪ Аудио загружено: <b>{saved}</b>\n"
        f"Пропущено (не аудио): {skipped}\n"
        f"Ошибок: {errors}",
        parse_mode="HTML",
    )
    logger.info(
        "Admin %s loaded %d tracks from %s → %s",
        admin_msg.from_user.id, saved, channel_ref, label,
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
