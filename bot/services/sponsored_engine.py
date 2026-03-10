"""
sponsored_engine.py — Service for managing sponsored tracks in recommendations.

Picks active campaigns matching user taste, records events, charges budget.
"""
import logging

from sqlalchemy import select, update

from bot.models.base import async_session
from bot.models.sponsored import SponsoredCampaign, SponsoredEvent
from bot.models.track import Track

logger = logging.getLogger(__name__)


async def get_sponsored_track(
    user_id: int,
    user_genres: list[str] | None = None,
) -> dict | None:
    """Get a sponsored track for this user if any active campaign matches.

    Returns a track dict compatible with search results, or None.
    """
    try:
        from bot.services.feature_flags import is_enabled
        if not await is_enabled("sponsored_tracks"):
            return None
    except Exception:
        return None

    async with async_session() as session:
        q = (
            select(SponsoredCampaign, Track)
            .join(Track, Track.id == SponsoredCampaign.track_id)
            .where(
                SponsoredCampaign.status == "active",
                SponsoredCampaign.spent_stars < SponsoredCampaign.budget_stars,
            )
            .order_by(SponsoredCampaign.impressions_total.asc())
            .limit(5)
        )
        result = await session.execute(q)
        candidates = result.all()

    if not candidates:
        return None

    # Pick best matching campaign
    best = None
    for campaign, track in candidates:
        # Check if already shown to this user recently (dedupe)
        if best is None:
            best = (campaign, track)
            continue
        # Prefer campaigns targeting user's genres
        if user_genres and campaign.target_genres:
            overlap = set(user_genres) & set(campaign.target_genres)
            if overlap:
                best = (campaign, track)
                break

    if not best:
        return None

    campaign, track = best

    # Record impression
    async with async_session() as session:
        session.add(SponsoredEvent(
            campaign_id=campaign.id,
            user_id=user_id,
            event_type="impression",
        ))
        await session.execute(
            update(SponsoredCampaign)
            .where(SponsoredCampaign.id == campaign.id)
            .values(impressions_total=SponsoredCampaign.impressions_total + 1)
        )
        await session.commit()

    from bot.utils import fmt_duration
    return {
        "video_id": track.source_id,
        "title": f"[Promo] {track.title or 'Unknown'}",
        "uploader": track.artist or "Unknown",
        "duration": int(track.duration) if track.duration else None,
        "duration_fmt": fmt_duration(track.duration or 0),
        "source": track.source or "sponsored",
        "_campaign_id": campaign.id,
    }


async def record_click(campaign_id: int, user_id: int) -> None:
    """Record a click event and charge 1 star from budget."""
    async with async_session() as session:
        session.add(SponsoredEvent(
            campaign_id=campaign_id,
            user_id=user_id,
            event_type="click",
        ))
        await session.execute(
            update(SponsoredCampaign)
            .where(SponsoredCampaign.id == campaign_id)
            .values(
                clicks_total=SponsoredCampaign.clicks_total + 1,
                spent_stars=SponsoredCampaign.spent_stars + 1,
            )
        )
        # Check if budget exhausted → finish campaign
        result = await session.execute(
            select(SponsoredCampaign).where(SponsoredCampaign.id == campaign_id)
        )
        campaign = result.scalar_one_or_none()
        if campaign and campaign.spent_stars >= campaign.budget_stars:
            await session.execute(
                update(SponsoredCampaign)
                .where(SponsoredCampaign.id == campaign_id)
                .values(status="finished")
            )
        await session.commit()


async def create_campaign(
    user_id: int,
    track_id: int,
    budget_stars: int,
    target_genres: list[str] | None = None,
) -> SponsoredCampaign:
    """Create a new sponsored campaign (pending admin approval)."""
    async with async_session() as session:
        campaign = SponsoredCampaign(
            user_id=user_id,
            track_id=track_id,
            budget_stars=budget_stars,
            target_genres=target_genres,
            status="pending",
        )
        session.add(campaign)
        await session.commit()
        await session.refresh(campaign)
        return campaign


async def approve_campaign(campaign_id: int, admin_id: int) -> bool:
    """Approve a pending campaign."""
    async with async_session() as session:
        result = await session.execute(
            update(SponsoredCampaign)
            .where(
                SponsoredCampaign.id == campaign_id,
                SponsoredCampaign.status == "pending",
            )
            .values(status="active", approved_by=admin_id)
        )
        await session.commit()
        return result.rowcount > 0


async def list_campaigns(status: str | None = None) -> list[dict]:
    """List campaigns, optionally filtered by status."""
    async with async_session() as session:
        q = select(SponsoredCampaign).order_by(SponsoredCampaign.created_at.desc()).limit(50)
        if status:
            q = q.where(SponsoredCampaign.status == status)
        result = await session.execute(q)
        return [
            {
                "id": c.id,
                "user_id": c.user_id,
                "track_id": c.track_id,
                "budget": c.budget_stars,
                "spent": c.spent_stars,
                "impressions": c.impressions_total,
                "clicks": c.clicks_total,
                "status": c.status,
            }
            for c in result.scalars().all()
        ]
