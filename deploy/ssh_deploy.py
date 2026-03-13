"""SSH deploy script — connects to VPS and sets up the music bot."""
import paramiko
import sys
import time
import os

HOST = "89.169.52.174"
USER = "root"
PASS = "YjfWW9v6j2m5"
REPO = "https://github.com/zorins376-hub/music-bot.git"
BOT_TOKEN = "8561612277:AAHV80B9gjdwDY7MuQjZZnzAm7aNbQsM8Js"

SETUP_SCRIPT = r"""#!/bin/bash
set -euo pipefail

echo "=== [0/6] Waiting for dpkg lock (unattended-upgrades) ==="
# Wait for any running apt/dpkg processes to finish (up to 5 minutes)
for i in $(seq 1 60); do
    if fuser /var/lib/dpkg/lock-frontend &>/dev/null; then
        echo "  dpkg locked by another process, waiting... ($i/60)"
        sleep 5
    else
        echo "  dpkg lock is free"
        break
    fi
done
# Kill unattended-upgrades if still running
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
REPO_DIR="/opt/music-bot"
if [ -d "$REPO_DIR/.git" ]; then
    echo "Repo exists, pulling latest..."
    cd "$REPO_DIR"
    git pull
else
    rm -rf "$REPO_DIR"
    git clone REPO_PLACEHOLDER "$REPO_DIR"
    cd "$REPO_DIR"
fi

echo "=== [5/6] Creating .env ==="
cat > "$REPO_DIR/.env" << 'ENVEOF'
BOT_TOKEN=TOKEN_PLACEHOLDER

DATABASE_URL=postgresql+asyncpg://musicbot:changeme@postgres:5432/musicbot
POSTGRES_DB=musicbot
POSTGRES_USER=musicbot
POSTGRES_PASSWORD=changeme

REDIS_URL=redis://redis:6379/0

USE_WEBHOOK=false
WEB_SERVER_HOST=0.0.0.0
WEB_SERVER_PORT=8080

ADMIN_USERNAMES=["Tequilasunshine1","Kg_1988hp"]

DEFAULT_BITRATE=192
MAX_DURATION=600

SUPABASE_AI_ENABLED=false
ENVEOF

echo ".env created ($(wc -l < $REPO_DIR/.env) lines)"

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
""".replace("REPO_PLACEHOLDER", REPO).replace("TOKEN_PLACEHOLDER", BOT_TOKEN)


def main():
    print(f"Connecting to {HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30)
    print("Connected!\n")

    # Upload setup script
    print("Uploading setup script...")
    sftp = client.open_sftp()
    with sftp.open("/tmp/setup_musicbot.sh", "w") as f:
        f.write(SETUP_SCRIPT)
    sftp.close()
    print("Script uploaded.\n")

    # Execute the script with a long-running channel
    print("Executing setup script (this may take several minutes)...")
    print("=" * 60)
    
    chan = client.get_transport().open_session()
    chan.settimeout(None)  # no timeout
    chan.exec_command("bash /tmp/setup_musicbot.sh 2>&1")
    
    # Stream output in real-time
    while True:
        if chan.recv_ready():
            data = chan.recv(4096).decode(errors='replace')
            print(data, end='', flush=True)
        elif chan.exit_status_ready():
            # Read remaining data
            while chan.recv_ready():
                data = chan.recv(4096).decode(errors='replace')
                print(data, end='', flush=True)
            break
        else:
            time.sleep(0.5)
    
    exit_code = chan.recv_exit_status()
    print(f"\nScript exit code: {exit_code}")
    
    client.close()
    print("\n✓ Deployment complete!" if exit_code == 0 else "\n✗ Deployment failed!")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
