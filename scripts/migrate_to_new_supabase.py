"""
Migrate all data from OLD Supabase (uhvbdwjchxcnoiodfnvw) to NEW Supabase (vexyurbyobnpzyatiikw).

Steps:
1. Clear test data in NEW DB
2. Copy all tables in FK-safe order
3. Reset identity sequences
4. Verify row counts match
"""
import asyncio
import asyncpg
import sys

OLD_DSN = "postgresql://postgres.uhvbdwjchxcnoiodfnvw:MmrqkRANx51jHvBuYQ2ahp4S@aws-1-eu-central-1.pooler.supabase.com:6543/postgres"
NEW_DSN = "postgresql://postgres.vexyurbyobnpzyatiikw:MusicBot_AI_2026!@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"

# Tables in FK-safe insertion order (parents first, children last)
TABLES_ORDERED = [
    "users",
    "tracks",
    "listening_history",
    "payments",
    "playlists",
    "playlist_tracks",
    "favorite_tracks",
    "release_notifications",
    "admin_log",
    "blocked_tracks",
    "promo_codes",
    "promo_activations",
    "sponsored_campaigns",
    "sponsored_events",
    "dmca_appeals",
    "daily_mixes",
    "daily_mix_tracks",
    "share_links",
    "artist_watchlist",
    "family_plans",
    "family_members",
    "family_invites",
]

# Tables to clear in reverse FK order (children first)
TABLES_CLEAR = list(reversed(TABLES_ORDERED))


async def get_columns(conn, table):
    """Get column names for a table."""
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 "
        "ORDER BY ordinal_position",
        table,
    )
    return [r["column_name"] for r in rows]


async def migrate_table(old_conn, new_conn, table, old_cols, new_cols):
    """Copy all rows from old to new for a single table."""
    # Use only columns that exist in BOTH databases
    common_cols = [c for c in old_cols if c in new_cols]
    if not common_cols:
        print(f"  SKIP {table}: no common columns")
        return 0

    cols_str = ", ".join(f'"{c}"' for c in common_cols)

    # Fetch all rows from old
    rows = await old_conn.fetch(f'SELECT {cols_str} FROM "{table}"')
    if not rows:
        return 0

    # Build parameterized INSERT with OVERRIDING SYSTEM VALUE (for identity columns)
    placeholders = ", ".join(f"${i+1}" for i in range(len(common_cols)))
    insert_sql = (
        f'INSERT INTO "{table}" ({cols_str}) '
        f"OVERRIDING SYSTEM VALUE "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT DO NOTHING"
    )

    inserted = 0
    for row in rows:
        try:
            result = await new_conn.execute(insert_sql, *[row[c] for c in common_cols])
            if "INSERT 0 1" in result:
                inserted += 1
        except Exception as e:
            print(f"  WARN {table} row error: {e}")

    return inserted


async def reset_sequences(conn):
    """Reset all identity/serial sequences to max(id) + 1."""
    tables_with_id = await conn.fetch(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'id' "
        "AND is_identity = 'YES'"
    )
    for r in tables_with_id:
        table = r["table_name"]
        try:
            max_id = await conn.fetchval(f'SELECT COALESCE(MAX(id), 0) FROM "{table}"')
            if max_id > 0:
                await conn.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), $1)",
                    max_id,
                )
        except Exception:
            pass


async def main():
    print("Connecting to OLD Supabase...")
    old_conn = await asyncpg.connect(OLD_DSN, timeout=15)
    print("Connecting to NEW Supabase...")
    new_conn = await asyncpg.connect(NEW_DSN, timeout=15)

    # Phase 1: Clear test data in NEW DB
    print("\n--- Phase 1: Clear test data in NEW DB ---")
    # Clear AI-specific test data too
    for t in ["user_feedback", "user_profiles", "embedding_queue"] + TABLES_CLEAR:
        try:
            result = await new_conn.execute(f'DELETE FROM "{t}"')
            count = int(result.split()[-1])
            if count > 0:
                print(f"  Cleared {t}: {count} rows")
        except Exception:
            pass

    # Phase 2: Copy data table by table
    print("\n--- Phase 2: Migrate data ---")
    total_migrated = 0
    for table in TABLES_ORDERED:
        # Get columns from both DBs
        old_cols = await get_columns(old_conn, table)
        new_cols = await get_columns(new_conn, table)

        old_count = await old_conn.fetchval(f'SELECT count(*) FROM "{table}"')
        if old_count == 0:
            continue

        inserted = await migrate_table(old_conn, new_conn, table, old_cols, new_cols)
        total_migrated += inserted
        print(f"  {table:35s} {old_count:>6} -> {inserted:>6} migrated")

    # Phase 3: Reset sequences
    print("\n--- Phase 3: Reset identity sequences ---")
    await reset_sequences(new_conn)
    print("  Done")

    # Phase 4: Verify
    print("\n--- Phase 4: Verify row counts ---")
    all_ok = True
    for table in TABLES_ORDERED:
        old_count = await old_conn.fetchval(f'SELECT count(*) FROM "{table}"')
        new_count = await new_conn.fetchval(f'SELECT count(*) FROM "{table}"')
        status = "OK" if old_count == new_count else "MISMATCH!"
        if old_count != new_count:
            all_ok = False
        if old_count > 0 or new_count > 0:
            print(f"  {table:35s} old={old_count:>6}  new={new_count:>6}  {status}")

    print(f"\n{'='*60}")
    if all_ok:
        print("  ALL DATA MIGRATED SUCCESSFULLY!")
    else:
        print("  SOME TABLES HAVE MISMATCHES — check above")
    print(f"  Total rows migrated: {total_migrated}")
    print(f"{'='*60}")

    await old_conn.close()
    await new_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
