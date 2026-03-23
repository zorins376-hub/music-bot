import base64
import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import select, update
from sqlalchemy.sql import func

from bot.db import get_or_create_user, is_admin
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track
from bot.models.user import User
from bot.version import VERSION, get_new_features, get_changelog_text, CHANGELOG

logger = logging.getLogger(__name__)

router = Router()


def _main_menu(lang: str, admin: bool = False) -> InlineKeyboardMarkup:
    from bot.config import settings
    rows = []
    # TMA Player WebApp button — top priority
    if settings.TMA_URL:
        rows.append([
            InlineKeyboardButton(text="🎵 Открыть плеер", web_app=WebAppInfo(url=settings.TMA_URL)),
        ])
    rows += [
        [
            InlineKeyboardButton(text="◈ Найти трек", callback_data="action:search"),
            InlineKeyboardButton(text="✦ Моя Волна", callback_data="action:recommend"),
        ],
        [
            InlineKeyboardButton(text="🏆 Чарты", callback_data="action:charts"),
            InlineKeyboardButton(text="🆕 Новые релизы", callback_data="action:radar"),
        ],
        [
            InlineKeyboardButton(text="▸ Плейлисты", callback_data="action:playlist"),
            InlineKeyboardButton(text="❤️ Любимое", callback_data="action:favorites"),
        ],
        [
            InlineKeyboardButton(text="◉ Профиль", callback_data="action:profile"),
            InlineKeyboardButton(text="◇ Premium", callback_data="action:premium"),
        ],
        [
            InlineKeyboardButton(text="📻 Радио", callback_data="action:radio_menu"),
            InlineKeyboardButton(text="🤖 AI Плейлист", callback_data="action:ai_playlist"),
        ],
        [
            InlineKeyboardButton(text="⋯ Ещё", callback_data="action:more"),
        ],
    ]
    if admin:
        rows.append([
            InlineKeyboardButton(text="◆ Админ-панель", callback_data="action:admin"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _more_menu(lang: str) -> InlineKeyboardMarkup:
    """Submenu with additional features."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✦ Daily Mix", callback_data="action:mix"),
            InlineKeyboardButton(text="◆ Топ сегодня", callback_data="action:top"),
        ],
        [
            InlineKeyboardButton(text="🎦 Видео", callback_data="action:video"),
            InlineKeyboardButton(text="🎤 Мой вкус", callback_data="action:taste"),
        ],
        [
            InlineKeyboardButton(text="🏅 Бейджи", callback_data="action:badges"),
            InlineKeyboardButton(text="🏆 Топ игроков", callback_data="action:leaderboard"),
        ],
        [
            InlineKeyboardButton(text="📥 Импорт", callback_data="action:import_playlist"),
            InlineKeyboardButton(text="👨‍👩‍👧‍👦 Семья", callback_data="action:family"),
        ],
        [
            InlineKeyboardButton(text="⚙ Настройки", callback_data="action:settings"),
            InlineKeyboardButton(text="❓ FAQ", callback_data="action:faq"),
        ],
        [
            InlineKeyboardButton(text="◁ Назад", callback_data="action:menu"),
        ],
    ])


def _radio_menu(lang: str) -> InlineKeyboardMarkup:
    """Radio submenu with live streams and auto mix."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="▸ TEQUILA LIVE", callback_data="radio:tequila"),
            InlineKeyboardButton(text="◑ FULLMOON LIVE", callback_data="radio:fullmoon"),
        ],
        [
            InlineKeyboardButton(text="✦ AUTO MIX", callback_data="radio:automix"),
            InlineKeyboardButton(text="🎙 AI DJ", callback_data="action:dj"),
        ],
        [
            InlineKeyboardButton(text="◁ Назад", callback_data="action:menu"),
        ],
    ])


_LANG_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton(text="🇰🇬 Кыргызча", callback_data="lang:kg"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        ]
    ]
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    admin = is_admin(message.from_user.id, message.from_user.username)

    # D-02: Handle deep-link from inline mode: /start s_<base64(query)>
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        payload = args[1]
        if payload.startswith("s_"):
            b64 = payload[2:]
            # Add back padding
            b64 += "=" * (-len(b64) % 4)
            try:
                query = base64.urlsafe_b64decode(b64).decode()
            except Exception:
                logger.debug("Invalid deep-link payload: %s", payload)
            else:
                from bot.handlers.search import _do_search
                await _do_search(message, query)
                return
        # C-04: Handle shared playlist deep-link: /start pl_<share_id>
        elif payload.startswith("pl_"):
            share_id = payload[3:]
            from bot.handlers.playlist import show_shared_playlist
            await show_shared_playlist(message, share_id)
            return
        # Share track deep-link: /start tr_<share_id>
        elif payload.startswith("tr_"):
            share_id = payload[3:]
            from bot.handlers.search import show_shared_track
            await show_shared_track(message, share_id)
            return
        # Share mix deep-link: /start mx_<share_id>
        elif payload.startswith("mx_"):
            share_id = payload[3:]
            from bot.handlers.mix import show_shared_mix
            await show_shared_mix(message, share_id)
            return
        # E-01: Handle referral deep-link: /start ref_<user_id>
        elif payload.startswith("ref_"):
            from bot.handlers.referral import process_referral
            await process_referral(message, payload[4:])
        # Family plan deep-link: /start fam_<invite_code>
        elif payload.startswith("fam_"):
            from bot.handlers.family import handle_family_deeplink
            if await handle_family_deeplink(message, payload):
                return

    # Check for new features to show
    new_features = get_new_features(user.language, user.last_seen_version)
    if new_features:
        await message.answer(new_features, parse_mode="HTML")
        # Update last_seen_version
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(last_seen_version=VERSION)
            )
            await session.commit()
    elif not user.last_seen_version:
        # First time user — silently update version
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(last_seen_version=VERSION)
            )
            await session.commit()

    await message.answer(
        t(user.language, "start_message", name=message.from_user.first_name or ""),
        reply_markup=_main_menu(user.language, admin=admin),
        parse_mode="HTML",
    )

    # Smart Onboarding v2: nudge new un-onboarded users
    if not user.onboarded:
        await message.answer(
            t(user.language, "onboard_nudge"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎵 " + t(user.language, "onboard_nudge_btn"), callback_data="action:recommend")]
            ]),
            parse_mode="HTML",
        )


@router.message(Command("version"))
async def cmd_version(message: Message) -> None:
    """Show current bot version."""
    user = await get_or_create_user(message.from_user)
    await message.answer(
        t(user.language, "bot_version", version=VERSION),
        parse_mode="HTML",
    )


@router.message(Command("changelog"))
async def cmd_changelog(message: Message) -> None:
    """Show full changelog."""
    user = await get_or_create_user(message.from_user)
    parts = [f"<b>{t(user.language, 'changelog_title')}</b>\n"]

    # Sort versions newest first
    from packaging.version import Version
    versions = sorted(CHANGELOG.keys(), key=lambda v: Version(v), reverse=True)

    for ver in versions[:5]:  # Last 5 versions
        parts.append(get_changelog_text(user.language, ver))
        parts.append("")

    await message.answer("\n".join(parts).strip(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await message.answer(t(user.language, "help_message"), parse_mode="HTML")


@router.message(Command("lang"))
async def cmd_lang(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await message.answer(
        t(user.language, "choose_language"),
        reply_markup=_LANG_KEYBOARD,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("lang:"))
async def handle_lang_select(callback: CallbackQuery) -> None:
    lang = callback.data.split(":")[1]
    if lang not in ("ru", "en", "kg"):
        await callback.answer()
        return

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == callback.from_user.id).values(language=lang)
        )
        await session.commit()

    await callback.answer()
    await callback.message.edit_text(t(lang, "lang_changed"))


@router.callback_query(lambda c: c.data == "action:search")
async def handle_search_button(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await callback.message.answer(t(user.language, "search_prompt"))


@router.callback_query(lambda c: c.data == "action:charts")
async def handle_charts_button(callback: CallbackQuery) -> None:
    from bot.handlers.charts import cmd_charts
    await callback.answer()
    await cmd_charts(callback.message)


@router.callback_query(lambda c: c.data == "action:faq")
async def handle_faq_button(callback: CallbackQuery) -> None:
    from bot.handlers.faq import send_faq
    user = await get_or_create_user(callback.from_user)
    await callback.answer()
    await send_faq(callback.message, user.language)


@router.callback_query(lambda c: c.data == "action:favorites")
async def handle_favorites_button(callback: CallbackQuery) -> None:
    from bot.handlers.favorites import send_favorites

    user = await get_or_create_user(callback.from_user)
    await callback.answer()
    await send_favorites(callback.message, user.id, user.language)


@router.callback_query(lambda c: c.data == "action:menu")
async def handle_menu_button(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    admin = is_admin(callback.from_user.id, callback.from_user.username)
    await callback.answer()
    try:
        await callback.message.edit_text(
            t(user.language, "start_message", name=callback.from_user.first_name or ""),
            reply_markup=_main_menu(user.language, admin=admin),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            t(user.language, "start_message", name=callback.from_user.first_name or ""),
            reply_markup=_main_menu(user.language, admin=admin),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "action:more")
async def handle_more_button(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=_more_menu(user.language))
    except Exception:
        await callback.message.answer(
            "⋯",
            reply_markup=_more_menu(user.language),
        )


@router.callback_query(lambda c: c.data == "action:radio_menu")
async def handle_radio_menu_button(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=_radio_menu(user.language))
    except Exception:
        await callback.message.answer(
            "📻",
            reply_markup=_radio_menu(user.language),
        )


@router.callback_query(lambda c: c.data == "action:settings")
async def handle_settings_button(callback: CallbackQuery) -> None:
    from bot.handlers.settings import cmd_settings_v2
    await callback.answer()
    await cmd_settings_v2(callback.message)


@router.callback_query(lambda c: c.data == "action:top")
async def handle_top_button(callback: CallbackQuery) -> None:
    from bot.handlers.history import _show_top
    await callback.answer()
    await _show_top(callback.message, callback.from_user)


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    await _show_profile(message, message.from_user)


@router.callback_query(lambda c: c.data == "action:profile")
async def handle_profile_button(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_profile(callback.message, callback.from_user)


async def _show_profile(message: Message, tg_user) -> None:
    user = await get_or_create_user(tg_user)
    lang = user.language

    # Count user's played tracks
    async with async_session() as session:
        play_count = await session.scalar(
            select(func.count(ListeningHistory.id))
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
            )
        ) or 0

    admin = is_admin(tg_user.id, tg_user.username)

    lines = [t(lang, "profile_header")]
    lines.append(t(lang, "profile_name", name=tg_user.first_name or tg_user.username or str(tg_user.id)))

    if admin:
        lines.append(t(lang, "profile_status_admin"))
    elif user.is_premium and user.premium_until:
        lines.append(t(lang, "profile_status_premium", until=user.premium_until.strftime("%d.%m.%Y")))
    elif user.is_premium:
        lines.append(t(lang, "profile_status_premium", until="∞"))
    else:
        lines.append(t(lang, "profile_status_free"))

    lines.append(t(lang, "profile_quality", quality=user.quality))
    lines.append(t(lang, "profile_tracks", count=play_count))
    lines.append(t(lang, "profile_joined", date=user.created_at.strftime("%d.%m.%Y")))

    if user.fav_genres:
        lines.append(t(lang, "profile_genres", genres=", ".join(user.fav_genres)))
    if user.fav_vibe:
        lines.append(t(lang, "profile_vibe", vibe=user.fav_vibe))
    if user.fav_artists:
        lines.append(t(lang, "profile_artists", artists=", ".join(user.fav_artists)))

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── Family Plan ──────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "action:family")
async def handle_family_button(callback: CallbackQuery) -> None:
    await callback.answer()
    from bot.handlers.family import cmd_family
    await cmd_family(callback.message)


# ── Taste Profile ────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "action:taste")
async def handle_taste_button(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_taste_profile(callback.message, callback.from_user)


@router.message(Command("taste"))
async def cmd_taste(message: Message) -> None:
    await _show_taste_profile(message, message.from_user)


async def _show_taste_profile(message: Message, tg_user) -> None:
    """Display a detailed taste profile for the user."""
    from bot.db import get_user_stats
    from collections import Counter
    from datetime import datetime, timedelta, timezone

    user = await get_or_create_user(tg_user)
    lang = user.language

    # Gather deep stats from listening history
    async with async_session() as session:
        now = datetime.now(timezone.utc)
        month_ago = now - timedelta(days=30)

        # Top 5 artists (all time)
        top_artists_r = await session.execute(
            select(Track.artist, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
                Track.artist.isnot(None),
                Track.artist != "",
            )
            .group_by(Track.artist)
            .order_by(func.count().desc())
            .limit(5)
        )
        top_artists = [(row[0], row[1]) for row in top_artists_r.all()]

        # Top 5 genres
        top_genres_r = await session.execute(
            select(Track.genre, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
                Track.genre.isnot(None),
                Track.genre != "",
            )
            .group_by(Track.genre)
            .order_by(func.count().desc())
            .limit(5)
        )
        top_genres = [(row[0], row[1]) for row in top_genres_r.all()]

        # Average BPM
        avg_bpm_r = await session.scalar(
            select(func.avg(Track.bpm))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
                Track.bpm.isnot(None),
            )
        )
        avg_bpm = int(avg_bpm_r) if avg_bpm_r else None

        # Total plays & month plays
        total_plays = await session.scalar(
            select(func.count(ListeningHistory.id))
            .where(ListeningHistory.user_id == user.id, ListeningHistory.action == "play")
        ) or 0

        month_plays = await session.scalar(
            select(func.count(ListeningHistory.id))
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= month_ago,
            )
        ) or 0

        # Sources distribution
        sources_r = await session.execute(
            select(ListeningHistory.source, func.count().label("cnt"))
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
                ListeningHistory.source.isnot(None),
            )
            .group_by(ListeningHistory.source)
            .order_by(func.count().desc())
            .limit(5)
        )
        sources = [(row[0], row[1]) for row in sources_r.all()]

    lines = [t(lang, "taste_header")]
    lines.append(t(lang, "taste_total", total=total_plays, month=month_plays))

    if top_artists:
        lines.append("")
        lines.append(t(lang, "taste_top_artists"))
        for i, (artist, cnt) in enumerate(top_artists, 1):
            lines.append(f"  {i}. {artist} ({cnt})")

    if top_genres:
        lines.append("")
        lines.append(t(lang, "taste_top_genres"))
        for i, (genre, cnt) in enumerate(top_genres, 1):
            lines.append(f"  {i}. {genre} ({cnt})")

    if avg_bpm:
        lines.append("")
        lines.append(t(lang, "taste_avg_bpm", bpm=avg_bpm))

    if user.fav_vibe:
        lines.append(t(lang, "taste_vibe", vibe=user.fav_vibe))

    if sources:
        lines.append("")
        lines.append(t(lang, "taste_sources"))
        for src, cnt in sources:
            lines.append(f"  ▸ {src}: {cnt}")

    if total_plays == 0:
        lines.append("")
        lines.append(t(lang, "taste_no_data"))

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── Radar from main menu ────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "action:radar")
async def handle_radar_button(callback: CallbackQuery) -> None:
    from bot.handlers.release_radar import cmd_radar
    await callback.answer()
    await cmd_radar(callback.message)
