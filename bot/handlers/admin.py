import io
import json
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import case, func, select, update, and_

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


class BroadcastState(StatesGroup):
    waiting_message = State()  # admin sends text/photo/gif for broadcast


# Admin rate limiting: max operations per minute
_ADMIN_RATE_LIMIT = 15
_ADMIN_RATE_WINDOW = 60  # seconds


def _admin_rate_key(user_id: int) -> str:
    return f"admin:rate:{user_id}"


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
    """Build a detailed admin stats message (optimized: ~6 queries instead of ~20)."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    async with async_session() as session:
        # ── Users: single combined query ──────────
        user_stats_r = await session.execute(
            select(
                func.count().label("total"),
                func.sum(case((User.created_at >= today_start, 1), else_=0)),
                func.sum(case((User.created_at >= week_ago, 1), else_=0)),
                func.sum(case((User.last_active >= today_start, 1), else_=0)),
                func.sum(case((User.last_active >= week_ago, 1), else_=0)),
                func.sum(case((User.last_active >= month_ago, 1), else_=0)),
                func.sum(case((User.is_banned == True, 1), else_=0)),
                func.sum(case((User.bot_blocked == True, 1), else_=0)),
                func.sum(case((User.is_premium == True, 1), else_=0)),
                func.sum(case((and_(User.is_premium == True, User.premium_until == None), 1), else_=0)),
                func.coalesce(func.sum(User.request_count), 0),
            )
        )
        u = user_stats_r.one()
        user_total = u[0] or 0
        users_today = int(u[1] or 0)
        users_week = int(u[2] or 0)
        dau = int(u[3] or 0)
        wau = int(u[4] or 0)
        mau = int(u[5] or 0)
        banned_count = int(u[6] or 0)
        blocked_count = int(u[7] or 0)
        premium_total = int(u[8] or 0)
        admin_premium = int(u[9] or 0)
        total_requests = int(u[10] or 0)
        paid_premium = premium_total - admin_premium

        # ── Payments: single combined query ───────
        pay_stats_r = await session.execute(
            select(
                func.coalesce(func.sum(Payment.amount), 0),
                func.count(),
                func.coalesce(func.sum(case((Payment.created_at >= month_ago, Payment.amount), else_=0)), 0),
            )
        )
        p = pay_stats_r.one()
        total_revenue = int(p[0] or 0)
        payment_count = int(p[1] or 0)
        revenue_month = int(p[2] or 0)

        # ── Tracks: single combined query ─────────
        track_stats_r = await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Track.downloads), 0),
            ).select_from(Track)
        )
        tr = track_stats_r.one()
        track_total = tr[0] or 0
        total_downloads = int(tr[1] or 0)

        # ── Listening events: single combined query
        lh_stats_r = await session.execute(
            select(
                func.sum(case((and_(ListeningHistory.action == "play", ListeningHistory.created_at >= today_start), 1), else_=0)),
                func.sum(case((and_(ListeningHistory.action == "play", ListeningHistory.created_at >= week_ago), 1), else_=0)),
                func.sum(case((and_(ListeningHistory.action == "search", ListeningHistory.created_at >= today_start), 1), else_=0)),
                func.sum(case((ListeningHistory.action == "like", 1), else_=0)),
                func.sum(case((ListeningHistory.action == "dislike", 1), else_=0)),
            )
        )
        lh = lh_stats_r.one()
        plays_today = int(lh[0] or 0)
        plays_week = int(lh[1] or 0)
        searches_today = int(lh[2] or 0)
        likes = int(lh[3] or 0)
        dislikes = int(lh[4] or 0)

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
        f"  🚫 Заблокировали бота: <b>{blocked_count}</b>",
        f"  ✅ Активных: <b>{user_total - blocked_count - banned_count}</b>",
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

    # ── Top tracks TODAY ──────────────────────
    async with async_session() as session:
        top_today_r = await session.execute(
            select(Track.artist, Track.title, func.count(ListeningHistory.id).label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= today_start,
            )
            .group_by(Track.id, Track.artist, Track.title)
            .order_by(func.count(ListeningHistory.id).desc())
            .limit(10)
        )
        top_today = top_today_r.all()

        # ── Retention ─────────────────────────────
        # % of users who registered N days ago and were active since
        ret_1d = ret_7d = ret_30d = 0
        for days_ago, label in [(1, "1d"), (7, "7d"), (30, "30d")]:
            reg_start = now - timedelta(days=days_ago + 1)
            reg_end = now - timedelta(days=days_ago)
            cohort = await session.scalar(
                select(func.count()).select_from(User)
                .where(User.created_at >= reg_start, User.created_at < reg_end)
            ) or 0
            returned = await session.scalar(
                select(func.count()).select_from(User)
                .where(
                    User.created_at >= reg_start,
                    User.created_at < reg_end,
                    User.last_active >= reg_end,
                )
            ) or 0
            if label == "1d":
                ret_1d = (returned * 100 // cohort) if cohort else 0
            elif label == "7d":
                ret_7d = (returned * 100 // cohort) if cohort else 0
            else:
                ret_30d = (returned * 100 // cohort) if cohort else 0

    if top_today:
        lines.append("")
        lines.append("<b>🔥 Топ-10 треков сегодня:</b>")
        for i, (artist, title, cnt) in enumerate(top_today, 1):
            lines.append(f"  {i}. {artist or '?'} — {title or '?'} ({cnt})")

    lines.append("")
    lines.append("<b>📈 Retention:</b>")
    lines.append(f"  D1: <b>{ret_1d}%</b> | D7: <b>{ret_7d}%</b> | D30: <b>{ret_30d}%</b>")

    cache_metrics = cache.get_runtime_metrics()
    lines.append("")
    lines.append("<b>⚡ Cache performance:</b>")
    lines.append(
        f"  Hit rate: <b>{cache_metrics['hit_rate']:.1f}%</b> "
        f"({cache_metrics['hits']}/{cache_metrics['gets']})"
    )
    lines.append(f"  Avg Redis GET latency: <b>{cache_metrics['avg_latency_ms']:.2f} ms</b>")

    return "\n".join(lines)


async def _build_ab_dashboard() -> str:
    """Build A/B test dashboard showing ML vs SQL recommendation CTR."""
    from datetime import datetime, timedelta, timezone
    from bot.config import settings

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Check if A/B test is enabled
    if not settings.ML_AB_TEST_ENABLED:
        return (
            "<b>🔬 A/B Test Dashboard</b>\n\n"
            "A/B тестирование отключено.\n"
            "Включить: установить <code>ML_AB_TEST_ENABLED=true</code>"
        )

    try:
        from bot.models.recommendation_log import RecommendationLog
    except ImportError:
        return (
            "<b>🔬 A/B Test Dashboard</b>\n\n"
            "⚠️ Модель RecommendationLog не найдена.\n"
            "Требуется миграция базы данных."
        )

    async with async_session() as session:
        # Get stats per algo type for the last 7 days
        stats_r = await session.execute(
            select(
                RecommendationLog.algo,
                func.count().label("total"),
                func.sum(case((RecommendationLog.clicked == True, 1), else_=0)).label("clicks"),
            )
            .where(RecommendationLog.created_at >= week_ago)
            .group_by(RecommendationLog.algo)
        )
        stats = {row[0]: {"total": row[1], "clicks": row[2] or 0} for row in stats_r.all()}

    if not stats:
        return (
            "<b>🔬 A/B Test Dashboard (7 дней)</b>\n"
            "─────────────────────────\n"
            "Нет данных. Логирование рекомендаций ещё не началось."
        )

    lines = ["<b>🔬 A/B Рекомендации (7 дней):</b>", "─────────────────────────"]

    # ML stats
    ml = stats.get("ml", {"total": 0, "clicks": 0})
    ml_ctr = (ml["clicks"] * 100 / ml["total"]) if ml["total"] else 0
    lines.append(f"ML:  показано {ml['total']}, кликнуто {ml['clicks']}, CTR = {ml_ctr:.1f}%")

    # SQL stats
    sql = stats.get("sql", {"total": 0, "clicks": 0})
    sql_ctr = (sql["clicks"] * 100 / sql["total"]) if sql["total"] else 0
    lines.append(f"SQL: показано {sql['total']}, кликнуто {sql['clicks']}, CTR = {sql_ctr:.1f}%")

    # Popular fallback stats
    popular = stats.get("popular", {"total": 0, "clicks": 0})
    if popular["total"]:
        pop_ctr = (popular["clicks"] * 100 / popular["total"])
        lines.append(f"POP: показано {popular['total']}, кликнуто {popular['clicks']}, CTR = {pop_ctr:.1f}%")

    # Lift calculation (ML vs SQL)
    lines.append("─────────────────────────")
    if sql_ctr > 0:
        lift = ((ml_ctr - sql_ctr) / sql_ctr) * 100
        lift_sign = "+" if lift >= 0 else ""
        lines.append(f"Lift (ML vs SQL): <b>{lift_sign}{lift:.1f}%</b>")
    else:
        lines.append("Lift: недостаточно данных SQL")

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
                InlineKeyboardButton(text="🆕 Рассылка версии", callback_data="adm:release"),
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
                InlineKeyboardButton(text="🩺 Здоровье провайдеров", callback_data="adm:health"),
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

    # Rate limit admin commands
    rkey = _admin_rate_key(message.from_user.id)
    try:
        cnt = await cache.redis.incr(rkey)
        if cnt == 1:
            await cache.redis.expire(rkey, _ADMIN_RATE_WINDOW)
        if cnt > _ADMIN_RATE_LIMIT:
            await message.answer("⚠️ Слишком много команд. Подожди минуту.")
            return
    except Exception:
        logger.debug("admin rate limit check failed", exc_info=True)

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

    # /admin broadcast <текст> — legacy text-only broadcast
    elif subcmd == "broadcast":
        if len(args) < 3:
            await message.answer(
                "📨 <b>Рассылка</b>\n\n"
                "Для текстовой рассылки: <code>/admin broadcast текст</code>\n\n"
                "Или нажми кнопку «◈ Рассылка» в админ-панели — "
                "там можно отправить фото, GIF или видео.",
                parse_mode="HTML",
            )
            return
        text = message.text.split(None, 2)[2]  # everything after "/admin broadcast"
        import json as _json
        await cache.redis.setex(
            f"admin:broadcast_pending:{message.from_user.id}",
            300,
            _json.dumps({"chat_id": message.chat.id, "message_id": message.message_id, "text_only": text}),
        )
        preview = text[:200] + ("..." if len(text) > 200 else "")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить рассылку", callback_data="adm:broadcast_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="adm:broadcast_cancel"),
            ]
        ])
        await message.answer(
            f"⚠️ <b>Подтверди рассылку ВСЕМ пользователям:</b>\n\n{preview}",
            parse_mode="HTML",
            reply_markup=kb,
        )

    # /admin release — force send current version changelog to eligible users
    elif subcmd in ("release", "version", "whatsnew"):
        await message.answer("⏳ Запускаю рассылку новой версии...")
        from bot.main import _broadcast_version_update
        await _broadcast_version_update(bot)
        await message.answer("✅ Рассылка новой версии завершена. Проверь логи sent/failed.")
        await log_admin_action(message.from_user.id, "version_broadcast")

    # /admin premium <user_id | @username>  — выдать premium вручную
    elif subcmd == "premium":
        if len(args) < 3:
            await message.answer("Использование: /admin premium <user_id или @username>")
            return
        target, err = await _resolve_user(args[2])
        if not target:
            await message.answer(err)
            return
        from datetime import datetime, timedelta, timezone
        premium_until = datetime.now(timezone.utc) + timedelta(days=settings.PREMIUM_DAYS)
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == target.id).values(
                    is_premium=True,
                    premium_until=premium_until,
                )
            )
            await session.commit()
        label = f"@{target.username}" if target.username else str(target.id)
        await message.answer(
            f"Premium выдан пользователю {label} на {settings.PREMIUM_DAYS} дней "
            f"(до {premium_until.strftime('%d.%m.%Y')})."
        )
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

    # /admin block <source_id> [reason] — DMCA block
    elif subcmd == "block":
        if len(args) < 3:
            await message.answer("Использование: /admin block <source_id> [причина]")
            return
        parts = args[2].split(maxsplit=1)
        source_id = parts[0]
        reason = parts[1] if len(parts) > 1 else "DMCA"
        from bot.services.dmca_filter import block_track
        blocked = await block_track(source_id, reason=reason, blocked_by=str(message.from_user.id))
        if blocked:
            await message.answer(f"🚫 Трек <code>{source_id}</code> заблокирован ({reason}).", parse_mode="HTML")
            await log_admin_action(message.from_user.id, "dmca_block", details=source_id)
        else:
            await message.answer("Трек уже заблокирован или ошибка.")

    # /admin unblock <source_id> — DMCA unblock
    elif subcmd == "unblock":
        if len(args) < 3:
            await message.answer("Использование: /admin unblock <source_id>")
            return
        source_id = args[2]
        from bot.services.dmca_filter import unblock_track
        removed = await unblock_track(source_id)
        if removed:
            await message.answer(f"✅ Трек <code>{source_id}</code> разблокирован.", parse_mode="HTML")
            await log_admin_action(message.from_user.id, "dmca_unblock", details=source_id)
        else:
            await message.answer("Трек не найден в списке заблокированных.")

    # /admin proxy — proxy pool status
    elif subcmd == "proxy":
        from bot.services.proxy_pool import proxy_pool
        await message.answer(proxy_pool.get_status(), parse_mode="HTML")

    # /admin promo create <code> <type> <uses> | /admin promo list
    elif subcmd == "promo":
        promo_args = text.split(maxsplit=3) if len(args) >= 3 else []
        if len(promo_args) >= 2 and promo_args[0] == "promo":
            promo_sub = promo_args[1] if len(promo_args) > 1 else ""
        else:
            promo_sub = args[2] if len(args) > 2 else ""
        if promo_sub == "create":
            # /admin promo create CODE type uses
            rest = text.split("create", 1)[-1].strip().split()
            if len(rest) < 3:
                await message.answer(
                    "Использование: /admin promo create &lt;код&gt; &lt;тип: premium_7d|premium_30d|flac_5&gt; &lt;кол-во&gt;",
                    parse_mode="HTML",
                )
                return
            code, promo_type, max_uses_s = rest[0], rest[1], rest[2]
            if promo_type not in ("premium_7d", "premium_30d", "flac_5"):
                await message.answer("Тип должен быть: premium_7d, premium_30d или flac_5")
                return
            try:
                max_uses = int(max_uses_s)
            except ValueError:
                await message.answer("Кол-во должно быть числом")
                return
            from bot.services.promo_service import create_promo
            promo = await create_promo(code, promo_type, max_uses, message.from_user.id)
            if promo:
                await message.answer(f"✅ Промокод <code>{code}</code> создан ({promo_type}, {max_uses} использований).", parse_mode="HTML")
                await log_admin_action(message.from_user.id, "promo_create", details=f"{code} {promo_type} {max_uses}")
            else:
                await message.answer("Промокод с таким кодом уже существует.")
        elif promo_sub == "list":
            from bot.services.promo_service import list_promos
            promos = await list_promos()
            if not promos:
                await message.answer("Промокодов нет.")
            else:
                lines = ["<b>Промокоды:</b>\n"]
                for p in promos:
                    lines.append(f"<code>{p['code']}</code> — {p['type']} | осталось: {p['uses_left']}/{p['max_uses']}")
                await message.answer("\n".join(lines), parse_mode="HTML")
        else:
            await message.answer("Использование: /admin promo create|list")

    # /admin flags — list all feature flags
    elif subcmd == "flags":
        from bot.services.feature_flags import get_all_flags
        flags = await get_all_flags()
        lines = ["<b>🚩 Feature Flags:</b>\n"]
        for name, enabled in flags.items():
            status_icon = "✅" if enabled else "❌"
            lines.append(f"  {status_icon} <code>{name}</code>")
        lines.append("\nПереключить: /admin flag &lt;name&gt; on|off")
        await message.answer("\n".join(lines), parse_mode="HTML")

    # /admin flag <name> on|off — toggle a feature flag
    elif subcmd == "flag":
        if len(args) < 4:
            await message.answer("Использование: /admin flag &lt;name&gt; on|off", parse_mode="HTML")
            return
        flag_name = args[2]
        flag_value = args[3] if len(args) > 3 else ""
        # Parse flag_name and value from args[2] which may be "name on/off"
        parts = message.text.split(maxsplit=3)
        if len(parts) >= 4:
            flag_name = parts[2]
            flag_value = parts[3].lower()
        if flag_value not in ("on", "off"):
            await message.answer("Значение: on или off")
            return
        from bot.services.feature_flags import set_flag, _DEFAULTS
        if flag_name not in _DEFAULTS:
            await message.answer(f"Неизвестный флаг: <code>{flag_name}</code>.\nДоступные: {', '.join(_DEFAULTS.keys())}", parse_mode="HTML")
            return
        await set_flag(flag_name, flag_value == "on")
        status = "✅ ВКЛ" if flag_value == "on" else "❌ ВЫКЛ"
        await message.answer(f"Флаг <code>{flag_name}</code> → {status}", parse_mode="HTML")
        await log_admin_action(message.from_user.id, "flag_toggle", details=f"{flag_name}={flag_value}")

    # /admin appeals — list pending DMCA appeals
    elif subcmd == "appeals":
        from bot.models.dmca_appeal import DmcaAppeal
        from bot.models.blocked_track import BlockedTrack
        async with async_session() as session:
            result = await session.execute(
                select(DmcaAppeal, BlockedTrack)
                .join(BlockedTrack, BlockedTrack.id == DmcaAppeal.blocked_track_id)
                .where(DmcaAppeal.status == "pending")
                .order_by(DmcaAppeal.created_at.desc())
                .limit(20)
            )
            appeals = result.all()
        if not appeals:
            await message.answer("Нет ожидающих апелляций.")
            return
        lines = ["<b>📋 DMCA Апелляции (pending):</b>\n"]
        for appeal, bt in appeals:
            lines.append(
                f"  #{appeal.id} | user:{appeal.user_id} | трек: <code>{bt.source_id}</code>\n"
                f"    Причина: {(appeal.reason or '-')[:80]}"
            )
        lines.append("\nРассмотреть: /admin appeal &lt;id&gt; approve|reject")
        await message.answer("\n".join(lines), parse_mode="HTML")

    # /admin appeal <id> approve|reject — review DMCA appeal
    elif subcmd == "appeal":
        if len(args) < 4:
            await message.answer("Использование: /admin appeal &lt;id&gt; approve|reject", parse_mode="HTML")
            return
        parts = message.text.split(maxsplit=3)
        try:
            appeal_id = int(parts[2])
        except (ValueError, IndexError):
            await message.answer("ID апелляции должен быть числом.")
            return
        decision = parts[3].lower() if len(parts) > 3 else ""
        if decision not in ("approve", "reject"):
            await message.answer("Решение: approve или reject")
            return
        from bot.services.dmca_filter import review_appeal
        success = await review_appeal(appeal_id, approved=(decision == "approve"), admin_id=message.from_user.id)
        if success:
            emoji = "✅" if decision == "approve" else "❌"
            await message.answer(f"{emoji} Апелляция #{appeal_id} — {decision}d.")
            await log_admin_action(message.from_user.id, f"appeal_{decision}", details=str(appeal_id))
        else:
            await message.answer("Апелляция не найдена или уже рассмотрена.")

    # /admin ab — A/B test dashboard for recommendation system
    elif subcmd == "ab":
        text = await _build_ab_dashboard()
        await message.answer(text, parse_mode="HTML")

    else:
        await message.answer(
            "<b>Команды админа:</b>\n"
            "/admin stats — статистика\n"
            "/admin ban &lt;id или @username&gt; — бан\n"
            "/admin unban &lt;id или @username&gt; — разбан\n"
            "/admin broadcast &lt;текст&gt; — рассылка\n"
            "/admin release — рассылка новой версии\n"
            "/admin premium &lt;id или @username&gt; — выдать premium\n"
            "/admin queue — очередь эфира\n"
            "/admin skip — пропустить трек\n"
            "/admin mode &lt;режим&gt; — режим эфира\n"
            "/admin tracks &lt;tequila|fullmoon&gt; — управление треками\n"
            "/admin load &lt;@channel&gt; &lt;tequila|fullmoon&gt; — загрузить из канала\n"
            "/admin audit — журнал действий\n"
            "/admin export — экспорт статистики CSV\n"
            "/admin block &lt;source_id&gt; [причина] — заблокировать трек (DMCA)\n"
            "/admin unblock &lt;source_id&gt; — разблокировать трек\n"
            "/admin proxy — статус прокси-пула\n"
            "/admin promo create &lt;код&gt; &lt;тип&gt; &lt;кол-во&gt; — создать промокод\n"
            "/admin promo list — список промокодов\n"
            "/admin flags — список feature-флагов\n"
            "/admin flag &lt;name&gt; on|off — переключить флаг\n"
            "/admin appeals — список DMCA апелляций\n"
            "/admin appeal &lt;id&gt; approve|reject — рассмотреть апелляцию\n"
            "/admin ab — A/B тест рекомендаций (CTR)",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "action:admin")
async def handle_admin_panel(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        try:
            await callback.answer()
        except TelegramBadRequest as e:
            if "query is too old" not in str(e).lower():
                raise
        return
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" not in str(e).lower():
            raise
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


@router.callback_query(lambda c: c.data == "adm:release")
async def handle_adm_release(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer("Запускаю рассылку версии...")
    from bot.main import _broadcast_version_update

    await _broadcast_version_update(bot)
    await log_admin_action(callback.from_user.id, "version_broadcast")
    try:
        await callback.message.edit_text(
            "✅ Рассылка новой версии завершена. Проверь логи sent/failed.",
            reply_markup=_back_to_panel_kb,
        )
    except Exception:
        await callback.message.answer(
            "✅ Рассылка новой версии завершена. Проверь логи sent/failed.",
            reply_markup=_back_to_panel_kb,
        )


@router.callback_query(lambda c: c.data == "adm:health")
async def handle_adm_health(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()
    from bot.services.provider_health import get_health_summary
    text = get_health_summary()
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "adm:broadcast")
async def handle_adm_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Enter broadcast FSM: ask admin to send a message (text/photo/GIF)."""
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()
    await state.set_state(BroadcastState.waiting_message)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:broadcast_cancel")]
    ])
    await callback.message.answer(
        "📨 <b>Рассылка</b>\n\n"
        "Отправь мне сообщение, которое хочешь разослать всем пользователям.\n\n"
        "Поддерживается:\n"
        "• Текст (с HTML-форматированием)\n"
        "• Фото с подписью\n"
        "• GIF/анимация с подписью\n"
        "• Видео с подписью\n\n"
        "Оформи сообщение красиво — оно будет отправлено <b>как есть</b>.",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )


@router.message(BroadcastState.waiting_message)
async def handle_broadcast_message(message: Message, state: FSMContext, bot: Bot) -> None:
    """Receive broadcast content from admin, show preview and confirm."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    # Store the message reference for later copy_message
    await state.update_data(
        broadcast_chat_id=message.chat.id,
        broadcast_message_id=message.message_id,
    )

    # Also store in Redis as backup (FSM might expire)
    import json as _json
    await cache.redis.setex(
        f"admin:broadcast_pending:{message.from_user.id}",
        300,  # 5 min TTL
        _json.dumps({"chat_id": message.chat.id, "message_id": message.message_id}),
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить рассылку", callback_data="adm:broadcast_confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="adm:broadcast_cancel"),
        ]
    ])

    # Count users
    async with async_session() as session:
        result = await session.execute(
            select(func.count(User.id)).where(User.is_banned == False)  # noqa: E712
        )
        user_count = result.scalar() or 0

    # Describe content type
    if message.animation:
        content_type = "GIF + текст"
    elif message.photo:
        content_type = "Фото + текст"
    elif message.video:
        content_type = "Видео + текст"
    else:
        content_type = "Текст"

    await message.reply(
        f"⚠️ <b>Подтверди рассылку</b>\n\n"
        f"Тип: <b>{content_type}</b>\n"
        f"Получателей: <b>{user_count}</b> пользователей\n\n"
        f"☝️ Сообщение выше будет отправлено всем. Подтвердить?",
        parse_mode="HTML",
        reply_markup=kb,
    )
    # Stay in state until confirm/cancel


@router.callback_query(lambda c: c.data == "adm:broadcast_confirm")
async def handle_broadcast_confirm(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()

    import json as _json
    pending_key = f"admin:broadcast_pending:{callback.from_user.id}"
    raw = await cache.redis.get(pending_key)
    if not raw:
        await callback.message.edit_text("⚠️ Рассылка истекла или уже отправлена.")
        await state.clear()
        return
    if isinstance(raw, bytes):
        raw = raw.decode()
    data = _json.loads(raw)

    await cache.redis.delete(pending_key)
    await state.clear()
    await callback.message.edit_text("⏳ Рассылка запущена...")

    # Legacy text-only broadcast
    if "text_only" in data:
        await _broadcast(bot, callback.message, data["text_only"])
        await log_admin_action(callback.from_user.id, "broadcast", details=data["text_only"][:200])
    else:
        # Copy message broadcast (supports photo/GIF/video/text)
        await _broadcast_copy(bot, callback.message, data["chat_id"], data["message_id"])
        await log_admin_action(callback.from_user.id, "broadcast", details=f"msg_id={data['message_id']}")


@router.callback_query(lambda c: c.data == "adm:broadcast_cancel")
async def handle_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()
    await cache.redis.delete(f"admin:broadcast_pending:{callback.from_user.id}")
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")


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
        blocked_total = await session.scalar(
            select(func.count()).select_from(User).where(User.bot_blocked == True)  # noqa: E712
        ) or 0
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
        # Status icon: ◇ premium, ○ free, 🚫 blocked bot
        blocked = getattr(u, "bot_blocked", False)
        if blocked:
            icon = "\U0001f6ab"  # 🚫
        elif u.is_premium:
            icon = "\u25c7"
        else:
            icon = "\u25cb"
        label = f"{icon} @{name}" if u.username else f"{icon} {name}"
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

    active = total - blocked_total
    text = (
        f"<b>\u25ce \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438</b> ({total})\n"
        f"Активных: <b>{active}</b> · Заблокировали: <b>{blocked_total}</b>\n\n"
        f"\u25c7 = Premium · \u25cb = Free · \U0001f6ab = Заблокировал бота\n"
        f"\u041d\u0430\u0436\u043c\u0438 \u25c7 \u0447\u0442\u043e\u0431\u044b \u0432\u044b\u0434\u0430\u0442\u044c, \u2717 \u0447\u0442\u043e\u0431\u044b \u0441\u043d\u044f\u0442\u044c."
    )
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
        user = await session.get(User, callback_data.uid)
        if user:
            user.is_premium = True
            badges = user.badges or []
            if "premium" not in badges:
                user.badges = badges + ["premium"]
        await session.commit()
    await log_admin_action(callback.from_user.id, "premium", callback_data.uid)
    await callback.answer("\u25c7 Premium \u0432\u044b\u0434\u0430\u043d", show_alert=False)
    text, kb = await _build_user_list_kb(callback_data.p)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        logger.debug("edit premium grant list failed", exc_info=True)


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
        logger.debug("edit premium revoke list failed", exc_info=True)


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
        logger.debug("edit settings text failed", exc_info=True)


@router.callback_query(lambda c: c.data and c.data.startswith("adm:"))
async def handle_adm_prompt(callback: CallbackQuery) -> None:
    """Handle admin buttons that need text input — show instructions."""
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    prompts = {
        "adm:broadcast": None,  # handled by dedicated FSM handler above
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
        logger.debug("edit tracks list page failed", exc_info=True)


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
        logger.debug("edit tracks list after delete failed", exc_info=True)


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
                logger.debug("delete forwarded message failed msg=%s", fwd.message_id, exc_info=True)

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
                logger.debug("edit channel load progress failed", exc_info=True)

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
    """Broadcast text to all users with Telegram-friendly rate limiting."""
    import asyncio
    async with async_session() as session:
        result = await session.execute(
            select(User.id).where(
                User.is_banned == False,  # noqa: E712
                User.bot_blocked == False,  # noqa: E712
            )
        )
        user_ids = [row[0] for row in result.all()]

    sent, failed = 0, 0
    blocked_ids: list[int] = []
    for uid in user_ids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            failed += 1
            err_str = str(e).lower()
            if "blocked" in err_str or "deactivated" in err_str or "not found" in err_str:
                blocked_ids.append(uid)
        await asyncio.sleep(0.05)

    # Mark blocked users so we skip them next time
    if blocked_ids:
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id.in_(blocked_ids)).values(bot_blocked=True)
            )
            await session.commit()

    await admin_msg.answer(
        f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}"
        + (f"\n🚫 Заблокировали бота: {len(blocked_ids)}" if blocked_ids else "")
    )


async def _broadcast_copy(bot: Bot, admin_msg: Message, from_chat_id: int, message_id: int) -> None:
    """Broadcast by copying a message (supports text, photo, GIF, video) to all users."""
    import asyncio
    async with async_session() as session:
        result = await session.execute(
            select(User.id).where(
                User.is_banned == False,  # noqa: E712
                User.bot_blocked == False,  # noqa: E712
            )
        )
        user_ids = [row[0] for row in result.all()]

    sent, failed = 0, 0
    blocked_ids: list[int] = []
    for uid in user_ids:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            sent += 1
        except Exception as e:
            failed += 1
            err_str = str(e).lower()
            if "blocked" in err_str or "deactivated" in err_str or "not found" in err_str:
                blocked_ids.append(uid)
        await asyncio.sleep(0.05)

    # Mark blocked users so we skip them next time
    if blocked_ids:
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id.in_(blocked_ids)).values(bot_blocked=True)
            )
            await session.commit()

    await admin_msg.answer(
        f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}"
        + (f"\n🚫 Заблокировали бота: {len(blocked_ids)}" if blocked_ids else "")
    )
