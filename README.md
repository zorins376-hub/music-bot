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
