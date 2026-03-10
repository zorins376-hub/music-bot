"""
promote.py — B2B Artist Promo handler.

Artists can create sponsored campaigns to promote tracks via Stars.
Admins approve/reject campaigns.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.db import get_or_create_user
from bot.i18n import t
from bot.services.sponsored_engine import (
    approve_campaign,
    create_campaign,
    list_campaigns,
)

router = Router()


class PromoState(StatesGroup):
    waiting_track_id = State()
    waiting_budget = State()
    waiting_genres = State()


@router.message(Command("promote"))
async def cmd_promote(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    await message.answer(t(lang, "promote_intro"), parse_mode="HTML")
    await state.set_state(PromoState.waiting_track_id)


@router.message(PromoState.waiting_track_id)
async def handle_track_id(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Отправь ID трека (число).")
        return
    await state.update_data(track_id=int(text))
    await message.answer("Сколько Stars готов потратить на промо? (минимум 10)")
    await state.set_state(PromoState.waiting_budget)


@router.message(PromoState.waiting_budget)
async def handle_budget(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) < 10:
        await message.answer("Минимальный бюджет — 10 Stars.")
        return
    await state.update_data(budget=int(text))
    await message.answer(
        "Укажи целевые жанры через запятую (или 'all' для всех):"
    )
    await state.set_state(PromoState.waiting_genres)


@router.message(PromoState.waiting_genres)
async def handle_genres(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    data = await state.get_data()
    await state.clear()

    text = (message.text or "").strip()
    genres = [] if text.lower() == "all" else [g.strip() for g in text.split(",") if g.strip()]

    campaign = await create_campaign(
        user_id=user.id,
        track_id=data["track_id"],
        budget_stars=data["budget"],
        target_genres=genres or None,
    )

    if campaign:
        await message.answer(
            t(lang, "promote_created", campaign_id=campaign["id"]),
            parse_mode="HTML",
        )
    else:
        await message.answer(t(lang, "promote_error"), parse_mode="HTML")


@router.message(Command("admin_campaigns"))
async def cmd_admin_campaigns(message: Message) -> None:
    """Admin: list pending campaigns."""
    user = await get_or_create_user(message.from_user)
    if not user.is_admin:
        return

    campaigns = await list_campaigns(status="pending")
    if not campaigns:
        await message.answer("Нет кампаний на модерации.")
        return

    lines = ["<b>Кампании на модерации:</b>\n"]
    for c in campaigns:
        lines.append(
            f"ID: {c['id']} | Track: {c['track_id']} | "
            f"Budget: {c['budget_stars']}★ | User: {c['user_id']}"
        )
        lines.append(f"  /approve_campaign {c['id']}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("approve_campaign"))
async def cmd_approve_campaign(message: Message) -> None:
    """Admin: approve a campaign."""
    user = await get_or_create_user(message.from_user)
    if not user.is_admin:
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: /approve_campaign <id>")
        return

    ok = await approve_campaign(int(args[1]), admin_id=user.id)
    await message.answer("✅ Кампания одобрена." if ok else "⚠️ Не удалось одобрить.")
