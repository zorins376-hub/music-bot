#!/usr/bin/env python3
"""
Sync data from Supabase REST API into local PostgreSQL.

Usage:  Run inside the bot Docker container:
    docker compose exec bot python /app/deploy/sync_supabase_to_local.py

Reads SUPABASE_DB_URL/SUPABASE_DB_KEY from env (the music-bot project with main DB).
Writes into the local DATABASE_URL PostgreSQL.
"""

import asyncio
import json as json_mod
import logging
import os
import sys
from datetime import date, datetime, timezone

import aiohttp
from sqlalchemy import text

# Ensure bot package is importable
sys.path.insert(0, "/app")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync")

# ── Supabase source (music-bot project = main DB) ───────────────────────────
SUPA_URL = os.environ.get(
    "SUPABASE_DB_URL",
    "https://uhvbdwjchxcnoiodfnvw.supabase.co",
)
SUPA_KEY = os.environ.get(
    "SUPABASE_DB_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVodmJkd2pjaHhjbm9pb2RmbnZ3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTg1MDAwOSwiZXhwIjoyMDg3NDI2MDA5fQ.tLm2O84rRZHgcoPQgbgb8zVC3zRCBzy54xS0qCF_6Gw",
)

# Optional extra source (music-bot-ai project = AI/ML). We import only users from it.
SUPA_AI_URL = os.environ.get(
    "SUPABASE_AI_DB_URL",
    "https://vexyurbyobnpzyatiikw.supabase.co",
)
SUPA_AI_KEY = os.environ.get(
    "SUPABASE_AI_DB_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZleHl1cmJ5b2JucHp5YXRpaWt3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MzE3OTkzOCwiZXhwIjoyMDg4NzU1OTM4fQ.qa9t7XPT2XkYYz21yHg8vS_ZQLGWxNStJWRjuNWnU9U",
)

HEADERS = {
    "Authorization": f"Bearer {SUPA_KEY}",
    "apikey": SUPA_KEY,
    "Content-Type": "application/json",
}

# Tables to sync in dependency order.
# Each entry: (table_name, supabase_select, order_column)
TABLES = [
    ("users", "*", "id"),
    ("tracks", "*", "id"),
    ("playlists", "*", "id"),
    ("playlist_tracks", "*", "id"),
    ("favorite_tracks", "*", "id"),
    ("listening_history", "*", "id"),
]

PAGE_SIZE = 500  # Supabase REST max is 1000


async def fetch_all(session: aiohttp.ClientSession, table: str, select: str, order: str):
    """Paginate through Supabase REST and return all rows."""
    rows = []
    offset = 0
    while True:
        url = f"{SUPA_URL}/rest/v1/{table}"
        params = {
            "select": select,
            "order": f"{order}.asc",
            "limit": str(PAGE_SIZE),
            "offset": str(offset),
        }
        async with session.get(url, headers=HEADERS, params=params) as resp:
            if resp.status != 200:
                text_body = await resp.text()
                log.error("Fetch %s offset=%d failed %d: %s", table, offset, resp.status, text_body)
                break
            batch = await resp.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return rows


async def fetch_all_from(
    session: aiohttp.ClientSession,
    base_url: str,
    headers: dict,
    table: str,
    select: str,
    order: str,
):
    rows = []
    offset = 0
    while True:
        url = f"{base_url}/rest/v1/{table}"
        params = {
            "select": select,
            "order": f"{order}.asc",
            "limit": str(PAGE_SIZE),
            "offset": str(offset),
        }
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                text_body = await resp.text()
                log.error("Fetch %s from %s offset=%d failed %d: %s", table, base_url, offset, resp.status, text_body)
                break
            batch = await resp.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return rows


def build_upsert_sql(table: str, columns: list[str], pk: str = "id") -> str:
    """Build an UPSERT (INSERT ... ON CONFLICT DO UPDATE) statement."""
    cols = ", ".join(f'"{c}"' for c in columns)
    vals = ", ".join(f":{c}" for c in columns)
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in columns if c != pk)
    return f'INSERT INTO {table} ({cols}) VALUES ({vals}) ON CONFLICT ("{pk}") DO UPDATE SET {updates}'


def normalize_row(row: dict) -> dict:
    clean = {}
    for k, v in row.items():
        if isinstance(v, str) and "T" in v and len(v) > 18:
            try:
                clean[k] = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                clean[k] = v
        elif isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
            try:
                clean[k] = date.fromisoformat(v)
            except ValueError:
                clean[k] = v
        elif isinstance(v, (list, dict)):
            clean[k] = json_mod.dumps(v, ensure_ascii=False)
        else:
            clean[k] = v
    return clean


async def get_table_columns(db_session, table: str) -> list[str]:
    q = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:table "
        "ORDER BY ordinal_position"
    )
    r = await db_session.execute(q, {"table": table})
    return [row[0] for row in r.fetchall()]


async def sync_table(
    session: aiohttp.ClientSession,
    db_session,
    table: str,
    select: str,
    order: str,
):
    """Fetch from Supabase and upsert into local DB."""
    log.info("Syncing table: %s", table)
    rows = await fetch_all(session, table, select, order)
    if not rows:
        log.info("  %s: 0 rows, skipping", table)
        return 0

    columns = list(rows[0].keys())
    sql = build_upsert_sql(table, columns)

    count = 0
    errors = 0
    for row in rows:
        clean = normalize_row(row)
        try:
            async with db_session.begin_nested():
                await db_session.execute(text(sql), clean)
            count += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                log.warning("  Row error in %s (id=%s): %s", table, row.get("id"), e)
            elif errors == 6:
                log.warning("  ... suppressing further errors for %s", table)
            continue

    await db_session.commit()
    log.info("  %s: synced %d / %d rows", table, count, len(rows))
    return count


async def sync_ai_users(session: aiohttp.ClientSession, db_session) -> int:
    if not SUPA_AI_KEY:
        log.info("AI users sync skipped: SUPABASE_AI_DB_KEY is empty")
        return 0

    ai_headers = {
        "Authorization": f"Bearer {SUPA_AI_KEY}",
        "apikey": SUPA_AI_KEY,
        "Content-Type": "application/json",
    }
    rows = await fetch_all_from(session, SUPA_AI_URL, ai_headers, "users", "*", "id")
    if not rows:
        log.info("AI users sync: 0 rows from %s", SUPA_AI_URL)
        return 0

    local_columns = await get_table_columns(db_session, "users")
    selected = [c for c in local_columns if any(c in r for r in rows)]
    if "id" not in selected:
        log.warning("AI users sync skipped: no id column in payload")
        return 0

    sql = build_upsert_sql("users", selected)
    count = 0
    errors = 0
    for row in rows:
        payload = {c: row.get(c) for c in selected}
        clean = normalize_row(payload)
        try:
            async with db_session.begin_nested():
                await db_session.execute(text(sql), clean)
            count += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                log.warning("  AI users row error (id=%s): %s", row.get("id"), e)
            elif errors == 6:
                log.warning("  ... suppressing further AI users errors")
            continue

    await db_session.commit()
    log.info("  ai_users: synced %d / %d rows", count, len(rows))
    return count


async def fix_sequences(db_session):
    """Reset auto-increment sequences to max(id)+1."""
    tables_with_seq = ["users", "tracks", "playlists", "playlist_tracks",
                       "favorite_tracks", "listening_history"]
    for table in tables_with_seq:
        try:
            r = await db_session.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(max(id), 1)) FROM {table}")
            )
            val = r.scalar()
            log.info("  Sequence %s.id reset to %s", table, val)
        except Exception as e:
            log.debug("  Sequence reset for %s skipped: %s", table, e)
            await db_session.rollback()


async def main():
    from bot.models.base import async_session, init_db

    log.info("=== Supabase → Local PostgreSQL sync ===")
    log.info("Source: %s", SUPA_URL)

    # Initialize local DB (create tables if needed)
    await init_db()

    log.info("Truncate step is managed by deploy/run_sync.py")

    async with aiohttp.ClientSession() as http:
        async with async_session() as db:
            total = 0
            for table, select, order in TABLES:
                n = await sync_table(http, db, table, select, order)
                total += n

            total += await sync_ai_users(http, db)

            await fix_sequences(db)

    log.info("=== Done! Total rows synced: %d ===", total)


if __name__ == "__main__":
    asyncio.run(main())
