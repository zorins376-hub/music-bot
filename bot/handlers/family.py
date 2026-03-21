"""
family.py — Family Plan management handlers.

Commands:
- /family — show family plan status or create new
- /family_invite — generate invite link
- /family_join <code> — join a family using invite code
- /family_leave — leave current family
- /family_kick <user_id> — owner removes member
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from sqlalchemy import delete, select, update, func as sqla_func

from bot.config import settings
from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.family_plan import FamilyInvite, FamilyMember, FamilyPlan
from bot.models.user import User

logger = logging.getLogger(__name__)

router = Router()

# ── Prices ────────────────────────────────────────────────────────────────
_FAMILY_PRICE_30D = 250  # vs 150 single = 67% savings for 5 members
_FAMILY_PRICE_90D = 650  # −13%
_FAMILY_PRICE_365D = 2000  # −33%
_MAX_FAMILY_MEMBERS = 5
_INVITE_EXPIRE_HOURS = 48


async def _get_user_family(user_id: int) -> tuple[FamilyPlan | None, FamilyMember | None]:
    """Get family plan and membership for user."""
    async with async_session() as session:
        result = await session.execute(
            select(FamilyMember)
            .options()
            .where(FamilyMember.user_id == user_id)
        )
        member = result.scalar_one_or_none()
        if not member:
            return None, None
        
        result = await session.execute(
            select(FamilyPlan).where(FamilyPlan.id == member.family_plan_id)
        )
        plan = result.scalar_one_or_none()
        return plan, member


async def _get_family_members_count(plan_id: int) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(sqla_func.count(FamilyMember.id))
            .where(FamilyMember.family_plan_id == plan_id)
        )
        return result.scalar() or 0


@router.message(Command("family"))
async def cmd_family(message: Message) -> None:
    """Show family plan status or offer to create one."""
    user = await get_or_create_user(message.from_user)
    lang = user.language
    
    plan, member = await _get_user_family(user.id)
    
    if plan:
        # User has a family plan
        is_owner = member.role == "owner"
        members_count = await _get_family_members_count(plan.id)
        until_str = plan.premium_until.strftime("%d.%m.%Y") if plan.premium_until else "-"
        
        text = t(lang, "family_status",
            name=plan.name,
            members=members_count,
            max_members=plan.max_members,
            until=until_str,
            is_active="✅" if plan.is_premium else "❌"
        )
        
        buttons = []
        if is_owner:
            buttons.append([InlineKeyboardButton(
                text=t(lang, "family_invite_btn"),
                callback_data="family:invite"
            )])
            if not plan.is_premium:
                buttons.append([InlineKeyboardButton(
                    text=t(lang, "family_buy_30d_btn", price=_FAMILY_PRICE_30D),
                    callback_data="family:buy:30d"
                )])
            buttons.append([InlineKeyboardButton(
                text=t(lang, "family_manage_btn"),
                callback_data="family:manage"
            )])
        else:
            buttons.append([InlineKeyboardButton(
                text=t(lang, "family_leave_btn"),
                callback_data="family:leave"
            )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        # No family plan
        text = t(lang, "family_info")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t(lang, "family_create_btn"),
                callback_data="family:create"
            )],
            [InlineKeyboardButton(
                text=t(lang, "family_join_btn"),
                callback_data="family:join_prompt"
            )],
        ])
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "family:create")
async def handle_family_create(callback: CallbackQuery) -> None:
    """Create a new family plan."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    
    # Check if already in family
    plan, _ = await _get_user_family(user.id)
    if plan:
        await callback.message.answer(t(lang, "family_already_member"))
        return
    
    async with async_session() as session:
        # Create family plan
        new_plan = FamilyPlan(
            owner_id=user.id,
            name=f"{user.first_name or 'User'}'s Family"
        )
        session.add(new_plan)
        await session.flush()
        
        # Add owner as member
        owner_member = FamilyMember(
            family_plan_id=new_plan.id,
            user_id=user.id,
            role="owner"
        )
        session.add(owner_member)
        await session.commit()
        
        logger.info("Family plan %s created by user %s", new_plan.id, user.id)
    
    # Show purchase options
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t(lang, "family_buy_30d_btn", price=_FAMILY_PRICE_30D),
            callback_data="family:buy:30d"
        )],
        [InlineKeyboardButton(
            text=t(lang, "family_buy_90d_btn", price=_FAMILY_PRICE_90D),
            callback_data="family:buy:90d"
        )],
        [InlineKeyboardButton(
            text=t(lang, "family_buy_365d_btn", price=_FAMILY_PRICE_365D),
            callback_data="family:buy:365d"
        )],
    ])
    await callback.message.answer(t(lang, "family_created"), reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "family:invite")
async def handle_family_invite(callback: CallbackQuery) -> None:
    """Generate invite link for family."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    
    plan, member = await _get_user_family(user.id)
    if not plan or member.role != "owner":
        await callback.message.answer(t(lang, "family_not_owner"))
        return
    
    # Check member limit
    count = await _get_family_members_count(plan.id)
    if count >= plan.max_members:
        await callback.message.answer(t(lang, "family_full"))
        return
    
    # Generate invite code
    code = secrets.token_urlsafe(8)[:12].upper()
    expires = datetime.now(timezone.utc) + timedelta(hours=_INVITE_EXPIRE_HOURS)
    
    async with async_session() as session:
        invite = FamilyInvite(
            family_plan_id=plan.id,
            invite_code=code,
            uses_left=1,
            expires_at=expires
        )
        session.add(invite)
        await session.commit()
    
    bot_username = (await callback.bot.me()).username
    invite_link = f"https://t.me/{bot_username}?start=fam_{code}"
    
    await callback.message.answer(
        t(lang, "family_invite_created", code=code, link=invite_link, hours=_INVITE_EXPIRE_HOURS),
        parse_mode="HTML"
    )


@router.callback_query(lambda c: c.data == "family:join_prompt")
async def handle_family_join_prompt(callback: CallbackQuery) -> None:
    """Prompt user to enter invite code."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await callback.message.answer(t(user.language, "family_enter_code"), parse_mode="HTML")


@router.message(Command("family_join"))
async def cmd_family_join(message: Message) -> None:
    """Join family using invite code."""
    user = await get_or_create_user(message.from_user)
    lang = user.language
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(t(lang, "family_enter_code"))
        return
    
    await _join_family_by_code(message, user, parts[1].strip().upper())


async def _join_family_by_code(message: Message, user: User, code: str) -> None:
    """Process family join by code."""
    lang = user.language
    
    # Check if already in family
    plan, _ = await _get_user_family(user.id)
    if plan:
        await message.answer(t(lang, "family_already_member"))
        return
    
    async with async_session() as session:
        # Find invite
        result = await session.execute(
            select(FamilyInvite).where(FamilyInvite.invite_code == code)
        )
        invite = result.scalar_one_or_none()
        
        if not invite:
            await message.answer(t(lang, "family_invite_invalid"))
            return
        
        if invite.uses_left <= 0:
            await message.answer(t(lang, "family_invite_used"))
            return
        
        if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
            await message.answer(t(lang, "family_invite_expired"))
            return
        
        # Check family member limit
        count = await _get_family_members_count(invite.family_plan_id)
        result = await session.execute(
            select(FamilyPlan).where(FamilyPlan.id == invite.family_plan_id)
        )
        family = result.scalar_one_or_none()
        
        if not family or count >= family.max_members:
            await message.answer(t(lang, "family_full"))
            return
        
        # Add member
        new_member = FamilyMember(
            family_plan_id=invite.family_plan_id,
            user_id=user.id,
            role="member"
        )
        session.add(new_member)
        
        # Decrement invite uses
        invite.uses_left -= 1
        
        # If family has active premium, grant it to new member
        if family.is_premium:
            await session.execute(
                update(User).where(User.id == user.id)
                .values(is_premium=True, premium_until=family.premium_until)
            )
        
        await session.commit()
        logger.info("User %s joined family %s", user.id, family.id)
    
    await message.answer(t(lang, "family_joined", name=family.name), parse_mode="HTML")


@router.callback_query(lambda c: c.data == "family:leave")
async def handle_family_leave(callback: CallbackQuery) -> None:
    """Leave current family."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    
    plan, member = await _get_user_family(user.id)
    if not plan:
        await callback.message.answer(t(lang, "family_not_member"))
        return
    
    if member.role == "owner":
        await callback.message.answer(t(lang, "family_owner_cant_leave"))
        return
    
    async with async_session() as session:
        await session.execute(
            delete(FamilyMember).where(FamilyMember.user_id == user.id)
        )
        # Revoke premium if it came from family
        await session.execute(
            update(User).where(User.id == user.id)
            .values(is_premium=False, premium_until=None)
        )
        await session.commit()
    
    await callback.message.answer(t(lang, "family_left"), parse_mode="HTML")


@router.callback_query(lambda c: c.data == "family:manage")
async def handle_family_manage(callback: CallbackQuery) -> None:
    """Show family management options."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    
    plan, member = await _get_user_family(user.id)
    if not plan or member.role != "owner":
        await callback.message.answer(t(lang, "family_not_owner"))
        return
    
    async with async_session() as session:
        result = await session.execute(
            select(FamilyMember)
            .where(FamilyMember.family_plan_id == plan.id)
        )
        members = result.scalars().all()
    
    # List members with kick buttons
    text = t(lang, "family_members_title", name=plan.name) + "\n\n"
    buttons = []
    
    for m in members:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.id == m.user_id)
            )
            u = result.scalar_one_or_none()
        
        role_icon = "👑" if m.role == "owner" else "👤"
        name = u.first_name or u.username or str(u.id) if u else str(m.user_id)
        text += f"{role_icon} {name}\n"
        
        if m.role != "owner":
            buttons.append([InlineKeyboardButton(
                text=f"❌ {name}",
                callback_data=f"family:kick:{m.user_id}"
            )])
    
    buttons.append([InlineKeyboardButton(
        text=t(lang, "family_rename_btn"),
        callback_data="family:rename"
    )])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data.startswith("family:kick:"))
async def handle_family_kick(callback: CallbackQuery) -> None:
    """Owner kicks a member."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    
    target_id = int(callback.data.split(":")[2])
    
    plan, member = await _get_user_family(user.id)
    if not plan or member.role != "owner":
        await callback.message.answer(t(lang, "family_not_owner"))
        return
    
    if target_id == user.id:
        await callback.message.answer(t(lang, "family_cant_kick_self"))
        return
    
    async with async_session() as session:
        # Verify target is in same family
        result = await session.execute(
            select(FamilyMember)
            .where(FamilyMember.user_id == target_id)
            .where(FamilyMember.family_plan_id == plan.id)
        )
        target_member = result.scalar_one_or_none()
        
        if not target_member:
            await callback.message.answer(t(lang, "family_member_not_found"))
            return
        
        await session.execute(
            delete(FamilyMember).where(FamilyMember.user_id == target_id)
        )
        await session.execute(
            update(User).where(User.id == target_id)
            .values(is_premium=False, premium_until=None)
        )
        await session.commit()
    
    await callback.message.answer(t(lang, "family_member_kicked"), parse_mode="HTML")
    
    # Notify kicked user
    try:
        await callback.bot.send_message(target_id, t("ru", "family_you_were_kicked"))
    except Exception:
        logger.debug("Failed to notify kicked family member user_id=%s", target_id, exc_info=True)


# ── Payment handlers ─────────────────────────────────────────────────────

_PAYLOAD_FAMILY_30D = "family_30d"
_PAYLOAD_FAMILY_90D = "family_90d"
_PAYLOAD_FAMILY_365D = "family_365d"


@router.callback_query(lambda c: c.data == "family:buy:30d")
async def handle_family_buy_30d(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    
    plan, member = await _get_user_family(user.id)
    if not plan or member.role != "owner":
        await callback.message.answer(t(lang, "family_not_owner"))
        return
    
    await callback.message.answer_invoice(
        title=t(lang, "family_invoice_30d_title"),
        description=t(lang, "family_invoice_30d_desc"),
        payload=f"{_PAYLOAD_FAMILY_30D}:{plan.id}",
        currency="XTR",
        prices=[LabeledPrice(label="Family Premium 30d", amount=_FAMILY_PRICE_30D)],
    )


@router.callback_query(lambda c: c.data == "family:buy:90d")
async def handle_family_buy_90d(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    
    plan, member = await _get_user_family(user.id)
    if not plan or member.role != "owner":
        await callback.message.answer(t(lang, "family_not_owner"))
        return
    
    await callback.message.answer_invoice(
        title=t(lang, "family_invoice_90d_title"),
        description=t(lang, "family_invoice_90d_desc"),
        payload=f"{_PAYLOAD_FAMILY_90D}:{plan.id}",
        currency="XTR",
        prices=[LabeledPrice(label="Family Premium 90d", amount=_FAMILY_PRICE_90D)],
    )


@router.callback_query(lambda c: c.data == "family:buy:365d")
async def handle_family_buy_365d(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    
    plan, member = await _get_user_family(user.id)
    if not plan or member.role != "owner":
        await callback.message.answer(t(lang, "family_not_owner"))
        return
    
    await callback.message.answer_invoice(
        title=t(lang, "family_invoice_365d_title"),
        description=t(lang, "family_invoice_365d_desc"),
        payload=f"{_PAYLOAD_FAMILY_365D}:{plan.id}",
        currency="XTR",
        prices=[LabeledPrice(label="Family Premium 365d", amount=_FAMILY_PRICE_365D)],
    )


@router.pre_checkout_query(lambda q: q.invoice_payload.startswith("family_"))
async def handle_family_pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_family_payment(message: Message) -> None:
    """Process successful family premium payment."""
    payload = message.successful_payment.invoice_payload
    if not payload.startswith("family_"):
        return  # Let other handlers process
    
    user = await get_or_create_user(message.from_user)
    lang = user.language
    
    parts = payload.split(":")
    plan_type = parts[0]
    plan_id = int(parts[1]) if len(parts) > 1 else None
    
    if not plan_id:
        return
    
    now = datetime.now(timezone.utc)
    
    if plan_type == _PAYLOAD_FAMILY_30D:
        days = 30
    elif plan_type == _PAYLOAD_FAMILY_90D:
        days = 90
    elif plan_type == _PAYLOAD_FAMILY_365D:
        days = 365
    else:
        return
    
    premium_until = now + timedelta(days=days)
    
    async with async_session() as session:
        # Update family plan
        await session.execute(
            update(FamilyPlan)
            .where(FamilyPlan.id == plan_id)
            .values(premium_until=premium_until, is_active=True)
        )
        
        # Get all family members
        result = await session.execute(
            select(FamilyMember).where(FamilyMember.family_plan_id == plan_id)
        )
        members = result.scalars().all()
        
        # Grant premium to all members
        for member in members:
            await session.execute(
                update(User)
                .where(User.id == member.user_id)
                .values(is_premium=True, premium_until=premium_until)
            )
        
        # Record payment
        from bot.models.track import Payment
        session.add(Payment(
            user_id=user.id,
            amount=message.successful_payment.total_amount,
            currency=message.successful_payment.currency,
            payload=payload,
        ))
        
        await session.commit()
        logger.info("Family %s premium activated until %s for %d members", 
                    plan_id, premium_until, len(members))
    
    await message.answer(t(lang, "family_premium_activated", days=days), parse_mode="HTML")


# ── Deep link handler for family invite ──────────────────────────────────

async def handle_family_deeplink(message: Message, code: str) -> bool:
    """Handle family invite deep link. Returns True if handled."""
    if not code.startswith("fam_"):
        return False
    
    invite_code = code[4:].upper()
    user = await get_or_create_user(message.from_user)
    await _join_family_by_code(message, user, invite_code)
    return True
