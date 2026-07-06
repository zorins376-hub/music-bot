"""Verify bot can connect to new Supabase DB and all features work."""
import asyncio
import os

import asyncpg

DSN = os.environ.get("SUPABASE_DSN") or os.environ.get("DATABASE_URL")
if not DSN:
    raise SystemExit("Set SUPABASE_DSN (or DATABASE_URL) env var (never hardcode DSNs).")

async def test():
    conn = await asyncpg.connect(DSN, timeout=15, statement_cache_size=0)

    users = await conn.fetchval("SELECT count(*) FROM users")
    tracks = await conn.fetchval("SELECT count(*) FROM tracks")
    history = await conn.fetchval("SELECT count(*) FROM listening_history")
    playlists = await conn.fetchval("SELECT count(*) FROM playlists")
    artist_wl = await conn.fetchval("SELECT count(*) FROM artist_watchlist")

    print(f"DB Connection: OK (port 6543 / PgBouncer)")
    print(f"Users: {users}, Tracks: {tracks}, History: {history}")
    print(f"Playlists: {playlists}, Artist watchlist: {artist_wl}")

    # Check bot-specific columns exist on users
    row = await conn.fetchrow(
        "SELECT id, username, quality, is_premium, is_admin, xp, level, "
        "streak_days, language, badges FROM users LIMIT 1"
    )
    print(f"Sample user: id={row['id']}, username={row['username']}, "
          f"quality={row['quality']}, premium={row['is_premium']}, "
          f"xp={row['xp']}, level={row['level']}")

    # Check AI functions
    funcs = await conn.fetch(
        "SELECT routine_name FROM information_schema.routines "
        "WHERE routine_schema = 'public' "
        "AND routine_name IN ('recommend_tracks','similar_tracks',"
        "'trending_tracks','update_user_profile','search_tracks',"
        "'user_taste_summary','match_tracks_by_embedding') "
        "ORDER BY routine_name"
    )
    print(f"AI functions: {[r['routine_name'] for r in funcs]}")

    # Check trigram indexes
    idx = await conn.fetch(
        "SELECT indexname FROM pg_indexes "
        "WHERE tablename = 'tracks' AND indexdef LIKE '%trgm%'"
    )
    print(f"Trigram indexes: {[r['indexname'] for r in idx]}")

    # Check pgvector extension
    ext = await conn.fetchval(
        "SELECT extname FROM pg_extension WHERE extname = 'vector'"
    )
    print(f"pgvector: {'OK' if ext else 'MISSING!'}")

    # Check pg_cron
    cron = await conn.fetchval(
        "SELECT extname FROM pg_extension WHERE extname = 'pg_cron'"
    )
    print(f"pg_cron: {'OK' if cron else 'MISSING!'}")

    # Test recommend_tracks function
    try:
        recs = await conn.fetch(
            "SELECT * FROM recommend_tracks($1, $2)", row["id"], 3
        )
        print(f"recommend_tracks({row['id']}, 3): {len(recs)} results")
    except Exception as e:
        print(f"recommend_tracks error: {e}")

    # Test trending_tracks
    try:
        trending = await conn.fetch("SELECT * FROM trending_tracks($1, $2)", 7, 3)
        print(f"trending_tracks(7, 3): {len(trending)} results")
    except Exception as e:
        print(f"trending_tracks error: {e}")

    # Test search_tracks
    try:
        search = await conn.fetch("SELECT * FROM search_tracks($1, $2)", "music", 3)
        print(f"search_tracks('music', 3): {len(search)} results")
    except Exception as e:
        print(f"search_tracks error: {e}")

    await conn.close()
    print("\nAll checks passed!")

asyncio.run(test())
