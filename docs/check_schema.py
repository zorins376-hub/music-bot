import os
import psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

# List all tables
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
print('Tables:', [r[0] for r in cur.fetchall()])

# Check users columns
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' ORDER BY ordinal_position")
cols = [r[0] for r in cur.fetchall()]
print(f'Users has {len(cols)} columns:', cols)

conn.close()
