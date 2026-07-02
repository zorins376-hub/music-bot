#!/usr/bin/env python3
"""Kill all PostgreSQL connections and run sync."""
import os
import sys
import time
from pathlib import Path

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_common import connect_ssh

PROJECT_DIR = os.environ.get("DEPLOY_PROJECT_DIR", "/root/music-bot").strip()


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
    ssh = connect_ssh()

    local_sync = Path(__file__).with_name("sync_supabase_to_local.py")
    remote_sync = f"{PROJECT_DIR}/deploy/sync_supabase_to_local.py"
    sftp = ssh.open_sftp()
    sftp.put(str(local_sync), remote_sync)
    sftp.close()
    print(f">>> uploaded {local_sync} -> {remote_sync}")

    run(ssh, f"cd {PROJECT_DIR} && docker compose stop bot")

    # Safety dump BEFORE any DELETE, so a failed/empty sync is always recoverable.
    # Run inside bash with pipefail so a pg_dump failure propagates through the gzip pipe.
    ts = time.strftime("%Y%m%d_%H%M%S")
    dump_code, _, _ = run(
        ssh,
        "bash -c 'set -o pipefail; mkdir -p /root/db-backups && "
        f"cd {PROJECT_DIR} && docker compose exec -T postgres "
        "pg_dump -U musicbot -d musicbot | gzip > "
        f"/root/db-backups/pre_sync_{ts}.sql.gz && "
        f"test -s /root/db-backups/pre_sync_{ts}.sql.gz'",
        timeout=1800,
    )
    if dump_code != 0:
        print(
            "Pre-sync safety dump failed; aborting before touching the DB.",
            file=sys.stderr,
        )
        ssh.close()
        sys.exit(dump_code or 1)
    print(f">>> safety dump written to /root/db-backups/pre_sync_{ts}.sql.gz")

    run(
        ssh,
        f"cd {PROJECT_DIR} && docker compose exec -T postgres psql -U musicbot -d musicbot "
        '-c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
        "WHERE datname='musicbot' AND pid != pg_backend_pid()\"",
    )

    run(
        ssh,
        f"cd {PROJECT_DIR} && docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U musicbot -d musicbot "
        '-c "DELETE FROM listening_history; DELETE FROM playlist_tracks; DELETE FROM favorite_tracks; '
        'DELETE FROM daily_mix_tracks; DELETE FROM playlists; DELETE FROM tracks; DELETE FROM users;"',
        timeout=1800,
    )

    time.sleep(2)

    code, _, _ = run(
        ssh,
        f"cd {PROJECT_DIR} && docker compose run --rm "
        f"-v {PROJECT_DIR}/deploy/sync_supabase_to_local.py:/app/deploy/sync_supabase_to_local.py "
        "bot python /app/deploy/sync_supabase_to_local.py",
        timeout=1800,
    )

    if code == 0:
        run(ssh, f"cd {PROJECT_DIR} && docker compose start bot")
    else:
        print("Sync failed; bot remains stopped for investigation.", file=sys.stderr)
        sys.exit(code)

    ssh.close()


if __name__ == "__main__":
    main()
