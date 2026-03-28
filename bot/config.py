from pathlib import Path
from typing import List, Optional

from pydantic import field_validator, model_validator
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
    REDIS_MAX_OPS_PER_SEC: int = 0  # 0 = disabled
    REDIS_BURST: int = 50

    # ── Webhook ───────────────────────────────────────────────────────────
    USE_WEBHOOK: bool = False
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""
    WEBHOOK_PATH: str = "/webhook"
    WEB_SERVER_HOST: str = "0.0.0.0"
    WEB_SERVER_PORT: int = 8080
    WEBAPP_CORS_ORIGINS: List[str] = []

    # ── Admins ────────────────────────────────────────────────────────────
    ADMIN_IDS: List[int] = []
    ADMIN_USERNAMES: List[str] = []

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

    @model_validator(mode="after")
    def validate_required_runtime_settings(self):
        if not self.BOT_TOKEN or not self.BOT_TOKEN.strip():
            raise ValueError("BOT_TOKEN is required and cannot be empty")
        if not self.ADMIN_IDS and not self.ADMIN_USERNAMES:
            import warnings
            warnings.warn("No ADMIN_IDS or ADMIN_USERNAMES configured; admin commands will be unavailable until loaded from Redis")
        return self

    @field_validator("WEBAPP_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_webapp_cors_origins(cls, v):
        if isinstance(v, str):
            return [x.strip().rstrip("/") for x in v.split(",") if x.strip()]
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

    # ── Thread pool (VPS-optimized: increase for dedicated servers) ─────
    YTDL_WORKERS: int = 8  # Railway: 4, VPS: 8-12
    YTDL_MAX_WORKERS_MULTIPLIER: int = 4  # MAX_WORKERS = YTDL_WORKERS * this
    YTDL_CONCURRENT_FRAGMENTS: int = 8  # parallel fragment downloads per track

    # ── Pyrogram userbot (v1.1) ───────────────────────────────────────────
    PYROGRAM_API_ID: Optional[int] = None
    PYROGRAM_API_HASH: Optional[str] = None
    PYROGRAM_SESSION_STRING: Optional[str] = None

    # ── Каналы экосистемы (v1.1) ─────────────────────────────────────────
    TEQUILA_CHANNEL: str = ""
    FULLMOON_CHANNEL: str = ""
    BLACKROOM_GROUP_ID: Optional[str] = None  # single ID or comma-separated list

    # ── YouTube cookies (base64-encoded Netscape cookies.txt) ────────────
    YT_COOKIES: Optional[str] = None

    # ── Spotify (v1.2) ────────────────────────────────────────────────────
    SPOTIFY_CLIENT_ID: Optional[str] = None
    SPOTIFY_CLIENT_SECRET: Optional[str] = None

    # ── Yandex Music ──────────────────────────────────────────────────────
    YANDEX_MUSIC_TOKEN: Optional[str] = None
    YANDEX_TOKENS: Optional[str] = None  # пул токенов через запятую (ротация)
    YANDEX_TOKEN_EXPIRES_AT: Optional[str] = None  # single token expiry (unix ts / ISO8601)
    YANDEX_TOKENS_EXPIRES_AT: Optional[str] = None  # comma-separated expiries aligned with YANDEX_TOKENS
    YANDEX_ALERT_TELEGRAM: bool = True
    CHART_YANDEX_ENABLED: bool = True  # False to skip Yandex chart (geo-blocked IPs)
    # ── VK Music ───────────────────────────────────────────────────────────────
    VK_TOKEN: Optional[str] = None       # Kate Mobile / VK Android token
    VK_LOGIN: Optional[str] = None
    VK_PASSWORD: Optional[str] = None

    # ── Deezer ────────────────────────────────────────────────────────────────
    DEEZER_ARL: Optional[str] = None     # browser cookie from deezer.com

    # ── OpenAI (Prompt-to-Playlist) ──────────────────────────────────────
    OPENAI_API_KEY: Optional[str] = None

    # ── Analytics export ───────────────────────────────────────────────────
    ANALYTICS_EXPORT_URL: Optional[str] = None
    ANALYTICS_EXPORT_TOKEN: Optional[str] = None
    ANALYTICS_EXPORT_TIMEOUT_SEC: float = 2.0

    # ── Proxy pool ────────────────────────────────────────────────────────
    PROXY_POOL: Optional[str] = None  # comma-separated: socks5://ip:port,http://ip:port

    # ── Sentry ───────────────────────────────────────────────────────────────
    SENTRY_DSN: Optional[str] = None

    # ── Genius (lyrics) ──────────────────────────────────────────────────
    GENIUS_TOKEN: Optional[str] = None

    # ── Last.fm (recommendations / similar tracks) ────────────────────────
    LASTFM_API_KEY: Optional[str] = None

    # ── Prometheus metrics ────────────────────────────────────────────
    METRICS_PORT: int = 9090  # VPS: enabled (0 = disabled)

    # ── HTTP Connection tuning (VPS-optimized for high load) ─────────
    HTTP_POOL_CONNECTIONS: int = 200  # TCP connection pool size
    HTTP_POOL_KEEPALIVE: int = 30  # keepalive timeout seconds
    HTTP_CONNECT_TIMEOUT: int = 10  # connection timeout
    HTTP_READ_TIMEOUT: int = 60  # read timeout for downloads

    # ── Database tuning (VPS-optimized for high load) ──────────────────
    DB_POOL_SIZE: int = 50  # SQLAlchemy pool size (local PG only)
    DB_MAX_OVERFLOW: int = 50  # additional connections above pool_size
    DB_POOL_TIMEOUT: int = 30  # wait for connection
    DB_COMMAND_TIMEOUT: int = 30  # query timeout
    DB_CONNECT_TIMEOUT: int = 60  # connection timeout

    # ── Premium (Telegram Stars) ─────────────────────────────────────────
    PREMIUM_STAR_PRICE: int = 150  # цена в Stars (~$2-3)
    PREMIUM_DAYS: int = 30

    # ── TMA Player (1.1) ─────────────────────────────────────────────────
    TMA_URL: Optional[str] = None  # e.g. https://example.com/tma/

    # ── ML Recommendations (local — disabled when Supabase AI is active) ────
    ML_ENABLED: bool = False                     # Master switch: ML on/off
    ML_AB_TEST_ENABLED: bool = False             # A/B test mode
    ML_MODEL_DIR: Path = _BASE / "data" / "models"
    ML_RETRAIN_HOUR: int = 4                     # UTC hour for nightly training
    ML_MIN_INTERACTIONS: int = 100               # Minimum interactions to train
    ML_MIN_USERS: int = 10                       # Minimum users to train ALS
    ML_ALS_FACTORS: int = 64                     # ALS embedding dimension
    ML_ALS_ITERATIONS: int = 15                  # ALS training iterations
    ML_ALS_REGULARIZATION: float = 0.01
    ML_W2V_VECTOR_SIZE: int = 64                 # Word2Vec embedding dimension
    ML_W2V_WINDOW: int = 5
    ML_W2V_EPOCHS: int = 10
    ML_SESSION_GAP_MINUTES: int = 30             # Gap between sessions
    ML_SCORER_W_ALS: float = 0.40                # ALS weight in hybrid scorer
    ML_SCORER_W_EMB: float = 0.25                # Embedding weight
    ML_SCORER_W_POP: float = 0.15                # Popularity weight
    ML_SCORER_W_FRESH: float = 0.10              # Freshness weight
    ML_SCORER_W_TIME: float = 0.10               # Time-of-day weight
    ML_MAX_PER_ARTIST: int = 2                   # Diversity: max tracks per artist
    ML_MAX_PER_GENRE: int = 3                    # Diversity: max tracks per genre
    ML_COLD_START_THRESHOLD: int = 5             # Min plays for ML (vs pure content-based)
    ML_RECO_CACHE_TTL: int = 3600                # ML reco cache TTL (seconds)

    # ── Supabase AI Service (primary recommendation + DB backend) ──────────
    SUPABASE_URL: Optional[str] = None           # e.g. https://xxxx.supabase.co
    SUPABASE_SERVICE_KEY: Optional[str] = None   # service_role key (NOT anon)
    SUPABASE_AI_ENABLED: bool = True             # Master switch: use Supabase AI (disables local ML)

    # ── Bot Fleet / Sharding (5.2) ────────────────────────────────────────
    NODE_ID: Optional[str] = None  # e.g. "node-1"
    DISPATCHER_TOKEN: Optional[str] = None
    NODE_TOKENS: Optional[str] = None  # comma-separated bot tokens for nodes

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
config = settings

settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

# Write YouTube cookies file from env var if provided
_COOKIES_PATH = settings.DATA_DIR / "cookies.txt"
if settings.YT_COOKIES:
    import base64 as _b64
    _COOKIES_PATH.write_bytes(_b64.b64decode(settings.YT_COOKIES))
