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
from bot.handlers import radio, premium, recommend, playlist, recognize
from bot.handlers import settings as settings_handler
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


async def on_startup(bot: Bot) -> None:
    from bot.services.downloader import log_runtime_info
    log_runtime_info()

    await init_db()

    if app_settings.METRICS_PORT:
        from bot.services.metrics import start_metrics_server
        start_metrics_server(app_settings.METRICS_PORT)

    # Register bot commands for private chats
    private_commands = [
        BotCommand(command="start", description="◉ Главное меню"),
        BotCommand(command="search", description="◈ Найти трек"),
        BotCommand(command="video", description="🎦 Найти клип"),
        BotCommand(command="top", description="◆ Топ треков"),
        BotCommand(command="charts", description="🏆 Топ-чарты"),
        BotCommand(command="stats", description="◎ Моя статистика"),
        BotCommand(command="history", description="▹ Мои запросы"),
        BotCommand(command="settings", description="≡ Качество аудио"),
        BotCommand(command="playlist", description="▸ Плейлисты"),
        BotCommand(command="profile", description="◉ Мой профиль"),
        BotCommand(command="lang", description="○ Сменить язык"),
        BotCommand(command="help", description="◌ Справка"),
        BotCommand(command="faq", description="❓ FAQ"),
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


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    dp.message.middleware(CaptchaMiddleware())
    dp.message.middleware(ThrottleMiddleware())
    dp.message.middleware(LoggingMiddleware())

    dp.include_router(start.router)
    dp.include_router(admin.router)      # Admin (before search for forward mode)
    dp.include_router(playlist.router)   # Playlists
    dp.include_router(radio.router)      # TEQUILA/FULLMOON LIVE, AUTO MIX
    dp.include_router(premium.router)    # Premium
    dp.include_router(recommend.router)  # AI DJ
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
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
