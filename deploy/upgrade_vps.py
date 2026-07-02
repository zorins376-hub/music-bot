"""
deploy/upgrade_vps.py — Upgrade VPS from Railway config to VPS-optimized.

Usage:
    python deploy/upgrade_vps.py
"""
import os
import sys
import time

try:
    import paramiko
except ImportError:
    print("Installing paramiko...")
    os.system(f"{sys.executable} -m pip install paramiko")
    import paramiko

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_common import connect_ssh, get_ssh_config

PROJECT_DIR = os.environ.get("DEPLOY_PROJECT_DIR", "/opt/music-bot").strip()

VPS_SETTINGS = """
# VPS-OPTIMIZED SETTINGS (upgraded from Railway)
YTDL_WORKERS=8
YTDL_MAX_WORKERS_MULTIPLIER=4
YTDL_CONCURRENT_FRAGMENTS=8
HTTP_POOL_CONNECTIONS=100
HTTP_POOL_KEEPALIVE=30
HTTP_CONNECT_TIMEOUT=10
HTTP_READ_TIMEOUT=60
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30
DB_POOL_TIMEOUT=30
DB_COMMAND_TIMEOUT=30
DB_CONNECT_TIMEOUT=60
METRICS_PORT=9090
"""


def ssh_exec(ssh: paramiko.SSHClient, cmd: str, check: bool = True) -> str:
    print(f"  $ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=300)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode()
    err = stderr.read().decode()
    if exit_code != 0 and check:
        print(f"  ERROR: {err}")
        raise RuntimeError(f"Command failed: {cmd}")
    return out


def main():
    host, _, _, _ = get_ssh_config()
    print(f"=== Upgrading VPS {host} to VPS-optimized config ===")

    ssh = connect_ssh(timeout=30)

    try:
        print("\n[1/5] Backing up current .env...")
        ssh_exec(ssh, f"cp {PROJECT_DIR}/.env {PROJECT_DIR}/.env.backup.$(date +%Y%m%d_%H%M%S)")

        print("\n[2/5] Checking current config...")
        current_env = ssh_exec(ssh, f"cat {PROJECT_DIR}/.env")

        if "YTDL_WORKERS=8" in current_env:
            print("  VPS settings already applied!")
        else:
            print("\n[3/5] Adding VPS-optimized settings...")
            add_cmd = f"""cat >> {PROJECT_DIR}/.env << 'EOFVPS'
{VPS_SETTINGS}
EOFVPS"""
            ssh_exec(ssh, add_cmd)
            print("  Settings added!")

        print("\n[4/5] Rebuilding containers with new config...")
        ssh_exec(ssh, f"cd {PROJECT_DIR} && docker compose down")
        ssh_exec(ssh, f"cd {PROJECT_DIR} && docker compose build --no-cache bot")

        print("\n[5/5] Starting containers...")
        ssh_exec(ssh, f"cd {PROJECT_DIR} && docker compose up -d")

        time.sleep(5)
        status = ssh_exec(ssh, f"cd {PROJECT_DIR} && docker compose ps")
        print("\n=== Container Status ===")
        print(status)

        print("\n=== VPS Config Applied ===")
        new_env = ssh_exec(ssh, f"grep -E 'YTDL_|HTTP_|DB_|METRICS_' {PROJECT_DIR}/.env")
        print(new_env)

        print("\n✅ VPS upgrade complete!")

    finally:
        ssh.close()


if __name__ == "__main__":
    main()
