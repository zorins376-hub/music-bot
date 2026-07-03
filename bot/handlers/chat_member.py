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
    if chat.type == "channel":
        # Loudly log the channel id — this is how CACHE_CHANNEL_ID / radio
        # channels are discovered (private channels have no @username, and a
        # bot cannot resolve an invite link; re-adding the bot fires this).
        logger.info(
            "CHANNEL EVENT: bot %s in channel id=%s title=%r",
            event.new_chat_member.status, chat.id, chat.title,
        )
        return
    if chat.type not in ("group", "supergroup"):
        return

    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status if event.old_chat_member else ""

    async with async_session() as session:
        existing = await session.get(BotChat, chat.id)

        if new_status in _MEMBER_STATUSES:
            was_active = bool(existing and existing.is_active)
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

            # One short onboarding message on a FRESH add (not on admin-promote
            # or rejoin of an active chat): without it the trigger syntax is
            # undiscoverable and plain song requests are silently ignored.
            if not was_active and old_status not in _MEMBER_STATUSES:
                try:
                    await event.bot.send_message(
                        chat.id,
                        "◇ <b>BLACK ROOM</b> в чате.\n\n"
                        "Напиши <b>включи «название трека»</b> или ответь на моё "
                        "сообщение названием — пришлю музыку прямо сюда.\n"
                        "Например: <i>включи кино группа крови</i>",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.debug("group welcome message failed for %s", chat.id, exc_info=True)

        elif new_status in _LEFT_STATUSES:
            if existing:
                existing.is_active = False
            logger.info("Bot removed from chat %s (%s)", chat.id, chat.title)

        await session.commit()
