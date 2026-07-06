import asyncio
import os

import asyncpg

async def check():
    dsn = os.environ.get("OLD_SUPABASE_DSN") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Set OLD_SUPABASE_DSN (or DATABASE_URL) env var (never hardcode DSNs).")
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
    )
    print("Tables:", [t['tablename'] for t in tables])
    for t in tables:
        name = t['tablename']
        count = await conn.fetchval(f'SELECT count(*) FROM "{name}"')
        print(f"  {name}: {count} rows")
    # Show last 5 users if table exists
    tnames = [t['tablename'] for t in tables]
    if 'users' in tnames:
        users = await conn.fetch('SELECT id, username, first_name, is_premium, request_count, created_at FROM users ORDER BY created_at DESC LIMIT 5')
        print("\nRecent users:")
        for u in users:
            print(f"  {u['username']} | premium={u['is_premium']} | requests={u['request_count']} | {u['created_at']}")
    if 'tracks' in tnames:
        tracks = await conn.fetch('SELECT title, artist, downloads FROM tracks ORDER BY downloads DESC LIMIT 5')
        print("\nTop tracks:")
        for tr in tracks:
            print(f"  {tr['artist']} - {tr['title']} ({tr['downloads']} downloads)")
    await conn.close()

asyncio.run(check())
