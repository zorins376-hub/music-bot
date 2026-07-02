"""add cascade delete to foreign keys

Revision ID: 001_cascade_delete
Revises: 
Create Date: 2026-03-21

Adds ON DELETE CASCADE to all user_id and track_id foreign keys.
Skips tables that are not present (legacy/partial DBs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "001_cascade_delete"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _recreate_fk(
    table: str,
    constraint: str,
    ref_table: str,
    columns: list[str],
    ref_columns: list[str],
) -> None:
    if not _table_exists(table):
        return
    op.drop_constraint(constraint, table, type_="foreignkey")
    op.create_foreign_key(
        constraint, table, ref_table, columns, ref_columns, ondelete="CASCADE"
    )


def upgrade() -> None:
    _recreate_fk("daily_mixes", "daily_mixes_user_id_fkey", "users", ["user_id"], ["id"])
    _recreate_fk("daily_mix_tracks", "daily_mix_tracks_track_id_fkey", "tracks", ["track_id"], ["id"])
    _recreate_fk("favorite_tracks", "favorite_tracks_user_id_fkey", "users", ["user_id"], ["id"])
    _recreate_fk("favorite_tracks", "favorite_tracks_track_id_fkey", "tracks", ["track_id"], ["id"])
    _recreate_fk("party_sessions", "party_sessions_creator_id_fkey", "users", ["creator_id"], ["id"])
    _recreate_fk("playlists", "playlists_user_id_fkey", "users", ["user_id"], ["id"])
    _recreate_fk("playlist_tracks", "playlist_tracks_track_id_fkey", "tracks", ["track_id"], ["id"])
    _recreate_fk("recommendation_log", "recommendation_log_user_id_fkey", "users", ["user_id"], ["id"])
    _recreate_fk("recommendation_log", "recommendation_log_track_id_fkey", "tracks", ["track_id"], ["id"])


def downgrade() -> None:
    def _revert_fk(table, constraint, ref_table, columns, ref_columns):
        if not _table_exists(table):
            return
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(constraint, table, ref_table, columns, ref_columns)

    _revert_fk("recommendation_log", "recommendation_log_track_id_fkey", "tracks", ["track_id"], ["id"])
    _revert_fk("recommendation_log", "recommendation_log_user_id_fkey", "users", ["user_id"], ["id"])
    _revert_fk("playlist_tracks", "playlist_tracks_track_id_fkey", "tracks", ["track_id"], ["id"])
    _revert_fk("playlists", "playlists_user_id_fkey", "users", ["user_id"], ["id"])
    _revert_fk("party_sessions", "party_sessions_creator_id_fkey", "users", ["creator_id"], ["id"])
    _revert_fk("favorite_tracks", "favorite_tracks_track_id_fkey", "tracks", ["track_id"], ["id"])
    _revert_fk("favorite_tracks", "favorite_tracks_user_id_fkey", "users", ["user_id"], ["id"])
    _revert_fk("daily_mix_tracks", "daily_mix_tracks_track_id_fkey", "tracks", ["track_id"], ["id"])
    _revert_fk("daily_mixes", "daily_mixes_user_id_fkey", "users", ["user_id"], ["id"])
