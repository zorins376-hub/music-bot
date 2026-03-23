"""Track bot join/leave events for group chats."""
import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from bot.models.base import async_session
from bot.models.bot_chat import BotChat
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = Router()

_MEMBER_STATUSES = {"member", "administrator", "creator"}
_LEFT_STATUSES = {"left", "kicked"}


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    """Bot was added to or removed from a chat."""
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    new_status = event.new_chat_member.status

    async with async_session() as session:
        existing = await session.get(BotChat, chat.id)

        if new_status in _MEMBER_STATUSES:
            if existing:
                existing.is_active = True
                existing.title = chat.title
            else:
                session.add(BotChat(
                    chat_id=chat.id,
                    title=chat.title,
                    chat_type=chat.type,
                    is_active=True,
                ))
            logger.info("Bot added to chat %s (%s)", chat.id, chat.title)

        elif new_status in _LEFT_STATUSES:
            if existing:
                existing.is_active = False
            logger.info("Bot removed from chat %s (%s)", chat.id, chat.title)

        await session.commit()
