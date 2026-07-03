import asyncio
import base64
import html
import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo
from sqlalchemy import select, update
from sqlalchemy.sql import func

from bot.config import settings
from bot.db import get_or_create_user, is_admin
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import ListeningHistory, Track
from bot.models.user import User
from bot.version import VERSION, get_new_features, get_changelog_text, CHANGELOG

logger = logging.getLogger(__name__)

router = Router()


_RANKS = [
    (0, "Слушатель"),
    (10, "Ночной странник"),
    (50, "Тёмная душа"),
    (150, "Тёмный premium"),
    (500, "Элита Black Room"),
]

_VIBE_NAMES = {
    "vibe_fire": "огонь",
    "vibe_sad": "грустный вайб",
    "vibe_night": "ночной вайб",
    "vibe_drive": "дорога",
    "vibe_love": "black love",
}


def _rank_for(play_count: int, *, premium: bool = False, admin: bool = False) -> tuple[str, int, int]:
    if admin:
        return "Основатель", play_count, max(play_count, 1)
    if premium and play_count >= 50:
        return "Тёмный premium", 50, 150
    current = _RANKS[0]
    next_threshold = _RANKS[-1][0]
    for idx, rank in enumerate(_RANKS):
        if play_count >= rank[0]:
            current = rank
            if idx + 1 < len(_RANKS):
                next_threshold = _RANKS[idx + 1][0]
            else:
                next_threshold = rank[0]
    return current[1], current[0], next_threshold


def _progress_bar(value: int, start: int, end: int, width: int = 10) -> str:
    if end <= start:
        return "■" * width
    ratio = max(0.0, min(1.0, (value - start) / (end - start)))
    filled = int(round(ratio * width))
    return "■" * filled + "□" * (width - filled)


def _is_night_mode() -> bool:
    local_hour = (datetime.now(timezone.utc) + timedelta(hours=6)).hour
    return local_hour >= 22 or local_hour < 6


# Persistent bottom "reply" keyboard — always-visible quick access (private only).
# BLACK ROOM identity: leads with the fullscreen player (our differentiator) as a
# web_app button, then core actions. Distinct from generic "Новинки/Топ/Подборки"
# competitor keyboards. Button labels are matched exactly by the handlers below.
_RK_PLAYER = {"ru": "◇ Плеер", "en": "◇ Player", "kg": "◇ Плеер"}
_RK_CHARTS = {"ru": "🔥 Чарты", "en": "🔥 Charts", "kg": "🔥 Чарттар"}
_RK_MIX = {"ru": "✨ Микс", "en": "✨ Mix", "kg": "✨ Микс"}
_RK_FAV = {"ru": "♡ Моё", "en": "♡ Mine", "kg": "♡ Меники"}
_RK_MENU = {"ru": "☰ Меню", "en": "☰ Menu", "kg": "☰ Меню"}
_RK_MENU_TITLE = {"ru": "◇ Меню", "en": "◇ Menu", "kg": "◇ Меню"}

# Branded header row shown at the top of the inline menu (decorative title).
_BRAND_TITLE = "𝐓 𝐄 𝐐 𝐔 𝐈 𝐋 𝐀   𝐌 𝐔 𝐒 𝐈 𝐂"

# Text shown above the inline menu buttons — nudges users that search is just a message.
_MENU_INTRO = {
    "ru": ("🎧 <b>Для поиска просто отправь сообщение</b>\n"
           "Название трека, артиста или строчку из песни — я найду."),
    "en": ("🎧 <b>To search, just send a message</b>\n"
           "A track title, artist, or a line of lyrics — I'll find it."),
    "kg": ("🎧 <b>Издөө үчүн жөн гана билдирүү жибер</b>\n"
           "Тректин аты, аткаруучу же ырдын сабы — табам."),
}

# Short one-line header that carries the persistent ◇ Плеер keyboard on /start.
# Replaces the old multi-line welcome blurb (BLACK ROOM / sources / etc.) which
# the user asked to drop from the start screen.
_START_HELLO = "🎧 <b>BLACK ROOM</b>"


def _rk(d: dict, lang: str) -> str:
    return d.get(lang, d["ru"])


def _reply_keyboard(lang: str) -> ReplyKeyboardMarkup:
    # Under the input box: a single ◇ Плеер launcher for the Mini App. Falls back
    # to Charts/Mix when no Mini App is configured.
    if settings.TMA_URL:
        rows = [[KeyboardButton(text=_rk(_RK_PLAYER, lang), web_app=WebAppInfo(url=settings.TMA_URL))]]
    else:
        rows = [[KeyboardButton(text=_rk(_RK_CHARTS, lang)), KeyboardButton(text=_rk(_RK_MIX, lang))]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def _main_menu(lang: str, admin: bool = False, bot_username: str = "") -> InlineKeyboardMarkup:
    # Minimal branded card: TEQUILA MUSIC header, then Charts | Premium, then More.
    # Wave/Radio/Library live under "More" so the top stays clean.
    rows = [
        [InlineKeyboardButton(text=_BRAND_TITLE, callback_data="hub:radio")],
        [
            InlineKeyboardButton(text=t(lang, "menu_charts"), callback_data="action:charts"),
            InlineKeyboardButton(text=t(lang, "menu_premium"), callback_data="action:premium"),
        ],
        [InlineKeyboardButton(text=t(lang, "menu_more"), callback_data="menu:more")],
    ]
    if admin:
        rows.append([InlineKeyboardButton(text=t(lang, "menu_admin"), callback_data="action:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _more_menu(lang: str) -> InlineKeyboardMarkup:
    """Expanded 'More' sub-menu."""
    rows = [
        [
            InlineKeyboardButton(text=t(lang, "menu_wave"), callback_data="hub:wave"),
            InlineKeyboardButton(text=t(lang, "menu_library"), callback_data="hub:library"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "btn_video"), callback_data="action:video"),
            InlineKeyboardButton(text=t(lang, "btn_import"), callback_data="action:import_playlist"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "btn_family"), callback_data="action:family"),
            InlineKeyboardButton(text=t(lang, "btn_referral"), callback_data="action:referral"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "btn_settings"), callback_data="action:settings"),
            InlineKeyboardButton(text=t(lang, "btn_faq"), callback_data="action:faq"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "menu_back"), callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


_LANG_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton(text="🇰🇬 Кыргызча", callback_data="lang:kg"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        ]
    ]
)


async def process_start_payload(message: Message, payload: str) -> bool:
    """Dispatch a /start deep-link payload (s_/pl_/tr_/mx_/ref_/fam_).

    Returns True when the payload was fully handled and the caller should stop
    (i.e. not fall through to the main menu). ref_ returns False so onboarding
    continues. Reused by cmd_start and by the captcha middleware after a new
    user solves the challenge (so referrals/shared links survive the captcha).
    """
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
            return True
    # C-04: Handle shared playlist deep-link: /start pl_<share_id>
    elif payload.startswith("pl_"):
        share_id = payload[3:]
        from bot.handlers.playlist import show_shared_playlist
        await show_shared_playlist(message, share_id)
        return True
    # Share track deep-link: /start tr_<share_id>
    elif payload.startswith("tr_"):
        share_id = payload[3:]
        from bot.handlers.search import show_shared_track
        await show_shared_track(message, share_id)
        return True
    # Share mix deep-link: /start mx_<share_id>
    elif payload.startswith("mx_"):
        share_id = payload[3:]
        from bot.handlers.mix import show_shared_mix
        await show_shared_mix(message, share_id)
        return True
    # E-01: Handle referral deep-link: /start ref_<user_id>
    elif payload.startswith("ref_"):
        from bot.handlers.referral import process_referral
        await process_referral(message, payload[4:])
    # Family plan deep-link: /start fam_<invite_code>
    elif payload.startswith("fam_"):
        from bot.handlers.family import handle_family_deeplink
        if await handle_family_deeplink(message, payload):
            return True
    return False


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    admin = is_admin(message.from_user.id, message.from_user.username)

    # User came back — mark as not blocked
    if user.blocked_bot:
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(blocked_bot=False)
            )
            await session.commit()

    # D-02: Handle deep-link from inline mode: /start s_<base64(query)>
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        payload = args[1]
        if await process_start_payload(message, payload):
            return

    # Keep last_seen_version current without spamming a changelog on /start.
    if user.last_seen_version != VERSION:
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(last_seen_version=VERSION)
            )
            await session.commit()

    bot_me = await message.bot.me()
    # Welcome + persistent bottom keyboard (quick access always visible). The rich
    # inline menu is one tap away via the "☰ Меню" button.
    await message.answer(
        _START_HELLO,
        reply_markup=_reply_keyboard(user.language),
        parse_mode="HTML",
    )
    await message.answer(
        _rk(_MENU_INTRO, user.language),
        reply_markup=_main_menu(user.language, admin=admin, bot_username=bot_me.username or ""),
        parse_mode="HTML",
    )

    # Free Premium trial welcome (flag set in get_or_create_user on first creation)
    try:
        from bot.services.cache import cache
        trial_days = await cache.redis.get(f"premium:trial_granted:{user.id}")
        if trial_days:
            await cache.redis.delete(f"premium:trial_granted:{user.id}")
            days = trial_days if isinstance(trial_days, str) else trial_days.decode()
            await message.answer(
                t(user.language, "premium_trial_welcome", days=days),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=t(user.language, "menu_premium"), callback_data="action:premium"),
                ]]),
                parse_mode="HTML",
            )
    except Exception:
        logger.debug("trial welcome failed for %s", user.id, exc_info=True)


# ── Persistent bottom-keyboard button routes (private chat) ────────────────
# Registered in start.router (included before search.router), so the button
# texts route to the right feature instead of being treated as a search query.

@router.message(F.chat.type == "private", F.text.in_(set(_RK_CHARTS.values())))
async def rk_charts(message: Message) -> None:
    from bot.handlers.charts import cmd_charts
    await cmd_charts(message)


@router.message(F.chat.type == "private", F.text.in_(set(_RK_MIX.values())))
async def rk_mix(message: Message) -> None:
    from bot.handlers.mix import cmd_mix
    await cmd_mix(message)


@router.message(F.chat.type == "private", F.text.in_(set(_RK_FAV.values())))
async def rk_fav(message: Message) -> None:
    from bot.handlers.favorites import cmd_favorites
    await cmd_favorites(message)


@router.message(F.chat.type == "private", F.text.in_(set(_RK_MENU.values())))
async def rk_menu(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    admin = is_admin(message.from_user.id, message.from_user.username)
    bot_me = await message.bot.me()
    await message.answer(
        _rk(_MENU_INTRO, user.language),
        reply_markup=_main_menu(user.language, admin=admin, bot_username=bot_me.username or ""),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "captcha:ok")
async def cb_captcha_ok(callback: CallbackQuery) -> None:
    """One-tap captcha pass → straight into the main menu.

    Replaces the math challenge (see bot/middlewares/captcha.py). Also replays
    a pending /start deep-link payload via a native t.me deep-link button —
    safe re-dispatch with the correct from_user.
    """
    uid = callback.from_user.id
    try:
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == uid).values(captcha_passed=True, welcome_sent=True)
            )
            await session.commit()
    except Exception:
        logger.debug("captcha btn pass DB update failed user=%s", uid, exc_info=True)

    from bot.services.cache import cache
    pending = None
    try:
        pending = await cache.redis.get(f"captcha:pending_start:{uid}")
        for k in (f"captcha:q:{uid}", f"captcha:fails:{uid}", f"captcha:pending_start:{uid}"):
            await cache.redis.delete(k)
    except Exception:
        pass

    await callback.answer("✓")
    try:
        await callback.message.delete()
    except Exception:
        pass

    user = await get_or_create_user(callback.from_user)
    admin = is_admin(uid, callback.from_user.username)
    bot_me = await callback.bot.me()
    chat_id = callback.message.chat.id if callback.message else uid
    await callback.bot.send_message(
        chat_id,
        _START_HELLO,
        reply_markup=_reply_keyboard(user.language),
        parse_mode="HTML",
    )
    await callback.bot.send_message(
        chat_id,
        _rk(_MENU_INTRO, user.language),
        reply_markup=_main_menu(user.language, admin=admin, bot_username=bot_me.username or ""),
        parse_mode="HTML",
    )
    # Free Premium trial welcome — same flag as cmd_start, no longer lost when
    # the user doesn't retype /start within the flag's 1h TTL.
    try:
        trial_days = await cache.redis.get(f"premium:trial_granted:{uid}")
        if trial_days:
            await cache.redis.delete(f"premium:trial_granted:{uid}")
            days = trial_days if isinstance(trial_days, str) else trial_days.decode()
            await callback.bot.send_message(
                chat_id,
                t(user.language, "premium_trial_welcome", days=days),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=t(user.language, "menu_premium"), callback_data="action:premium"),
                ]]),
                parse_mode="HTML",
            )
    except Exception:
        logger.debug("trial welcome after captcha failed", exc_info=True)
    # Deep-link payload (shared track/playlist/referral) → one-tap continue.
    if pending:
        payload = pending if isinstance(pending, str) else pending.decode()
        try:
            await callback.bot.send_message(
                chat_id,
                t(user.language, "captcha_continue"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="▸",
                        url=f"https://t.me/{bot_me.username}?start={payload}",
                    ),
                ]]),
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("captcha continue link failed user=%s", uid, exc_info=True)


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
        t(user.language, "choose_lang"), reply_markup=_LANG_KEYBOARD
    )


@router.callback_query(lambda c: c.data and c.data.startswith("lang:"))
async def handle_lang_change(callback: CallbackQuery) -> None:
    lang = callback.data.split(":")[1]
    if lang not in ("ru", "kg", "en"):
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
    bot_me = await callback.bot.me()
    _username = bot_me.username or ""
    try:
        await callback.message.edit_text(
            _rk(_MENU_INTRO, user.language),
            reply_markup=_main_menu(user.language, admin=admin, bot_username=_username),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            _rk(_MENU_INTRO, user.language),
            reply_markup=_main_menu(user.language, admin=admin, bot_username=_username),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "menu:more")
async def handle_more_menu(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    await callback.answer()
    try:
        await callback.message.edit_text(
            t(user.language, "more_title"),
            reply_markup=_more_menu(user.language),
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("menu:more edit failed for %s", callback.from_user.id, exc_info=True)


@router.callback_query(lambda c: c.data == "menu:main")
async def handle_back_to_main(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    admin = is_admin(callback.from_user.id, callback.from_user.username)
    await callback.answer()
    bot_me = await callback.bot.me()
    _username = bot_me.username or ""
    try:
        await callback.message.edit_text(
            _rk(_MENU_INTRO, user.language),
            reply_markup=_main_menu(user.language, admin=admin, bot_username=_username),
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("menu:main edit failed for %s", callback.from_user.id, exc_info=True)


@router.callback_query(lambda c: c.data == "noop")
async def handle_noop(callback: CallbackQuery) -> None:
    # Decorative brand-title button — just acknowledge with a tiny toast.
    await callback.answer("🎧 TEQUILA MUSIC")


def _hub_menu(lang: str, rows: list) -> InlineKeyboardMarkup:
    rows = list(rows)
    rows.append([InlineKeyboardButton(text=t(lang, "menu_back"), callback_data="action:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_hub(callback: CallbackQuery, title_key: str, rows: list) -> None:
    user = await get_or_create_user(callback.from_user)
    await callback.answer()
    try:
        await callback.message.edit_text(
            t(user.language, title_key),
            reply_markup=_hub_menu(user.language, rows),
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("%s edit failed for %s", title_key, callback.from_user.id, exc_info=True)


@router.callback_query(F.data == "hub:wave")
async def handle_hub_wave(callback: CallbackQuery) -> None:
    lang = (await get_or_create_user(callback.from_user)).language
    rows = [
        [
            InlineKeyboardButton(text=t(lang, "btn_mix"), callback_data="action:mix"),
            InlineKeyboardButton(text=t(lang, "btn_dj"), callback_data="action:dj"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "btn_radar"), callback_data="action:radar"),
            InlineKeyboardButton(text=t(lang, "btn_ai_playlist"), callback_data="action:ai_playlist"),
        ],
    ]
    await _show_hub(callback, "hub_wave_title", rows)


@router.callback_query(F.data == "hub:radio")
async def handle_hub_radio(callback: CallbackQuery) -> None:
    lang = (await get_or_create_user(callback.from_user)).language
    rows = [
        [
            InlineKeyboardButton(text=t(lang, "btn_tequila"), callback_data="radio:tequila"),
            InlineKeyboardButton(text=t(lang, "btn_fullmoon"), callback_data="radio:fullmoon"),
        ],
    ]
    await _show_hub(callback, "hub_radio_title", rows)


@router.callback_query(F.data == "hub:library")
async def handle_hub_library(callback: CallbackQuery) -> None:
    lang = (await get_or_create_user(callback.from_user)).language
    rows = [
        [
            InlineKeyboardButton(text=t(lang, "btn_profile"), callback_data="action:profile"),
            InlineKeyboardButton(text=t(lang, "btn_favorites"), callback_data="action:favorites"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "btn_playlists"), callback_data="action:playlist"),
            InlineKeyboardButton(text=t(lang, "btn_taste"), callback_data="action:taste"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "btn_badges"), callback_data="action:badges"),
            InlineKeyboardButton(text=t(lang, "btn_wrapped"), callback_data="action:wrapped"),
        ],
    ]
    await _show_hub(callback, "hub_library_title", rows)


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
        top_vibe_row = (
            await session.execute(
                select(ListeningHistory.action, func.count().label("cnt"))
                .where(
                    ListeningHistory.user_id == user.id,
                    ListeningHistory.action.like("vibe_%"),
                )
                .group_by(ListeningHistory.action)
                .order_by(func.count().desc())
                .limit(1)
            )
        ).first()

    admin = is_admin(tg_user.id, tg_user.username)
    rank_name, rank_start, rank_next = _rank_for(
        play_count,
        premium=bool(user.is_premium),
        admin=admin,
    )
    progress = _progress_bar(play_count, rank_start, rank_next)
    next_left = max(0, rank_next - play_count)
    fav_vibe = user.fav_vibe
    if top_vibe_row:
        fav_vibe = _VIBE_NAMES.get(top_vibe_row[0], fav_vibe or "black")

    lines = [t(lang, "profile_header")]
    lines.append(t(lang, "profile_name", name=html.escape(tg_user.first_name or tg_user.username or str(tg_user.id))))
    lines.append(f"▸ Ранг: <b>{rank_name}</b>")
    lines.append(f"▸ Прогресс: <code>{progress}</code>" + (f" до следующего: <b>{next_left}</b>" if next_left else " максимум"))

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
    lines.append(f"▸ XP: <b>{user.xp or 0}</b> · Level <b>{user.level or 1}</b>")
    lines.append(f"▸ Streak: <b>{user.streak_days or 0}</b> дн.")
    lines.append(t(lang, "profile_joined", date=user.created_at.strftime("%d.%m.%Y")))

    if user.fav_genres:
        lines.append(t(lang, "profile_genres", genres=", ".join(user.fav_genres)))
    if fav_vibe:
        lines.append(t(lang, "profile_vibe", vibe=fav_vibe))
    if user.fav_artists:
        lines.append(t(lang, "profile_artists", artists=", ".join(user.fav_artists)))
    if _is_night_mode():
        lines.append("")
        lines.append("◑ Night mode: сейчас BLACK ROOM звучит темнее.")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="BLACK ROOM Wrapped", callback_data="action:wrapped"),
            InlineKeyboardButton(text="Мой вкус", callback_data="action:taste"),
        ],
    ])
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@router.message(Command("wrapped"))
async def cmd_wrapped(message: Message) -> None:
    await _show_wrapped(message, message.from_user)


@router.callback_query(lambda c: c.data == "action:wrapped")
async def handle_wrapped_button(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_wrapped(callback.message, callback.from_user)


async def _show_wrapped(message: Message, tg_user) -> None:
    user = await get_or_create_user(tg_user)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    async with async_session() as session:
        play_count = await session.scalar(
            select(func.count(ListeningHistory.id)).where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_ago,
            )
        ) or 0
        if play_count < 3:
            await message.answer(
                "◉ <b>BLACK ROOM Wrapped</b>\n\n"
                "Пока мало данных за неделю. Послушай ещё несколько треков — и я соберу красивую карточку.",
                parse_mode="HTML",
            )
            return

        top_artists_r = await session.execute(
            select(Track.artist, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_ago,
                Track.artist.isnot(None),
                Track.artist != "",
            )
            .group_by(Track.artist)
            .order_by(func.count().desc())
            .limit(5)
        )
        top_artists = [(row[0], row[1]) for row in top_artists_r.all()]

        top_track_r = await session.execute(
            select(Track.artist, Track.title, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.action == "play",
                ListeningHistory.created_at >= week_ago,
            )
            .group_by(Track.id, Track.artist, Track.title)
            .order_by(func.count().desc())
            .limit(1)
        )
        top_track = top_track_r.first()

        top_source_r = await session.execute(
            select(ListeningHistory.source, func.count().label("cnt"))
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.created_at >= week_ago,
                ListeningHistory.source.isnot(None),
            )
            .group_by(ListeningHistory.source)
            .order_by(func.count().desc())
            .limit(1)
        )
        top_source = top_source_r.first()

        top_vibe_r = await session.execute(
            select(ListeningHistory.action, func.count().label("cnt"))
            .where(
                ListeningHistory.user_id == user.id,
                ListeningHistory.created_at >= week_ago,
                ListeningHistory.action.like("vibe_%"),
            )
            .group_by(ListeningHistory.action)
            .order_by(func.count().desc())
            .limit(1)
        )
        top_vibe = top_vibe_r.first()

    top_track_str = f"{top_track[0]} — {top_track[1]}" if top_track else ""
    lines = [
        "◉ <b>BLACK ROOM Wrapped</b>",
        f"▸ За неделю: <b>{play_count}</b> треков",
    ]
    if _is_night_mode():
        lines.append("◑ Night edition")
    if top_track_str:
        lines.append(f"▸ Трек недели: <b>{top_track_str}</b>")
    if top_artists:
        lines.append("▸ Артисты: " + ", ".join(a for a, _ in top_artists[:3]))
    if top_source:
        lines.append(f"▸ Источник недели: <b>{top_source[0]}</b>")
    if top_vibe:
        lines.append(f"▸ Вайб недели: <b>{_VIBE_NAMES.get(top_vibe[0], 'black')}</b>")

    from bot.services.story_cards import generate_recap_card

    card_bytes = await asyncio.to_thread(
        generate_recap_card,
        user_name=tg_user.first_name or tg_user.username or str(tg_user.id),
        play_count=play_count,
        top_artists=[artist for artist, _ in top_artists],
        top_track=top_track_str,
    )
    if card_bytes:
        await message.answer_photo(
            BufferedInputFile(card_bytes, filename="black_room_wrapped.png"),
            caption="\n".join(lines),
            parse_mode="HTML",
        )
    else:
        await message.answer("\n".join(lines), parse_mode="HTML")


# ── Family Plan ──────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "action:family")
async def handle_family_button(callback: CallbackQuery) -> None:
    await callback.answer()
    from bot.handlers.family import cmd_family
    await cmd_family(callback.message, user=callback.from_user)


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
    await cmd_radar(callback.message, user=callback.from_user)
