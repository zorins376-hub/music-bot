"""add expires_at to promo_codes

Revision ID: 003_promo_expires_at
Revises: 002_cascade_listening_payment
Create Date: 2026-06-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_promo_expires_at"
down_revision: Union[str, None] = "002_cascade_listening_payment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _table_exists("promo_codes"):
        return
    if not _column_exists("promo_codes", "expires_at"):
        op.add_column(
            "promo_codes",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if not _table_exists("promo_codes"):
        return
    if _column_exists("promo_codes", "expires_at"):
        op.drop_column("promo_codes", "expires_at")
