"""
family_plan.py — Family Plan subscription model.

Supports up to 5 family members sharing one Premium subscription at discount.
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class FamilyPlan(Base):
    """Family Premium subscription."""
    __tablename__ = "family_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), default="Моя семья")
    max_members: Mapped[int] = mapped_column(Integer, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationship to members
    members: Mapped[list["FamilyMember"]] = relationship(
        "FamilyMember", 
        back_populates="family_plan",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    @property
    def is_premium(self) -> bool:
        if not self.premium_until:
            return False
        return self.premium_until > datetime.now(timezone.utc)


class FamilyMember(Base):
    """Member of a family plan."""
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("family_plans.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # 'owner' | 'member'
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationship back to plan
    family_plan: Mapped["FamilyPlan"] = relationship("FamilyPlan", back_populates="members")


class FamilyInvite(Base):
    """Pending invite to join a family plan."""
    __tablename__ = "family_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("family_plans.id", ondelete="CASCADE"), index=True)
    invite_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    uses_left: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
