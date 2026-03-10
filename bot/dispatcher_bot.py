"""
dispatcher_bot.py — Dispatcher for Bot Fleet / Sharding (5.2).

Routes users to node bots by hash(user_id) % num_nodes.
Provides /start with deep-link redirect and /health dashboard for admins.
"""
import asyncio
import hashlib
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

router = Router()

# Populated at startup from config
_NODE_BOTS: list[dict] = []  # [{"token": "...", "username": "bot_node1", "id": 123}]


def _route_user(user_id: int) -> int:
    """Determine node index for a user."""
    if not _NODE_BOTS:
        return 0
    h = int(hashlib.sha256(str(user_id).encode()).hexdigest(), 16)
    return h % len(_NODE_BOTS)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Route user to their assigned node bot via deep-link."""
    user_id = message.from_user.id

    if not _NODE_BOTS:
        await message.answer("⚠️ No node bots configured. Please try later.")
        return

    node_idx = _route_user(user_id)
    node = _NODE_BOTS[node_idx]
    username = node.get("username", "")

    if username:
        deep_link = f"https://t.me/{username}?start=from_dispatcher"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▸ Перейти к боту", url=deep_link)]
        ])
        await message.answer(
            f"🎵 Добро пожаловать! Вы подключены к ноде #{node_idx + 1}.\n"
            "Нажмите кнопку ниже:",
            reply_markup=kb,
        )
    else:
        await message.answer(f"🎵 Вы подключены к ноде #{node_idx + 1}.")


@router.message(Command("health"))
async def cmd_health(message: Message) -> None:
    """Admin health dashboard — show status of all nodes."""
    from bot.services.node_manager import list_nodes

    nodes = await list_nodes()
    if not nodes:
        await message.answer("Нет нод в пуле.")
        return

    lines = ["<b>🖥 Fleet Dashboard</b>\n"]
    for n in nodes:
        status = "🟢" if n.get("alive") else "🔴"
        node_id = n.get("node_id", "?")
        users = n.get("user_count", 0)
        last_hb = n.get("last_heartbeat", "?")
        lines.append(f"{status} <code>{node_id}</code> — {users} users — HB: {last_hb}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("migrate"))
async def cmd_migrate(message: Message) -> None:
    """Admin: migrate users from a dead/banned node."""
    from bot.services.node_manager import migrate_node

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /migrate <node_id>")
        return

    dead_node = args[1]
    moved = await migrate_node(dead_node)
    await message.answer(f"Migrated {moved} user routing(s) from {dead_node}.")


async def _resolve_node_usernames(dispatcher_bot: Bot, tokens: list[str]) -> None:
    """Resolve node bot usernames by calling getMe with each token."""
    for token in tokens:
        try:
            temp_bot = Bot(token=token)
            me = await temp_bot.get_me()
            _NODE_BOTS.append({
                "token": token,
                "username": me.username,
                "id": me.id,
            })
            await temp_bot.session.close()
        except Exception as e:
            logger.error("Failed to resolve node bot %s: %s", token[:10] + "...", e)


async def run_dispatcher() -> None:
    """Entry point: run the dispatcher bot."""
    from bot.config import settings

    if not settings.DISPATCHER_TOKEN:
        logger.error("DISPATCHER_TOKEN not set")
        return

    # Parse node tokens
    node_tokens = []
    if settings.NODE_TOKENS:
        node_tokens = [t.strip() for t in settings.NODE_TOKENS.split(",") if t.strip()]

    bot = Bot(
        token=settings.DISPATCHER_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Resolve node bot usernames
    if node_tokens:
        await _resolve_node_usernames(bot, node_tokens)
        logger.info("Dispatcher: %d node bots registered", len(_NODE_BOTS))

    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Dispatcher bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_dispatcher())
