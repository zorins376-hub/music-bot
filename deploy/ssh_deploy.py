"""SSH deploy script — connects to VPS and sets up the music bot."""
import os
import sys
import time

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_common import connect_ssh, get_ssh_config

REPO = os.environ.get(
    "DEPLOY_REPO_URL",
    "https://github.com/zorins376-hub/music-bot.git",
).strip()

SETUP_SCRIPT = r"""#!/bin/bash
set -euo pipefail

echo "=== [0/6] Waiting for dpkg lock (unattended-upgrades) ==="
for i in $(seq 1 60); do
    if fuser /var/lib/dpkg/lock-frontend &>/dev/null; then
        echo "  dpkg locked by another process, waiting... ($i/60)"
        sleep 5
    else
        echo "  dpkg lock is free"
        break
    fi
done
systemctl stop unattended-upgrades 2>/dev/null || true
killall -9 unattended-upgrades 2>/dev/null || true
sleep 2

echo "=== [1/6] Updating package index ==="
apt-get update -qq

echo "=== [2/6] Installing Docker ==="
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    echo "Docker already installed"
fi
docker --version
docker compose version 2>/dev/null || apt-get install -y docker-compose-plugin

echo "=== [3/6] Installing tools ==="
apt-get install -y -qq git curl htop

echo "=== [4/6] Cloning repository ==="
REPO_DIR="/root/music-bot"
if [ -d "$REPO_DIR/.git" ]; then
    echo "Repo exists, pulling latest..."
    cd "$REPO_DIR"
    git pull
else
    rm -rf "$REPO_DIR"
    git clone REPO_PLACEHOLDER "$REPO_DIR"
    cd "$REPO_DIR"
fi

echo "=== [5/6] Creating .env skeleton ==="
if [ ! -f "$REPO_DIR/.env" ]; then
cat > "$REPO_DIR/.env" << 'ENVEOF'
# Fill BOT_TOKEN and POSTGRES_PASSWORD before going live
BOT_TOKEN=

DATABASE_URL=postgresql+asyncpg://musicbot:changeme@postgres:5432/musicbot
POSTGRES_DB=musicbot
POSTGRES_USER=musicbot
POSTGRES_PASSWORD=changeme

REDIS_URL=redis://redis:6379/0

USE_WEBHOOK=false
WEB_SERVER_HOST=0.0.0.0
WEB_SERVER_PORT=8080

ADMIN_USERNAMES=

DEFAULT_BITRATE=192
MAX_DURATION=600

SUPABASE_AI_ENABLED=false
ENVEOF
echo ".env created ($(wc -l < $REPO_DIR/.env) lines)"
echo ">>> Edit $REPO_DIR/.env and set BOT_TOKEN + POSTGRES_PASSWORD"
else
echo ".env already exists — preserving it (skeleton not written)"
fi

echo "=== [6/6] Building and starting containers ==="
cd "$REPO_DIR"
docker compose up -d --build 2>&1 | tail -30

echo ""
echo "=== DEPLOYMENT STATUS ==="
sleep 3
docker compose ps
echo ""
echo "=== BOT LOGS (last 20 lines) ==="
docker compose logs --tail=20 bot 2>&1 || true
echo ""
echo "=== DONE ==="
""".replace("REPO_PLACEHOLDER", REPO)


def main():
    host, _, _, _ = get_ssh_config()
    print(f"Connecting to {host}...")
    client = connect_ssh(timeout=30)
    print("Connected!\n")

    print("Uploading setup script...")
    sftp = client.open_sftp()
    with sftp.open("/tmp/setup_musicbot.sh", "w") as f:
        f.write(SETUP_SCRIPT)
    sftp.close()
    print("Script uploaded.\n")

    print("Executing setup script (this may take several minutes)...")
    print("=" * 60)

    chan = client.get_transport().open_session()
    chan.settimeout(None)
    chan.exec_command("bash /tmp/setup_musicbot.sh 2>&1")

    while True:
        if chan.recv_ready():
            data = chan.recv(4096).decode(errors="replace")
            print(data, end="", flush=True)
        elif chan.exit_status_ready():
            while chan.recv_ready():
                data = chan.recv(4096).decode(errors="replace")
                print(data, end="", flush=True)
            break
        else:
            time.sleep(0.5)

    exit_code = chan.recv_exit_status()
    print(f"\nScript exit code: {exit_code}")

    client.close()
    print("\n✓ Deployment complete!" if exit_code == 0 else "\n✗ Deployment failed!")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
