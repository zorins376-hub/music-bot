"""
deploy/upgrade_vps.py — Upgrade VPS from Railway config to VPS-optimized.

Adds VPS-specific env vars and rebuilds containers.

Usage:
    python deploy/upgrade_vps.py
"""
import os
import sys

# Ensure paramiko is available
try:
    import paramiko
except ImportError:
    print("Installing paramiko...")
    os.system(f"{sys.executable} -m pip install paramiko")
    import paramiko

VPS_HOST = "89.169.52.174"
VPS_USER = "root"
VPS_PASS = "YjfWW9v6j2m5"
PROJECT_DIR = "/opt/music-bot"

# VPS-optimized settings to add/update
VPS_SETTINGS = """
# ═══════════════════════════════════════════════════════════════════════════
# VPS-OPTIMIZED SETTINGS (upgraded from Railway)
# ═══════════════════════════════════════════════════════════════════════════
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
    """Execute command via SSH and return stdout."""
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode()
    err = stderr.read().decode()
    if exit_code != 0 and check:
        print(f"  ERROR: {err}")
        raise RuntimeError(f"Command failed: {cmd}")
    return out


def main():
    print(f"=== Upgrading VPS {VPS_HOST} to VPS-optimized config ===")
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=30)
    
    try:
        # 1. Backup current .env
        print("\n[1/5] Backing up current .env...")
        ssh_exec(ssh, f"cp {PROJECT_DIR}/.env {PROJECT_DIR}/.env.backup.$(date +%Y%m%d_%H%M%S)")
        
        # 2. Check if VPS settings already present
        print("\n[2/5] Checking current config...")
        current_env = ssh_exec(ssh, f"cat {PROJECT_DIR}/.env")
        
        if "YTDL_WORKERS=8" in current_env:
            print("  VPS settings already applied!")
        else:
            # 3. Add VPS settings to .env
            print("\n[3/5] Adding VPS-optimized settings...")
            # Use heredoc to append settings
            add_cmd = f"""cat >> {PROJECT_DIR}/.env << 'EOFVPS'
{VPS_SETTINGS}
EOFVPS"""
            ssh_exec(ssh, add_cmd)
            print("  Settings added!")
        
        # 4. Stop and rebuild
        print("\n[4/5] Rebuilding containers with new config...")
        ssh_exec(ssh, f"cd {PROJECT_DIR} && docker compose down")
        ssh_exec(ssh, f"cd {PROJECT_DIR} && docker compose build --no-cache bot")
        
        # 5. Start with new config
        print("\n[5/5] Starting containers...")
        ssh_exec(ssh, f"cd {PROJECT_DIR} && docker compose up -d")
        
        # Wait and check status
        import time
        time.sleep(5)
        status = ssh_exec(ssh, f"cd {PROJECT_DIR} && docker compose ps")
        print("\n=== Container Status ===")
        print(status)
        
        # Show new config values
        print("\n=== VPS Config Applied ===")
        new_env = ssh_exec(ssh, f"grep -E 'YTDL_|HTTP_|DB_|METRICS_' {PROJECT_DIR}/.env")
        print(new_env)
        
        print("\n✅ VPS upgrade complete!")
        print("   • YTDL_WORKERS: 4 → 8")
        print("   • MAX_WORKERS: 16 → 32")
        print("   • HTTP_POOL: default → 100 connections")
        print("   • DB_POOL: NullPool → QueuePool(20+30)")
        print("   • METRICS: disabled → :9090")
        
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
