"""Check old Supabase project (uhvbdwjchxcnoiodfnvw) — the bot's current DB."""
import asyncio
import asyncpg

OLD_DB = "postgresql://postgres.uhvbdwjchxcnoiodfnvw:MmrqkRANx51jHvBuYQ2ahp4S@aws-1-eu-central-1.pooler.supabase.com:6543/postgres"
NEW_DB = "postgresql://postgres.vexyurbyobnpzyatiikw:MusicBot_AI_2026!@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"


async def audit_db(label, dsn):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    try:
        conn = await asyncpg.connect(dsn, timeout=15)
    except Exception as e:
        print(f"  CONNECTION ERROR: {e}")
        return

    # List tables
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    )
    tables = [r["table_name"] for r in rows]
    print(f"\n  Tables ({len(tables)}):")

    for t in tables:
        try:
            count = await conn.fetchval(f"SELECT count(*) FROM \"{t}\"")
            marker = " <<<" if count > 0 else ""
            print(f"    {t:35s} {count:>8} rows{marker}")
        except Exception as e:
            print(f"    {t:35s} ERROR: {e}")

    # Check extensions
    exts = await conn.fetch(
        "SELECT extname FROM pg_extension ORDER BY extname"
    )
    print(f"\n  Extensions: {', '.join(r['extname'] for r in exts)}")

    # Check indexes count
    idx_count = await conn.fetchval(
        "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'"
    )
    print(f"  Indexes: {idx_count}")

    # Check functions
    funcs = await conn.fetch(
        "SELECT routine_name FROM information_schema.routines "
        "WHERE routine_schema = 'public' ORDER BY routine_name"
    )
    if funcs:
        print(f"  Functions: {', '.join(r['routine_name'] for r in funcs)}")

    await conn.close()


async def main():
    await audit_db("OLD Supabase (uhvbdwjchxcnoiodfnvw) — bot's current DB", OLD_DB)
    await audit_db("NEW Supabase (vexyurbyobnpzyatiikw) — AI engine + new tables", NEW_DB)


asyncio.run(main())
