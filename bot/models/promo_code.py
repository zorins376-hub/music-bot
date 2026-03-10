"""PromoCode and PromoActivation models for promotional codes."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    promo_type: Mapped[str] = mapped_column(String(30))  # premium_7d, premium_30d, flac_5
    uses_left: Mapped[int] = mapped_column(Integer, default=1)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class PromoActivation(Base):
    __tablename__ = "promo_activations"
    __table_args__ = (UniqueConstraint("promo_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promo_id: Mapped[int] = mapped_column(Integer, ForeignKey("promo_codes.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
