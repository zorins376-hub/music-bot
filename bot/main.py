import asyncio
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, ErrorEvent

from bot.config import settings as app_settings

if app_settings.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(dsn=app_settings.SENTRY_DSN, traces_sample_rate=0.05)

from bot.handlers import admin, charts, faq, history, inline, search, start, video
from bot.handlers import radio, premium, recommend, playlist, recognize, queue, referral
from bot.handlers import favorites
from bot.handlers import mix
from bot.handlers import release_radar
from bot.handlers import ai_playlist
from bot.handlers import import_playlist
from bot.handlers import badges
from bot.handlers import leaderboard
from bot.handlers import settings as settings_handler
from bot.handlers import promote
from bot.handlers import voice_chat
from bot.handlers import family
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.middlewares.captcha import CaptchaMiddleware
from bot.models.base import init_db
from bot.services.cache import cache

_LOG_DIR = Path("/app/logs") if Path("/app").exists() else Path("logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        TimedRotatingFileHandler(
            _LOG_DIR / "bot.log", when="D", backupCount=30, encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger(__name__)

_DL_DIR = Path("/app/downloads") if Path("/app").exists() else Path("downloads")


def _cleanup_stale_downloads(max_age_sec: int = 3600) -> None:
    """Remove temp files from downloads/ older than max_age_sec."""
    import time
    if not _DL_DIR.exists():
        return
    now = time.time()
    removed = 0
    for f in _DL_DIR.iterdir():
        if f.is_file():
            try:
                if now - f.stat().st_mtime > max_age_sec:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
    if removed:
        logger.info("Cleaned up %d stale download(s)", removed)


async def on_startup(bot: Bot) -> None:
    from bot.services.downloader import log_runtime_info
    log_runtime_info()

    # Cleanup stale downloads from previous runs
    _cleanup_stale_downloads()

    await init_db()

    # Load persisted admin IDs from Redis
    from bot.db import load_admin_ids_from_redis
    await load_admin_ids_from_redis()

    # Load DMCA blocked tracks into memory
    from bot.services.dmca_filter import load_blocked_ids
    await load_blocked_ids()

    # Initialize proxy pool
    from bot.services.proxy_pool import proxy_pool, start_proxy_health_scheduler
    proxy_pool.load_from_config()
    if proxy_pool.size:
        asyncio.create_task(start_proxy_health_scheduler())

    if app_settings.METRICS_PORT:
        from bot.services.metrics import start_metrics_server
        start_metrics_server(app_settings.METRICS_PORT)

    # G-03: Daily digest scheduler
    from bot.services.daily_digest import start_digest_scheduler
    await start_digest_scheduler(bot)

    # Release Radar scheduler
    from bot.services.release_radar import start_release_radar_scheduler
    await start_release_radar_scheduler(bot)

    # Chart cache prewarm scheduler
    from bot.handlers.charts import start_chart_cache_prewarm_scheduler
    await start_chart_cache_prewarm_scheduler()

    # Background track indexer (harvests metadata from charts & APIs)
    from bot.services.track_indexer import start_indexer_scheduler
    await start_indexer_scheduler()

    # Deep crawler — runs on separate VPS, not here
    # from bot.services.deep_crawler import start_deep_crawler
    # await start_deep_crawler()

    # Weekly recap scheduler (Monday 10:00 UTC)
    from bot.services.weekly_recap import start_weekly_recap_scheduler
    await start_weekly_recap_scheduler(bot)

    # ML training scheduler (nightly at ML_RETRAIN_HOUR) — skip if Supabase AI handles it
    if not app_settings.SUPABASE_AI_ENABLED:
        from recommender.train import start_ml_training_scheduler
        await start_ml_training_scheduler()

    # Node heartbeat (Bot Fleet 5.2)
    if app_settings.NODE_ID:
        from bot.services.node_manager import register_node, start_heartbeat_loop
        await register_node(app_settings.NODE_ID)
        await start_heartbeat_loop(app_settings.NODE_ID)

    # One-time welcome broadcast for existing users
    asyncio.create_task(_broadcast_welcome(bot))

    # One-time version broadcast for existing users after deploy
    asyncio.create_task(_broadcast_version_update(bot))

    # Register bot commands for private chats
    private_commands = [
        BotCommand(command="start", description="◉ Главное меню"),
        BotCommand(command="search", description="◈ Найти трек"),
        BotCommand(command="mix", description="✦ Daily Mix"),
        BotCommand(command="radar", description="🆕 Release Radar"),
        BotCommand(command="video", description="🎦 Найти клип"),
        BotCommand(command="top", description="◆ Топ треков"),
        BotCommand(command="charts", description="🏆 Топ-чарты"),
        BotCommand(command="stats", description="◎ Моя статистика"),
        BotCommand(command="history", description="▹ Мои запросы"),
        BotCommand(command="settings", description="≡ Качество аудио"),
        BotCommand(command="playlist", description="▸ Плейлисты"),
        BotCommand(command="favorites", description="❤️ Любимое"),
        BotCommand(command="profile", description="◉ Мой профиль"),
        BotCommand(command="lang", description="○ Сменить язык"),
        BotCommand(command="help", description="◌ Справка"),
        BotCommand(command="faq", description="❓ FAQ"),
        BotCommand(command="ai_playlist", description="🤖 AI Плейлист"),
    ]
    try:
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())

        # Register bot commands for group chats
        group_commands = [
            BotCommand(command="search", description="◈ Найти трек"),
            BotCommand(command="video", description="🎦 Найти клип"),
            BotCommand(command="top", description="◆ Топ треков"),
        ]
        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
    except Exception as e:
        logger.warning("Failed to set bot commands (non-fatal): %s", e)

    if app_settings.USE_WEBHOOK:
        await bot.set_webhook(
            url=f"{app_settings.WEBHOOK_URL}{app_settings.WEBHOOK_PATH}",
            secret_token=app_settings.WEBHOOK_SECRET,
        )
        logger.info("Webhook set: %s%s", app_settings.WEBHOOK_URL, app_settings.WEBHOOK_PATH)
    else:
        logger.info("Bot started in polling mode")


async def on_shutdown(bot: Bot) -> None:
    if app_settings.USE_WEBHOOK:
        await bot.delete_webhook()
    await cache.close()

    # Close shared aiohttp session
    from bot.services.http_session import close_session
    await close_session()

    # Close Supabase AI session
    if app_settings.SUPABASE_AI_ENABLED:
        from bot.services.supabase_ai import close as close_supabase
        await close_supabase()

    # Gracefully shutdown thread pools
    from bot.services.downloader import _ytdl_pool
    from bot.services.vk_provider import _vk_pool
    _ytdl_pool.shutdown(wait=False)
    _vk_pool.shutdown(wait=False)

    logger.info("Bot stopped")


async def _global_error_handler(event: ErrorEvent) -> bool:
    """Catch-all: log every unhandled handler exception and reply to the user."""
    logger.exception(
        "Unhandled error on update %s: %s", event.update.update_id, event.exception
    )
    update = event.update
    try:
        if update.message:
            await update.message.answer("\u26a0\ufe0f \u0427\u0442\u043e-\u0442\u043e \u043f\u043e\u0448\u043b\u043e \u043d\u0435 \u0442\u0430\u043a. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437.")
        elif update.callback_query:
            await update.callback_query.answer(
                "\u26a0\ufe0f \u041e\u0448\u0438\u0431\u043a\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0441\u043d\u043e\u0432\u0430.", show_alert=True
            )
    except Exception:
        pass
    return True


async def _broadcast_welcome(bot: Bot) -> None:
    """One-time broadcast welcome message to all existing users who haven't received it yet."""
    from sqlalchemy import select, update
    from bot.models.base import async_session
    from bot.models.user import User
    from bot.version import WELCOME_MESSAGE

    await asyncio.sleep(10)  # Wait for DB to be ready

    try:
        async with async_session() as session:
            # Get all users who passed captcha but haven't received welcome
            result = await session.execute(
                select(User.id).where(
                    User.captcha_passed == True,
                    User.welcome_sent == False
                )
            )
            user_ids = [row[0] for row in result.fetchall()]

        if not user_ids:
            logger.info("Welcome broadcast: no users to notify")
            return

        logger.info("Welcome broadcast: sending to %d users", len(user_ids))
        sent = 0
        failed = 0

        for user_id in user_ids:
            try:
                await bot.send_message(user_id, WELCOME_MESSAGE, parse_mode="HTML")
                sent += 1
                # Mark as sent
                async with async_session() as session:
                    await session.execute(
                        update(User).where(User.id == user_id).values(welcome_sent=True)
                    )
                    await session.commit()
            except Exception as e:
                failed += 1
                # Still mark as sent to avoid retry spam on blocked users
                try:
                    async with async_session() as session:
                        await session.execute(
                            update(User).where(User.id == user_id).values(welcome_sent=True)
                        )
                        await session.commit()
                except Exception:
                    pass
            # Rate limit: 30 msgs/sec max for Telegram
            await asyncio.sleep(0.05)

        logger.info("Welcome broadcast done: sent=%d, failed=%d", sent, failed)

    except Exception as e:
        logger.error("Welcome broadcast error: %s", e)


async def _broadcast_version_update(bot: Bot) -> None:
    """Broadcast current version changelog to all users who haven't seen this version yet."""
    from sqlalchemy import select, update
    from bot.models.base import async_session
    from bot.models.user import User
    from bot.version import VERSION, get_changelog_text
    from bot.i18n import t

    await asyncio.sleep(15)

    try:
        async with async_session() as session:
            result = await session.execute(
                select(User.id, User.language).where(
                    User.captcha_passed == True,
                    (User.last_seen_version.is_(None)) | (User.last_seen_version != VERSION),
                )
            )
            users = result.fetchall()

        if not users:
            logger.info("Version broadcast: no users to notify")
            return

        logger.info("Version broadcast: sending v%s to %d users", VERSION, len(users))
        sent = 0
        failed = 0
        sent_user_ids: list[int] = []

        for user_id, language in users:
            lang = language or "ru"
            changelog_text = get_changelog_text(lang, VERSION)
            message_text = (
                f"<b>{t(lang, 'whats_new')}</b>\n\n{changelog_text}" if changelog_text else f"<b>{t(lang, 'bot_version', version=VERSION)}</b>"
            )
            try:
                await bot.send_message(user_id, message_text, parse_mode="HTML")
                sent += 1
                sent_user_ids.append(user_id)
            except Exception:
                failed += 1

            await asyncio.sleep(0.05)

        if sent_user_ids:
            try:
                async with async_session() as session:
                    await session.execute(
                        update(User)
                        .where(User.id.in_(sent_user_ids))
                        .values(last_seen_version=VERSION)
                    )
                    await session.commit()
            except Exception as e:
                logger.error("Version broadcast post-update error: %s", e)

        logger.info("Version broadcast done: sent=%d, failed=%d", sent, failed)

    except Exception as e:
        logger.error("Version broadcast error: %s", e)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    dp.message.middleware(CaptchaMiddleware())
    dp.message.middleware(ThrottleMiddleware())
    dp.message.middleware(LoggingMiddleware())

    dp.include_router(start.router)
    dp.include_router(admin.router)      # Admin (before search for forward mode)
    dp.include_router(playlist.router)   # Playlists
    dp.include_router(favorites.router)  # Favorites
    dp.include_router(mix.router)        # Daily Mix
    dp.include_router(release_radar.router)  # Release Radar
    dp.include_router(radio.router)      # TEQUILA/FULLMOON LIVE, AUTO MIX
    dp.include_router(premium.router)    # Premium
    dp.include_router(family.router)     # Family Plan
    dp.include_router(recommend.router)  # AI DJ
    dp.include_router(ai_playlist.router)  # Prompt-to-Playlist
    dp.include_router(import_playlist.router)  # Spotify/Yandex/Apple import
    dp.include_router(promote.router)  # B2B Artist Promo
    dp.include_router(voice_chat.router)  # Voice Chat UI
    dp.include_router(badges.router)  # Achievements/badges
    dp.include_router(leaderboard.router)  # XP leaderboard
    dp.include_router(queue.router)      # Queue
    dp.include_router(referral.router)   # Referral system
    dp.include_router(faq.router)                # FAQ
    dp.include_router(settings_handler.router)  # /settings (quality)
    dp.include_router(charts.router)              # Top charts
    dp.include_router(video.router)                # Video search & download
    dp.include_router(recognize.router)            # Shazam: voice/audio/video recognition
    dp.include_router(search.router)
    dp.include_router(inline.router)
    dp.include_router(history.router)

    dp.error.register(_global_error_handler)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp


async def _run_webhook(bot: Bot, dp: Dispatcher) -> None:
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    app = web.Application()
    handler = SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=app_settings.WEBHOOK_SECRET
    )
    handler.register(app, path=app_settings.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, app_settings.WEB_SERVER_HOST, app_settings.WEB_SERVER_PORT)
    await site.start()
    logger.info("Listening on %s:%d", app_settings.WEB_SERVER_HOST, app_settings.WEB_SERVER_PORT)
    await asyncio.Event().wait()  # run forever


async def main() -> None:
    bot = Bot(
        token=app_settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    if app_settings.USE_WEBHOOK:
        await _run_webhook(bot, dp)
    else:
        # Start TMA webapp alongside polling if TMA_URL is configured
        tma_task = None
        if app_settings.TMA_URL:
            tma_task = asyncio.create_task(_run_tma_server())
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            if tma_task:
                tma_task.cancel()


async def _run_tma_server() -> None:
    """Run TMA Player FastAPI server alongside the bot."""
    try:
        import uvicorn
        from webapp.api import app as tma_app

        port = int(__import__("os").environ.get("PORT", "8080"))
        config = uvicorn.Config(
            tma_app,
            host="0.0.0.0",
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        logger.info("TMA webapp starting on port %d", port)
        await server.serve()
    except Exception as e:
        logger.error("TMA webapp failed to start: %s", e)


if __name__ == "__main__":
    asyncio.run(main())
