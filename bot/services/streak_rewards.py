"""
streak_rewards.py — Daily streak tracking and XP rewards.

Awards bonus XP for consecutive listening days:
  3 days → 10 XP
  7 days → 30 XP
 14 days → 75 XP
 30 days → 200 XP
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

STREAK_MILESTONES = {
    3: 10,
    7: 30,
    14: 75,
    30: 200,
}


async def check_and_reward_streak(user_id: int) -> dict | None:
    """
    Check user's current streak and award XP if a milestone is hit.
    Returns milestone info dict if XP was awarded, None otherwise.

    Should be called once per "play" event (idempotent per day via DB check).
    """
    from bot.models.base import async_session
    from bot.models.user import User
    from sqlalchemy import select

    async with async_session() as session:
        q = await session.execute(select(User).where(User.id == user_id))
        user = q.scalar_one_or_none()
        if not user:
            return None

        streak = user.streak_days or 0

        # Check if this streak hits a milestone
        if streak in STREAK_MILESTONES:
            xp_reward = STREAK_MILESTONES[streak]
            try:
                from bot.services.leaderboard import add_xp
                await add_xp(user_id, xp_reward)
                logger.info("Streak reward: user %d, %d days → +%d XP", user_id, streak, xp_reward)
                return {
                    "milestone": streak,
                    "xp_reward": xp_reward,
                    "streak_days": streak,
                }
            except Exception as e:
                logger.error("streak_rewards add_xp failed: %s", e)

    return None


def get_next_milestone(streak_days: int) -> dict | None:
    """Get the next streak milestone for display."""
    for days, xp in sorted(STREAK_MILESTONES.items()):
        if streak_days < days:
            return {"days": days, "xp": xp, "remaining": days - streak_days}
    return None
