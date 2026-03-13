#!/usr/bin/env python3
"""Kill all PostgreSQL connections and run sync."""
import paramiko
import sys
import time
from pathlib import Path

HOST = "89.169.52.174"
USER = "root"
PASS = "YjfWW9v6j2m5"


def run(ssh, cmd, timeout=120):
    print(f">>> {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out)
    if err.strip():
        print(err, file=sys.stderr)
    return code, out, err


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS)

    # 0) Upload latest local sync script to VPS
    local_sync = Path(__file__).with_name("sync_supabase_to_local.py")
    remote_sync = "/opt/music-bot/deploy/sync_supabase_to_local.py"
    sftp = ssh.open_sftp()
    sftp.put(str(local_sync), remote_sync)
    sftp.close()
    print(f">>> uploaded {local_sync} -> {remote_sync}")

    # 1) Stop bot to release DB locks during truncate/import
    run(ssh, "cd /opt/music-bot && docker compose stop bot")

    # 1) Kill all DB connections
    run(ssh, """cd /opt/music-bot && docker compose exec -T postgres psql -U musicbot -d musicbot -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='musicbot' AND pid != pg_backend_pid()" """)

    # 2) Clear tables directly via psql (TRUNCATE hangs on this host)
    run(
        ssh,
        "cd /opt/music-bot && docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U musicbot -d musicbot "
        "-c \"DELETE FROM listening_history; DELETE FROM playlist_tracks; DELETE FROM favorite_tracks; "
        "DELETE FROM daily_mix_tracks; DELETE FROM playlists; DELETE FROM tracks; DELETE FROM users;\"",
        timeout=1800,
    )

    time.sleep(2)

    # 3) Run sync via mounted volume
    code, _, _ = run(ssh,
        "cd /opt/music-bot && docker compose run --rm "
        "-v /opt/music-bot/deploy/sync_supabase_to_local.py:/app/deploy/sync_supabase_to_local.py "
        "bot python /app/deploy/sync_supabase_to_local.py",
        timeout=1800)

    # 4) Start bot only on successful sync
    if code == 0:
        run(ssh, "cd /opt/music-bot && docker compose start bot")
    else:
        print("Sync failed; bot remains stopped for investigation.", file=sys.stderr)
        sys.exit(code)

    ssh.close()


if __name__ == "__main__":
    main()
