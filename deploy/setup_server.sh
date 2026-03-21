#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════
# Music Bot — Server Setup Script
# Run on a fresh Ubuntu 24.04 VPS as root
# ═══════════════════════════════════════════════════════════════════════════

echo "=== [1/6] Updating system ==="
apt-get update && apt-get upgrade -y

echo "=== [2/6] Installing Docker ==="
# Install Docker using official convenience script
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    echo "Docker already installed"
fi

# Install Docker Compose plugin
if ! docker compose version &>/dev/null; then
    apt-get install -y docker-compose-plugin
else
    echo "Docker Compose already installed"
fi

echo "=== [3/6] Installing basic tools ==="
apt-get install -y git curl htop

echo "=== [4/6] Cloning repository ==="
REPO_DIR="/opt/music-bot"
if [ -d "$REPO_DIR" ]; then
    echo "Directory exists, pulling latest..."
    cd "$REPO_DIR"
    git pull
else
    git clone https://github.com/zorins376-hub/music-bot.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

echo "=== [5/6] Creating .env file ==="
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/deploy/.env.production.local" "$REPO_DIR/.env" 2>/dev/null || cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo "Created .env from local template/fallback — EDIT IT with your tokens!"
else
    echo ".env already exists, skipping"
fi

echo "=== [6/6] Building and starting containers ==="
cd "$REPO_DIR"
docker compose up -d --build

echo ""
echo "=== DONE ==="
echo "Check status: docker compose ps"
echo "Check logs:   docker compose logs -f bot"
echo "Edit config:  nano /opt/music-bot/.env"
echo ""
docker compose ps
