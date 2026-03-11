#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# Deploy music-bot crawler on a fresh Debian/Ubuntu VPS
#
# Usage:
#   1. SSH into your VPS:  ssh root@YOUR_IP
#   2. Upload this script: scp deploy_crawler.sh root@YOUR_IP:~
#   3. Run:                bash deploy_crawler.sh
#
# OR one-liner (replace YOUR_REPO with your GitHub repo URL):
#   curl -sSL https://raw.githubusercontent.com/YOUR_USER/music-bot/main/deploy_crawler.sh | bash
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

APP_DIR="/opt/music-bot-crawler"
SERVICE_NAME="music-crawler"
REPO_URL="https://github.com/zorins376-hub/music-bot.git"

echo "═══ Music Bot Deep Crawler — VPS Deploy ═══"

# ── 1. System packages ──
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git > /dev/null

# ── 2. Clone / update repo ──
echo "[2/6] Cloning repository..."
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    git pull --ff-only
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 3. Python venv + deps ──
echo "[3/6] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.crawler.txt

# ── 4. Create .env if not exists ──
if [ ! -f "$APP_DIR/.env" ]; then
    echo "[4/6] Creating .env template..."
    cat > "$APP_DIR/.env" << 'ENVEOF'
# ═══ Crawler Environment ═══
# Copy these from your Railway / main bot .env

# Database (Supabase PostgreSQL — same connection string as bot)
DATABASE_URL=postgresql+psycopg://user:password@db.xxx.supabase.co:6543/postgres?sslmode=require

# Redis (if shared with bot; otherwise leave empty for in-memory queue)
REDIS_URL=redis://localhost:6379/0

# Yandex Music
YANDEX_MUSIC_TOKEN=your_token_here

# Spotify
SPOTIFY_CLIENT_ID=your_id_here
SPOTIFY_CLIENT_SECRET=your_secret_here

# Bot token (needed for config loading, crawler won't use Telegram API)
BOT_TOKEN=dummy
ENVEOF
    echo ""
    echo "  ⚠️  IMPORTANT: Edit /opt/music-bot-crawler/.env with your real credentials!"
    echo "     nano $APP_DIR/.env"
    echo ""
else
    echo "[4/6] .env already exists, keeping it."
fi

# ── 5. Create systemd service ──
echo "[5/6] Creating systemd service..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << SVCEOF
[Unit]
Description=Music Bot Deep Crawler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/python -m crawler
Restart=always
RestartSec=30

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# Resource limits (crawler is lightweight)
MemoryMax=512M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}

# ── 6. Done ──
echo "[6/6] Done!"
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Crawler installed at: $APP_DIR"
echo ""
echo "  Next steps:"
echo "    1. Edit .env:          nano $APP_DIR/.env"
echo "    2. Start crawler:      systemctl start $SERVICE_NAME"
echo "    3. Check logs:         journalctl -u $SERVICE_NAME -f"
echo "    4. Check status:       systemctl status $SERVICE_NAME"
echo ""
echo "  Quick commands:"
echo "    Single cycle:  cd $APP_DIR && venv/bin/python -m crawler --once"
echo "    Show stats:    cd $APP_DIR && venv/bin/python -m crawler --stats"
echo "    Stop:          systemctl stop $SERVICE_NAME"
echo "    Restart:       systemctl restart $SERVICE_NAME"
echo "    Update code:   cd $APP_DIR && git pull && systemctl restart $SERVICE_NAME"
echo "═══════════════════════════════════════════════════════"
