"""add cascade delete to foreign keys

Revision ID: 001_cascade_delete
Revises: 
Create Date: 2026-03-21

Adds ON DELETE CASCADE to all user_id and track_id foreign keys.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_cascade_delete'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL syntax for dropping and recreating FK constraints with CASCADE
    
    # ── daily_mixes ──
    op.drop_constraint('daily_mixes_user_id_fkey', 'daily_mixes', type_='foreignkey')
    op.create_foreign_key(
        'daily_mixes_user_id_fkey', 'daily_mixes', 'users',
        ['user_id'], ['id'], ondelete='CASCADE'
    )
    
    # ── daily_mix_tracks ──
    op.drop_constraint('daily_mix_tracks_track_id_fkey', 'daily_mix_tracks', type_='foreignkey')
    op.create_foreign_key(
        'daily_mix_tracks_track_id_fkey', 'daily_mix_tracks', 'tracks',
        ['track_id'], ['id'], ondelete='CASCADE'
    )
    
    # ── favorite_tracks ──
    op.drop_constraint('favorite_tracks_user_id_fkey', 'favorite_tracks', type_='foreignkey')
    op.create_foreign_key(
        'favorite_tracks_user_id_fkey', 'favorite_tracks', 'users',
        ['user_id'], ['id'], ondelete='CASCADE'
    )
    
    op.drop_constraint('favorite_tracks_track_id_fkey', 'favorite_tracks', type_='foreignkey')
    op.create_foreign_key(
        'favorite_tracks_track_id_fkey', 'favorite_tracks', 'tracks',
        ['track_id'], ['id'], ondelete='CASCADE'
    )
    
    # ── party_sessions ──
    op.drop_constraint('party_sessions_creator_id_fkey', 'party_sessions', type_='foreignkey')
    op.create_foreign_key(
        'party_sessions_creator_id_fkey', 'party_sessions', 'users',
        ['creator_id'], ['id'], ondelete='CASCADE'
    )
    
    # ── playlists ──
    op.drop_constraint('playlists_user_id_fkey', 'playlists', type_='foreignkey')
    op.create_foreign_key(
        'playlists_user_id_fkey', 'playlists', 'users',
        ['user_id'], ['id'], ondelete='CASCADE'
    )
    
    # ── playlist_tracks ──
    op.drop_constraint('playlist_tracks_track_id_fkey', 'playlist_tracks', type_='foreignkey')
    op.create_foreign_key(
        'playlist_tracks_track_id_fkey', 'playlist_tracks', 'tracks',
        ['track_id'], ['id'], ondelete='CASCADE'
    )
    
    # ── recommendation_log ──
    op.drop_constraint('recommendation_log_user_id_fkey', 'recommendation_log', type_='foreignkey')
    op.create_foreign_key(
        'recommendation_log_user_id_fkey', 'recommendation_log', 'users',
        ['user_id'], ['id'], ondelete='CASCADE'
    )
    
    op.drop_constraint('recommendation_log_track_id_fkey', 'recommendation_log', type_='foreignkey')
    op.create_foreign_key(
        'recommendation_log_track_id_fkey', 'recommendation_log', 'tracks',
        ['track_id'], ['id'], ondelete='CASCADE'
    )


def downgrade() -> None:
    # Revert to FK without CASCADE
    
    # ── recommendation_log ──
    op.drop_constraint('recommendation_log_track_id_fkey', 'recommendation_log', type_='foreignkey')
    op.create_foreign_key(
        'recommendation_log_track_id_fkey', 'recommendation_log', 'tracks',
        ['track_id'], ['id']
    )
    
    op.drop_constraint('recommendation_log_user_id_fkey', 'recommendation_log', type_='foreignkey')
    op.create_foreign_key(
        'recommendation_log_user_id_fkey', 'recommendation_log', 'users',
        ['user_id'], ['id']
    )
    
    # ── playlist_tracks ──
    op.drop_constraint('playlist_tracks_track_id_fkey', 'playlist_tracks', type_='foreignkey')
    op.create_foreign_key(
        'playlist_tracks_track_id_fkey', 'playlist_tracks', 'tracks',
        ['track_id'], ['id']
    )
    
    # ── playlists ──
    op.drop_constraint('playlists_user_id_fkey', 'playlists', type_='foreignkey')
    op.create_foreign_key(
        'playlists_user_id_fkey', 'playlists', 'users',
        ['user_id'], ['id']
    )
    
    # ── party_sessions ──
    op.drop_constraint('party_sessions_creator_id_fkey', 'party_sessions', type_='foreignkey')
    op.create_foreign_key(
        'party_sessions_creator_id_fkey', 'party_sessions', 'users',
        ['creator_id'], ['id']
    )
    
    # ── favorite_tracks ──
    op.drop_constraint('favorite_tracks_track_id_fkey', 'favorite_tracks', type_='foreignkey')
    op.create_foreign_key(
        'favorite_tracks_track_id_fkey', 'favorite_tracks', 'tracks',
        ['track_id'], ['id']
    )
    
    op.drop_constraint('favorite_tracks_user_id_fkey', 'favorite_tracks', type_='foreignkey')
    op.create_foreign_key(
        'favorite_tracks_user_id_fkey', 'favorite_tracks', 'users',
        ['user_id'], ['id']
    )
    
    # ── daily_mix_tracks ──
    op.drop_constraint('daily_mix_tracks_track_id_fkey', 'daily_mix_tracks', type_='foreignkey')
    op.create_foreign_key(
        'daily_mix_tracks_track_id_fkey', 'daily_mix_tracks', 'tracks',
        ['track_id'], ['id']
    )
    
    # ── daily_mixes ──
    op.drop_constraint('daily_mixes_user_id_fkey', 'daily_mixes', type_='foreignkey')
    op.create_foreign_key(
        'daily_mixes_user_id_fkey', 'daily_mixes', 'users',
        ['user_id'], ['id']
    )
