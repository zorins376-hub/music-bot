"""Quick check: channel track counts in DB."""
import os, psycopg2
db = os.environ.get("DATABASE_URL","").replace("postgresql+asyncpg","postgresql")
if not db:
    db = "postgresql://musicbot:musicbot@postgres:5432/musicbot"
conn = psycopg2.connect(db)
cur = conn.cursor()
cur.execute("SELECT channel, COUNT(*) FROM tracks WHERE channel IS NOT NULL GROUP BY channel ORDER BY COUNT(*) DESC")
for row in cur.fetchall():
    print(f"{row[0]}: {row[1]} tracks")
cur.execute("SELECT COUNT(*) FROM tracks")
print(f"TOTAL: {cur.fetchone()[0]} tracks")
conn.close()
