import os
import psycopg2
_dsn = os.environ.get("SUPABASE_DSN") or os.environ.get("DATABASE_URL")
if not _dsn:
    raise SystemExit("Set SUPABASE_DSN (or DATABASE_URL) env var (never hardcode DSNs).")
conn = psycopg2.connect(_dsn.replace("postgresql+asyncpg://", "postgresql://"))
cur = conn.cursor()

# List all tables
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
print('Tables:', [r[0] for r in cur.fetchall()])

# Check users columns
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' ORDER BY ordinal_position")
cols = [r[0] for r in cur.fetchall()]
print(f'Users has {len(cols)} columns:', cols)

conn.close()
