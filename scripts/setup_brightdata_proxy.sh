#!/usr/bin/env bash
# Configure Bright Data residential proxy on the music-bot VPS .env (YOUTUBE_PROXY).
# Does not create zones — paste the ONE line from Bright Data CP → Access Parameters.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ENV="${ROOT}/deploy/.env"
PROJECT_DIR="${DEPLOY_PROJECT_DIR:-/root/music-bot}"

if [[ -f "${DEPLOY_ENV}" ]]; then
  # shellcheck disable=SC1090
  set -a
  source <(grep -E '^DEPLOY_' "${DEPLOY_ENV}" | sed 's/\r$//')
  set +a
fi

: "${DEPLOY_SSH_HOST:?Set DEPLOY_SSH_HOST in deploy/.env}"
DEPLOY_SSH_USER="${DEPLOY_SSH_USER:-root}"

PROXY_URL="${BRIGHTDATA_PROXY_URL:-${YOUTUBE_PROXY:-}}"
if [[ -z "${PROXY_URL}" ]]; then
  echo "Paste Bright Data Access Parameters as ONE URL (host:port + user + password):"
  echo "  http://brd-customer-XXXX-zone-residential:PASSWORD@brd.superproxy.io:22225"
  read -r -p "YOUTUBE_PROXY URL: " PROXY_URL
fi

if [[ -z "${PROXY_URL}" ]]; then
  echo "Aborted: empty proxy URL." >&2
  exit 1
fi
if [[ "${PROXY_URL}" == *"35886d65-6602-4269-9366-b07393b47f7b"* ]]; then
  echo "Error: that UUID is a zone/customer id, not proxy auth. Use Access Parameters username+password." >&2
  exit 1
fi

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${DEPLOY_SSH_KEY_PATH:-}" ]]; then
  SSH_OPTS+=(-i "${DEPLOY_SSH_KEY_PATH}")
fi

REMOTE="${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}"
# Escape for remote sed
ESCAPED="$(printf '%s' "${PROXY_URL}" | sed 's/[&/\]/\\&/g')"

ssh "${SSH_OPTS[@]}" "${REMOTE}" bash -s <<EOF
set -euo pipefail
cd "${PROJECT_DIR}"
cp -a .env ".env.backup.\$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
grep -q '^YOUTUBE_PROXY=' .env 2>/dev/null && sed -i '/^YOUTUBE_PROXY=/d' .env || true
echo "YOUTUBE_PROXY=${PROXY_URL}" >> .env
grep -q '^BGUTIL_POT_BASE_URL=' .env || echo 'BGUTIL_POT_BASE_URL=http://bgutil-provider:4416' >> .env
docker compose up -d
echo "YOUTUBE_PROXY written. Restarting stack..."
EOF

echo "Done. Run: python deploy/_run_yt_probe.py"
