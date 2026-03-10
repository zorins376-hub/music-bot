# 🎧 BLACK ROOM RADIO BOT

Telegram music bot for the **BLACK ROOM** ecosystem — **TEQUILA MUSIC · FULLMOON TRIP SOUND · BLACK ROOM**.

## Features

- **Multi-source search**: YouTube, SoundCloud, Spotify link resolution
- **Priority search**: local channel DB (TEQUILA/FULLMOON) → YouTube → SoundCloud
- **Audio quality**: 128 / 192 / 320 kbps (320 kbps — Premium only)
- **AI DJ**: personalized recommendations based on listening history
- **AUTO MIX**: crossfade mixing with BPM analysis
- **Radio**: TEQUILA LIVE, FULLMOON LIVE streams (requires Pyrogram)
- **Premium**: Telegram Stars payments, 30-day subscriptions
- **Inline mode**: search and share tracks in any chat
- **Natural language**: "включи Drake", "поставь рок", "хочу послушать jazz"
- **i18n**: Russian, English, Kyrgyz
- **Admin panel**: stats, ban/unban, broadcast, radio queue/skip/mode

## Quick Start

```bash
# 1. Clone
git clone https://github.com/zorins376-hub/music-bot.git
cd music-bot

# 2. Configure
cp .env.example .env
# Edit .env — set BOT_TOKEN and ADMIN_IDS at minimum

# 3. Run with Docker
docker-compose up -d

# Or run locally (requires ffmpeg, Redis optional):
pip install -r requirements.txt
# Set REDIS_URL=fakeredis:// in .env for local dev without Redis
python -m bot.main
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome + onboarding |
| `/search <query>` | Search for a track |
| `/top` | Top tracks (today / week / all time) |
| `/history` | Your listening history |
| `/settings` | Audio quality settings |
| `/lang` | Change language |
| `/premium` | Premium subscription info |
| `/recommend` | AI DJ recommendations |
| `/admin` | Admin panel (admin only) |

## Project Structure

```
bot/            — Telegram bot (aiogram 3)
  handlers/     — Command and callback handlers
  models/       — SQLAlchemy models (User, Track, ListeningHistory)
  services/     — Cache (Redis), Downloader (yt-dlp)
  middlewares/  — Throttle, Logging
  i18n/         — Translations (ru/en/kg)
mixer/          — AUTO MIX crossfade engine (pydub)
recommender/    — AI DJ recommendation engine
parser/         — Channel parser (Pyrogram, optional)
streamer/       — Voice Chat streamer (pytgcalls, optional)
```

## Environment Variables

See [.env.example](.env.example) for full list. Required:

- `BOT_TOKEN` — Telegram bot token from @BotFather
- `ADMIN_IDS` — Comma-separated Telegram user IDs

## Tech Stack

- Python 3.12, aiogram 3, SQLAlchemy (async), yt-dlp
- SQLite (dev) / PostgreSQL (prod)
- Redis / fakeredis
- pydub + ffmpeg (audio mixing)
- Docker + docker-compose

## License

Private project — BLACK ROOM ecosystem.

## Operations

- Production migration checklist: [docs/PROD_MIGRATION_RUNBOOK.md](docs/PROD_MIGRATION_RUNBOOK.md)
- Quick deploy checklist: [docs/PROD_DEPLOY_CHECKLIST.md](docs/PROD_DEPLOY_CHECKLIST.md)
- DB smoke SQL: [docs/PROD_DB_SMOKE.sql](docs/PROD_DB_SMOKE.sql)
- DB assert SQL (fail-fast): [docs/PROD_DB_ASSERT.sql](docs/PROD_DB_ASSERT.sql)
- Make shortcut: `make prod-db-backup-and-assert`
- Verify report template: [docs/PROD_VERIFY_REPORT_TEMPLATE.md](docs/PROD_VERIFY_REPORT_TEMPLATE.md)
- PowerShell verify script: [scripts/prod_verify.ps1](scripts/prod_verify.ps1)
- Windows launcher: [scripts/prod_verify.cmd](scripts/prod_verify.cmd)
- Verify quick commands: [scripts/prod_verify_help.txt](scripts/prod_verify_help.txt)
- Unified ops quick help: [scripts/ops_help.txt](scripts/ops_help.txt)
- Cleanup script: [scripts/cleanup_reports.ps1](scripts/cleanup_reports.ps1)
- Cleanup launcher (Windows): [scripts/cleanup_reports.cmd](scripts/cleanup_reports.cmd)
- Unified ops launcher (Windows): [scripts/ops.cmd](scripts/ops.cmd)
- Unified ops launcher (PowerShell): [scripts/ops.ps1](scripts/ops.ps1)
- Scripts smoke launcher (Windows): [scripts/smoke_scripts.cmd](scripts/smoke_scripts.cmd)
- Ops status launcher (Windows): [scripts/status.cmd](scripts/status.cmd)
- Ops status launcher (PowerShell): [scripts/status.ps1](scripts/status.ps1)
- Verify reports output: [docs/reports](docs/reports)
- Verify command example: `make prod-verify-report COMMIT=release-2026-03-10 OPERATOR=devops`
- Fast mode (no backup): `make prod-verify-report-no-backup COMMIT=hotfix OPERATOR=oncall`
- Dry-run mode (no DB calls): `make prod-verify-report-dry-run COMMIT=preview OPERATOR=oncall`
- Rotation mode: `make prod-verify-report-rotate KEEP=30 COMMIT=release-2026-03-10 OPERATOR=devops`
- If `COMMIT` is omitted, verifier auto-detects current git short SHA.
- If `OPERATOR` is omitted, verifier auto-detects from `USERNAME`/`USER` env.
- If `make` is unavailable, verifier falls back to direct `pg_dump/psql` execution.
- Direct fallback example: `pwsh -File scripts/prod_verify.ps1 -DryRun -NoBackup -Commit preview -Operator oncall`
- Direct rotation example: `pwsh -File scripts/prod_verify.ps1 -RotateArtifacts -KeepArtifacts 30 -Commit release -Operator devops`
- Standalone cleanup: `make cleanup-reports KEEP=30` / `make cleanup-reports-dry-run KEEP=30`
- CMD cleanup example: `scripts\cleanup_reports.cmd -KeepArtifacts 30 -DryRun`
- Unified launcher examples: `scripts\ops.cmd verify -DryRun -NoBackup -Commit preview -Operator oncall` / `scripts\ops.cmd cleanup -KeepArtifacts 30 -DryRun`
- PowerShell launcher examples: `pwsh -File scripts/ops.ps1 verify -DryRun -NoBackup -Commit preview -Operator oncall` / `pwsh -File scripts/ops.ps1 cleanup -KeepArtifacts 30 -DryRun`
- Scripts smoke-check: `pwsh -File scripts/smoke_scripts.ps1` (or `make scripts-smoke`) — includes `ops status` route checks
- CMD smoke-check: `scripts\smoke_scripts.cmd`
- CMD launcher example: `scripts\prod_verify.cmd -DryRun -NoBackup -Commit preview -Operator oncall`
- Status snapshot: `scripts\status.cmd` / `pwsh -File scripts/status.ps1`
- Unified status: `scripts\ops.cmd status` / `pwsh -File scripts/ops.ps1 status`
- Unified smoke: `scripts\ops.cmd smoke` / `pwsh -File scripts/ops.ps1 smoke`
- Unified report: `scripts\ops.cmd report -Commit release-2026-03-10 -Operator devops` / `pwsh -File scripts/ops.ps1 report -Commit release-2026-03-10 -Operator devops`
- Make report shortcut: `make prod-new-report COMMIT=release-2026-03-10 OPERATOR=devops`
