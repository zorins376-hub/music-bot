from pathlib import Path
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings

# Автоопределение: Docker или локалка
_IN_DOCKER = Path("/.dockerenv").exists()
_BASE = Path("/app") if _IN_DOCKER else Path(__file__).parent.parent


class Settings(BaseSettings):
    # ── Bot ──────────────────────────────────────────────────────────────
    BOT_TOKEN: str

    # ── Database (Supabase PostgreSQL or local SQLite) ──────────────────────
    DATABASE_URL: str = (
        f"sqlite+aiosqlite:///{_BASE / 'data' / 'bot.db'}"
    )

    # ── Redis ─────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0" if _IN_DOCKER else "redis://localhost:6379/0"

    # ── Webhook ───────────────────────────────────────────────────────────
    USE_WEBHOOK: bool = False
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""
    WEBHOOK_PATH: str = "/webhook"
    WEB_SERVER_HOST: str = "0.0.0.0"
    WEB_SERVER_PORT: int = 8080

    # ── Admins ────────────────────────────────────────────────────────────
    ADMIN_IDS: List[int] = []
    ADMIN_USERNAMES: List[str] = ["Tequilasunshine1", "Kg_1988hp"]

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("ADMIN_USERNAMES", mode="before")
    @classmethod
    def parse_admin_usernames(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # ── Audio ─────────────────────────────────────────────────────────────
    DEFAULT_BITRATE: int = 192
    MAX_DURATION: int = 600
    MAX_FILE_SIZE: int = 45 * 1024 * 1024  # 45 MB

    # ── Cache TTL ─────────────────────────────────────────────────────────
    CACHE_FILE_ID_TTL: int = 30 * 24 * 3600   # 30 дней
    SEARCH_SESSION_TTL: int = 300              # 5 минут

    # ── Paths ─────────────────────────────────────────────────────────────
    DOWNLOAD_DIR: Path = _BASE / "downloads"
    DATA_DIR: Path = _BASE / "data"

    # ── Rate limiting ─────────────────────────────────────────────────────
    RATE_LIMIT_REGULAR: int = 10
    RATE_LIMIT_PREMIUM: int = 999999
    COOLDOWN_REGULAR: int = 5
    COOLDOWN_PREMIUM: int = 1

    # ── Pyrogram userbot (v1.1) ───────────────────────────────────────────
    PYROGRAM_API_ID: Optional[int] = None
    PYROGRAM_API_HASH: Optional[str] = None
    PYROGRAM_SESSION_STRING: Optional[str] = None

    # ── Каналы экосистемы (v1.1) ─────────────────────────────────────────
    TEQUILA_CHANNEL: str = ""
    FULLMOON_CHANNEL: str = ""
    BLACKROOM_GROUP_ID: Optional[int] = None

    # ── YouTube cookies (base64-encoded Netscape cookies.txt) ────────────
    YT_COOKIES: Optional[str] = None

    # ── Spotify (v1.2) ────────────────────────────────────────────────────
    SPOTIFY_CLIENT_ID: Optional[str] = None
    SPOTIFY_CLIENT_SECRET: Optional[str] = None

    # ── Premium (Telegram Stars) ─────────────────────────────────────────
    PREMIUM_STAR_PRICE: int = 150  # цена в Stars (~$2-3)
    PREMIUM_DAYS: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

# Write YouTube cookies file from env var if provided
_COOKIES_PATH = settings.DATA_DIR / "cookies.txt"
if settings.YT_COOKIES:
    import base64 as _b64
    _COOKIES_PATH.write_bytes(_b64.b64decode(settings.YT_COOKIES))
