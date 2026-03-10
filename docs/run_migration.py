"""Run database migration."""
import asyncio
import os
from pathlib import Path

# Use sync psycopg2 for simple migration
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    import subprocess
    subprocess.check_call(["pip", "install", "psycopg2-binary", "-q"])
    import psycopg2


def run_migration():
    # Get DATABASE_URL - convert asyncpg format to psycopg2 format
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        db_url = "postgresql://postgres.uhvbdwjchxcnoiodfnvw:MmrqkRANx51jHvBuYQ2ahp4S@aws-1-eu-central-1.pooler.supabase.com:6543/postgres"
    
    # Remove +asyncpg if present
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    
    print(f"Connecting to database...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    
    # Read migration file
    migration_file = Path(__file__).parent / "migrations" / "001_user_columns.sql"
    sql = migration_file.read_text(encoding="utf-8")
    
    # Split by semicolons and execute each statement
    statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]
    
    success = 0
    errors = 0
    
    print(f"Running {len(statements)} statements...")
    for i, stmt in enumerate(statements, 1):
        if not stmt or stmt.startswith('--'):
            continue
        try:
            cur.execute(stmt)
            if stmt.strip().upper().startswith('SELECT'):
                result = cur.fetchone()
                if result:
                    print(f"  [{i}] ✅ {result[0]}")
            else:
                print(f"  [{i}] ✅ OK")
            success += 1
        except Exception as e:
            err_msg = str(e).split('\n')[0]
            if 'already exists' in err_msg.lower() or 'duplicate' in err_msg.lower():
                print(f"  [{i}] ⏭️ Already exists, skipping")
                success += 1
            else:
                print(f"  [{i}] ❌ {err_msg[:80]}")
                errors += 1
    
    cur.close()
    conn.close()
    
    print(f"\n{'='*40}")
    print(f"Migration complete: {success} OK, {errors} errors")
    
    if errors > 0:
        return 1
    return 0


if __name__ == "__main__":
    exit(run_migration())
