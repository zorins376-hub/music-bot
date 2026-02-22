import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.handlers import admin, history, inline, search, start
from bot.handlers import radio, premium, recommend, settings
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.models.base import init_db
from bot.services.cache import cache

_LOG_DIR = Path("/app/logs") if Path("/app").exists() else Path("logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    await init_db()
    if settings.USE_WEBHOOK:
        await bot.set_webhook(
            url=f"{settings.WEBHOOK_URL}{settings.WEBHOOK_PATH}",
            secret_token=settings.WEBHOOK_SECRET,
        )
        logger.info("Webhook set: %s%s", settings.WEBHOOK_URL, settings.WEBHOOK_PATH)
    else:
        logger.info("Bot started in polling mode")


async def on_shutdown(bot: Bot) -> None:
    if settings.USE_WEBHOOK:
        await bot.delete_webhook()
    await cache.close()
    logger.info("Bot stopped")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    dp.message.middleware(ThrottleMiddleware())
    dp.message.middleware(LoggingMiddleware())

    dp.include_router(start.router)
    dp.include_router(radio.router)      # TEQUILA/FULLMOON LIVE, AUTO MIX
    dp.include_router(premium.router)    # Premium
    dp.include_router(recommend.router)  # AI DJ
    dp.include_router(settings.router)  # /settings (quality)
    dp.include_router(search.router)
    dp.include_router(inline.router)
    dp.include_router(history.router)
    dp.include_router(admin.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp


async def _run_webhook(bot: Bot, dp: Dispatcher) -> None:
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    app = web.Application()
    handler = SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=settings.WEBHOOK_SECRET
    )
    handler.register(app, path=settings.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.WEB_SERVER_HOST, settings.WEB_SERVER_PORT)
    await site.start()
    logger.info("Listening on %s:%d", settings.WEB_SERVER_HOST, settings.WEB_SERVER_PORT)
    await asyncio.Event().wait()  # run forever


async def main() -> None:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    if settings.USE_WEBHOOK:
        await _run_webhook(bot, dp)
    else:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
