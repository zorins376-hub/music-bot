"""Check sync counts on VPS."""
import sys
sys.path.insert(0, "deploy")
from ssh_cmd import ssh_exec

SQL = "SELECT tablename, n_live_tup FROM pg_stat_user_tables ORDER BY tablename"
cmd = f'cd /opt/music-bot && docker compose exec -T postgres psql -U musicbot -d musicbot -t -A -c "{SQL}"'
print(ssh_exec(cmd))
