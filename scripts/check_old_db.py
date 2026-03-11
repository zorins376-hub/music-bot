"""Check old Supabase DB (uhvbdwjchxcnoiodfnvw) — list tables and row counts."""
import asyncio
import asyncpg

OLD_DB = "postgresql://postgres.uhvbdwjchxcnoiodfnvw:MmrqkRANx51jHvBuYQ2ahp4S@aws-1-eu-central-1.pooler.supabase.com:6543/postgres"


async def main():
    conn = await asyncpg.connect(OLD_DB, timeout=15)

    # List all public tables
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    )
    print("=" * 60)
    print("Tables in OLD Supabase (uhvbdwjchxcnoiodfnvw):")
    print("=" * 60)
    for r in rows:
        print(f"  {r['table_name']}")

    print()
    print("=" * 60)
    print("Row counts:")
    print("=" * 60)
    for r in rows:
        t = r["table_name"]
        try:
            count = await conn.fetchval(f"SELECT count(*) FROM \"{t}\"")
            print(f"  {t:35s} {count:>8} rows")
        except Exception as e:
            print(f"  {t:35s} ERROR: {e}")

    await conn.close()


asyncio.run(main())
