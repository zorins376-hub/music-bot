#!/usr/bin/env python3
"""BlackBox Video — Telegram bot that downloads videos from any URL.
v4.0: queue, cache, limits, admin panel (broadcast/ban/users)
"""

import re
import asyncio
import logging
import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

TOKEN = "7778709205:AAGfUz2Cj5AWRGv2hsiy-ItpNqtw5xuWCXI"
ADMIN_IDS = {8558910353, 8258955906}
DOWNLOAD_DIR = Path("/tmp/blackbox_downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
MAX_TG_SIZE = 49 * 1024 * 1024
DB_PATH = Path("/root/blackbox-video/history.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("blackbox")

URL_RE = re.compile(r"https?://[^\s<>\"'\)]+")

# ── State ──
_cancel_flags: dict[int, asyncio.Event] = {}
_active_procs: dict[int, asyncio.subprocess.Process] = {}

# Queue: max 3 concurrent downloads
MAX_CONCURRENT = 3
_download_semaphore: asyncio.Semaphore | None = None

# Cache: url → file_id (video/audio) — TTL 24h
_file_cache: dict[str, tuple[str, str, float]] = {}  # cache_key → (file_id, type, timestamp)
CACHE_TTL = 86400  # 24h

# Limits
DAILY_LIMIT_FREE = 20


FORMAT_LADDER = [
    ("480p", "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]"),
    ("360p", "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]"),
    ("240p", "bestvideo[height<=240][ext=mp4]+bestaudio[ext=m4a]/best[height<=240][ext=mp4]/best[height<=240]"),
    ("worst", "worstvideo+worstaudio/worst"),
]

AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio"

REDIRECT_DOMAINS = {
    "t.co", "bit.ly", "tinyurl.com", "goo.gl",
    "rb.gy", "ow.ly", "is.gd", "v.gd", "cutt.ly", "shorturl.at",
    "vm.tiktok.com", "vt.tiktok.com",
}
UNSUPPORTED_SHORTENERS = {"share.google"}

LOGO_FILE_ID = None
LOGO_PATH = Path("/root/blackbox-video/logo.jpg")

START_TEXT = """
<b>BLACK BOX</b>  ·  <i>video bot</i>

━━━━━━━━━━━━━━━━━━━

<b>🎬 Любое видео. Одна ссылка. Без лишнего.</b>

Мы верим, что контент должен быть свободным.
Никаких регистраций. Никакой рекламы. Никаких ограничений.
Просто отправь ссылку — получи видео.

━━━━━━━━━━━━━━━━━━━

<b>⚡ Возможности:</b>

▸ <b>1000+ сайтов</b> — YouTube, TikTok, Instagram, VK, X, Reddit и другие
▸ <b>🎵 Аудио-режим</b> — извлекай музыку из любого видео
▸ <b>Авто-подбор качества</b> — максимум, что влезет в Telegram
▸ <b>Прогресс в реальном времени</b> — видишь каждый процент
▸ <b>📜 История</b> — все скачивания под рукой

━━━━━━━━━━━━━━━━━━━

<b>📖 Как пользоваться:</b>

Отправь ссылку → выбери 🎬 Видео или 🎵 Аудио
Всё остальное — наша работа.

━━━━━━━━━━━━━━━━━━━

<i>Black Box — скачивай. Смотри. Делись.</i>
"""


# ══════════════════════════════════════
# DB — history & stats
# ══════════════════════════════════════

def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, title TEXT,
        url TEXT, quality TEXT, size INTEGER,
        source TEXT, created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT, first_name TEXT,
        first_seen TEXT DEFAULT (datetime('now')),
        download_count INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        bot_blocked INTEGER DEFAULT 0
    )""")
    # Migrate: add columns if missing
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN bot_blocked INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    return conn


def _save_download(user_id: int, username: str, title: str, url: str, quality: str, size: int):
    try:
        host = urlparse(url).hostname or "unknown"
        host = host.replace("www.", "").replace("m.", "")
        conn = _db()
        conn.execute(
            "INSERT INTO downloads (user_id, username, title, url, quality, size, source) VALUES (?,?,?,?,?,?,?)",
            (user_id, username, title, url, quality, size, host),
        )
        conn.execute("""INSERT INTO users (user_id, username, first_name, download_count)
            VALUES (?, ?, ?, 1) ON CONFLICT(user_id)
            DO UPDATE SET download_count = download_count + 1, username = excluded.username""",
            (user_id, username, username),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("DB save error: %s", e)


def _get_history(user_id: int, limit: int = 10) -> list:
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT title, url, quality, size, source, created_at FROM downloads WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _ensure_user(user_id: int, username: str, first_name: str = ""):
    try:
        conn = _db()
        conn.execute("""INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?) ON CONFLICT(user_id)
            DO UPDATE SET username = excluded.username, first_name = excluded.first_name""",
            (user_id, username, first_name),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _is_banned(user_id: int) -> bool:
    try:
        conn = _db()
        row = conn.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception:
        return False


def _set_banned(user_id: int, banned: bool):
    try:
        conn = _db()
        conn.execute("UPDATE users SET is_banned=? WHERE user_id=?", (int(banned), user_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _set_bot_blocked(user_id: int, blocked: bool):
    try:
        conn = _db()
        conn.execute("UPDATE users SET bot_blocked=? WHERE user_id=?", (int(blocked), user_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _get_today_count(user_id: int) -> int:
    try:
        conn = _db()
        row = conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE user_id=? AND date(created_at)=date('now')", (user_id,)
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def _get_all_users(page: int = 0, per_page: int = 20) -> tuple[list, int]:
    try:
        conn = _db()
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        rows = conn.execute(
            "SELECT user_id, username, first_name, download_count, is_banned, bot_blocked FROM users ORDER BY download_count DESC LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        ).fetchall()
        conn.close()
        return rows, total
    except Exception:
        return [], 0


def _get_broadcast_users() -> list[int]:
    """Get user IDs that are not banned and not blocked."""
    try:
        conn = _db()
        rows = conn.execute("SELECT user_id FROM users WHERE is_banned=0 AND bot_blocked=0").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _cache_key(url: str, mode: str) -> str:
    from hashlib import md5
    return md5(f"{url}:{mode}".encode()).hexdigest()[:16]


def _cache_get(url: str, mode: str) -> str | None:
    key = _cache_key(url, mode)
    entry = _file_cache.get(key)
    if entry and time.time() - entry[2] < CACHE_TTL:
        return entry[0]  # file_id
    if entry:
        _file_cache.pop(key, None)
    return None


def _cache_set(url: str, mode: str, file_id: str):
    key = _cache_key(url, mode)
    _file_cache[key] = (file_id, mode, time.time())
    # Evict old entries
    if len(_file_cache) > 500:
        oldest = sorted(_file_cache, key=lambda k: _file_cache[k][2])
        for k in oldest[:100]:
            _file_cache.pop(k, None)


def _get_stats() -> dict:
    try:
        conn = _db()
        total_dl = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        today_dl = conn.execute("SELECT COUNT(*) FROM downloads WHERE date(created_at)=date('now')").fetchone()[0]
        top_sources = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM downloads GROUP BY source ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        top_users = conn.execute(
            "SELECT username, download_count FROM users ORDER BY download_count DESC LIMIT 5"
        ).fetchall()
        total_size = conn.execute("SELECT COALESCE(SUM(size),0) FROM downloads").fetchone()[0]
        banned = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
        blocked = conn.execute("SELECT COUNT(*) FROM users WHERE bot_blocked=1").fetchone()[0]
        conn.close()
        return {
            "total_dl": total_dl, "total_users": total_users,
            "today_dl": today_dl, "top_sources": top_sources,
            "top_users": top_users, "total_size": total_size,
            "banned": banned, "blocked": blocked,
        }
    except Exception:
        return {}


# ══════════════════════════════════════
# Helpers
# ══════════════════════════════════════

def _progress_bar(pct: float, width: int = 15) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def _size_fmt(size_bytes: int) -> str:
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} КБ"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} МБ"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} ГБ"


def _eta_fmt(seconds: float) -> str:
    if seconds < 0 or seconds > 36000:
        return "..."
    m, s = divmod(int(seconds), 60)
    return f"{m}м {s}с" if m > 0 else f"{s}с"


def _dur_fmt(seconds) -> str:
    try:
        s = int(float(seconds))
    except (ValueError, TypeError):
        return "?"
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _cancel_kb(msg_id: int):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отменить", callback_data=f"cancel:{msg_id}")]])


def _is_cancelled(msg_id: int) -> bool:
    evt = _cancel_flags.get(msg_id)
    return evt is not None and evt.is_set()


async def _edit_progress(bot, chat_id: int, msg_id: int, stage: str, pct: float, extra: str = "", last_text: dict = None):
    icons = {"download": "⬇️", "upload": "📤"}
    names = {"download": "Скачиваю", "upload": "Отправляю"}
    icon = icons.get(stage, "⏳")
    bar = _progress_bar(pct)
    text = f"{icon} <b>{names.get(stage, stage)}</b>\n\n{bar}  {pct:.0f}%\n{extra}"
    if last_text and last_text.get("t") == text:
        return
    if last_text is not None:
        last_text["t"] = text
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=msg_id,
            parse_mode="HTML", reply_markup=_cancel_kb(msg_id),
        )
    except Exception:
        pass


# ══════════════════════════════════════
# URL utils
# ══════════════════════════════════════

async def resolve_redirects(url: str) -> str:
    import aiohttp
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                final = str(resp.url)
                if final != url:
                    log.info("Resolved redirect: %s -> %s", url, final)
                return final
    except Exception:
        pass
    return url


def _needs_redirect(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith("." + d) for d in REDIRECT_DOMAINS)
    except Exception:
        return False


def _is_unsupported(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith("." + d) for d in UNSUPPORTED_SHORTENERS)
    except Exception:
        return False


# ══════════════════════════════════════
# Metadata / preview
# ══════════════════════════════════════

async def _get_metadata(url: str, msg_id: int) -> dict:
    """Get video title, duration, thumbnail."""
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--no-download",
        "--print", '%(title)s\n%(duration)s\n%(thumbnail)s\n%(uploader)s',
        url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _active_procs[msg_id] = proc
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        lines = out.decode(errors="replace").strip().split("\n")
        return {
            "title": lines[0] if len(lines) > 0 else "video",
            "duration": lines[1] if len(lines) > 1 else "0",
            "thumbnail": lines[2] if len(lines) > 2 else "",
            "uploader": lines[3] if len(lines) > 3 else "",
        }
    except Exception:
        return {"title": "video", "duration": "0", "thumbnail": "", "uploader": ""}


# ══════════════════════════════════════
# Download engine
# ══════════════════════════════════════

async def _download_with_progress(url: str, fmt: str, label: str, bot, chat_id: int, msg_id: int, last_text: dict, title: str, is_audio: bool = False) -> Path | None:
    merge_fmt = "m4a/mp3" if is_audio else "mp4"
    output_template = str(DOWNLOAD_DIR / f"dl_{msg_id}_%(id)s.%(ext)s")
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings",
        "-f", fmt, "--merge-output-format", merge_fmt,
        "-o", output_template, "--newline",
        "--socket-timeout", "30",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        url,
    ]

    await _edit_progress(bot, chat_id, msg_id, "download", 5, f"{'🎵' if is_audio else '🎬'} {title[:40]}\n📐 {label}", last_text)

    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _active_procs[msg_id] = proc

    last_update = 0
    while True:
        if _is_cancelled(msg_id):
            proc.kill()
            return None
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=300)
        except asyncio.TimeoutError:
            break
        if not line:
            break

        decoded = line.decode(errors="replace").strip()
        if "[download]" in decoded and "%" in decoded:
            try:
                pct_match = re.search(r"(\d+\.?\d*)%", decoded)
                pct = float(pct_match.group(1)) if pct_match else 0
                now = time.time()
                if now - last_update >= 2:
                    last_update = now
                    speed_match = re.search(r"at\s+(\S+)", decoded)
                    eta_match = re.search(r"ETA\s+(\S+)", decoded)
                    parts = [f"{'🎵' if is_audio else '🎬'} {title[:40]}"]
                    if speed_match and "Unknown" not in speed_match.group(1):
                        parts.append(f"⚡ {speed_match.group(1)}/с")
                    if eta_match:
                        parts.append(f"⏱ {eta_match.group(1)}")
                    await _edit_progress(bot, chat_id, msg_id, "download", pct, "  ".join(parts), last_text)
            except Exception:
                pass

        if "[Merger]" in decoded or "Merging" in decoded:
            await _edit_progress(bot, chat_id, msg_id, "download", 95, "🔀 Объединяю...", last_text)

    await proc.stderr.read()
    await proc.wait()
    if _is_cancelled(msg_id):
        return None
    if proc.returncode != 0:
        return None

    files = sorted(DOWNLOAD_DIR.glob(f"dl_{msg_id}_*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    files = [f for f in files if f.suffix not in (".part", ".jpg", ".webp", ".temp")]
    if not files:
        files = sorted(DOWNLOAD_DIR.glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
        files = [f for f in files if f.suffix not in (".part", ".jpg", ".webp", ".temp")]
    return files[0] if files else None


async def _queued_download(bot, chat_id: int, msg_id: int, url: str, user_id: int, username: str, is_audio: bool = False):
    """Wrapper: wait for semaphore slot, then run download."""
    global _download_semaphore
    if _download_semaphore is None:
        _download_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # Show queue position if all slots busy
    if _download_semaphore.locked():
        try:
            await bot.edit_message_text(
                "⏳ <b>В очереди</b>\n\nСейчас много загрузок, подожди немного...",
                chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
                reply_markup=_cancel_kb(msg_id),
            )
        except Exception:
            pass

    async with _download_semaphore:
        if _is_cancelled(msg_id):
            return
        await _process_download(bot, chat_id, msg_id, url, user_id, username, is_audio)


async def _process_download(bot, chat_id: int, msg_id: int, url: str, user_id: int, username: str, is_audio: bool = False):
    """Main download pipeline."""
    cancel_evt = asyncio.Event()
    _cancel_flags[msg_id] = cancel_evt
    last_text = {"t": ""}

    try:
        await _edit_progress(bot, chat_id, msg_id, "download", 0, "🔍 Получаю информацию...", last_text)
        meta = await _get_metadata(url, msg_id)
        title = meta["title"]
        if _is_cancelled(msg_id):
            return

        if is_audio:
            # Audio mode — single attempt
            filepath = await _download_with_progress(url, AUDIO_FORMAT, "аудио", bot, chat_id, msg_id, last_text, title, is_audio=True)
            if _is_cancelled(msg_id):
                return
            if filepath and filepath.exists():
                filesize = filepath.stat().st_size
                if filesize <= MAX_TG_SIZE:
                    size_str = _size_fmt(filesize)
                    await _edit_progress(bot, chat_id, msg_id, "upload", 50, f"📦 {size_str}", last_text)
                    try:
                        with open(filepath, "rb") as f:
                            sent_msg = await bot.send_audio(
                                chat_id=chat_id, audio=f, title=title[:60],
                                caption=f"🎵 {title[:60]}", read_timeout=300, write_timeout=300,
                            )
                        if sent_msg.audio:
                            _cache_set(url, "audio", sent_msg.audio.file_id)
                        await bot.edit_message_text(
                            f"✅ <b>Готово!</b>\n\n{_progress_bar(100)}\n\n🎵 {title[:60]}\n📦 {size_str}",
                            chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
                        )
                        _save_download(user_id, username, title, url, "audio", filesize)
                    except Exception as e:
                        log.error("Send audio failed: %s", e)
                        await bot.edit_message_text(f"❌ Ошибка отправки:\n{str(e)[:200]}", chat_id=chat_id, message_id=msg_id)
                    finally:
                        filepath.unlink(missing_ok=True)
                    return
                else:
                    filepath.unlink(missing_ok=True)
            await bot.edit_message_text("❌ Не удалось извлечь аудио.", chat_id=chat_id, message_id=msg_id)
            return

        # Video mode — format ladder
        for label, fmt in FORMAT_LADDER:
            if _is_cancelled(msg_id):
                return
            filepath = await _download_with_progress(url, fmt, label, bot, chat_id, msg_id, last_text, title)
            if _is_cancelled(msg_id):
                return
            if filepath and filepath.exists():
                filesize = filepath.stat().st_size
                if filesize <= MAX_TG_SIZE:
                    size_str = _size_fmt(filesize)
                    await _edit_progress(bot, chat_id, msg_id, "upload", 50, f"📦 {size_str}", last_text)
                    try:
                        with open(filepath, "rb") as f:
                            sent_msg = await bot.send_video(
                                chat_id=chat_id, video=f, caption=f"🎬 {title[:60]}",
                                supports_streaming=True, read_timeout=300, write_timeout=300,
                            )
                        if sent_msg.video:
                            _cache_set(url, "video", sent_msg.video.file_id)
                        await bot.edit_message_text(
                            f"✅ <b>Готово!</b>\n\n{_progress_bar(100)}\n\n🎬 {title[:60]}\n📐 {label} · {size_str}",
                            chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
                        )
                        _save_download(user_id, username, title, url, label, filesize)
                    except Exception as e:
                        log.error("Send failed: %s", e)
                        await bot.edit_message_text(f"❌ Ошибка отправки:\n{str(e)[:200]}", chat_id=chat_id, message_id=msg_id)
                    finally:
                        filepath.unlink(missing_ok=True)
                    return
                else:
                    log.info("File too big (%d MB) at %s", filesize // (1024*1024), label)
                    filepath.unlink(missing_ok=True)
                    await _edit_progress(bot, chat_id, msg_id, "download", 20, "📦 Слишком большой, пробую ниже...", last_text)
                    continue
            continue

        if not _is_cancelled(msg_id):
            await bot.edit_message_text(
                "⚠️ Не удалось скачать видео в подходящем размере (лимит Telegram — 50 МБ).",
                chat_id=chat_id, message_id=msg_id,
            )

    except Exception as e:
        if not _is_cancelled(msg_id):
            log.error("Pipeline error: %s", e)
            try:
                await bot.edit_message_text(
                    f"❌ Ошибка:\n<code>{str(e)[:300]}</code>",
                    chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
                )
            except Exception:
                pass
    finally:
        _cancel_flags.pop(msg_id, None)
        _active_procs.pop(msg_id, None)
        for f in DOWNLOAD_DIR.glob("*"):
            try:
                if f.stat().st_mtime < time.time() - 300:
                    f.unlink()
            except Exception:
                pass


# ══════════════════════════════════════
# Handlers
# ══════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global LOGO_FILE_ID
    sent = False
    if LOGO_FILE_ID:
        try:
            await update.message.reply_photo(photo=LOGO_FILE_ID, caption=START_TEXT, parse_mode="HTML")
            sent = True
        except Exception:
            pass
    if not sent and LOGO_PATH.exists():
        try:
            with open(LOGO_PATH, "rb") as f:
                msg = await update.message.reply_photo(photo=f, caption=START_TEXT, parse_mode="HTML")
            LOGO_FILE_ID = msg.photo[-1].file_id
            sent = True
        except Exception:
            pass
    if not sent:
        await update.message.reply_text(START_TEXT, parse_mode="HTML")


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>📖 Как пользоваться</b>\n\n"
        "1. Скопируй ссылку на видео\n"
        "2. Отправь её мне\n"
        "3. Выбери 🎬 <b>Видео</b> или 🎵 <b>Аудио</b>\n"
        "4. Получи файл!\n\n"
        "<b>💡 Поддерживаемые сайты:</b>\n"
        "YouTube, TikTok, Instagram, VK Video, X/Twitter, Reddit, Facebook, Twitch, Vimeo, Dailymotion, OK.ru и <b>1000+ других</b>\n\n"
        "<b>📋 Команды:</b>\n"
        "/start — главный экран\n"
        "/history — история скачиваний\n"
        "/help — эта справка\n"
        "/about — о боте\n\n"
        "<b>⚠️ Ограничения:</b>\n"
        "▸ Лимит Telegram — 50 МБ\n"
        "▸ Если видео больше — автоматически подберу качество поменьше\n"
        "▸ Ссылки <code>share.google</code> не поддерживаются",
        parse_mode="HTML",
    )


async def about_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>🖤 О BlackBox Video</b>\n\n"
        "Мы создали этого бота, потому что верим:\n"
        "контент должен быть доступен каждому.\n\n"
        "Без рекламы. Без регистрации. Без подписок.\n"
        "Просто ссылка → видео.\n\n"
        "<b>Версия:</b> 4.0\n"
        "<b>Движок:</b> yt-dlp\n"
        "<b>Поддерживает:</b> 1000+ сайтов\n\n"
        "<i>Black Box — скачивай. Смотри. Делись.</i>",
        parse_mode="HTML",
    )


async def history_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = _get_history(update.effective_user.id)
    if not rows:
        await update.message.reply_text("📜 У тебя пока нет скачиваний.")
        return
    lines = ["<b>📜 Последние скачивания:</b>\n"]
    for i, (title, url, quality, size, source, created) in enumerate(rows, 1):
        size_str = _size_fmt(size) if size else "?"
        date_str = created[:16] if created else ""
        lines.append(f"{i}. <b>{title[:40]}</b>\n   📐 {quality} · {size_str} · {source}\n   📅 {date_str}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("🔒 Только для администраторов.")
        return
    s = _get_stats()
    if not s:
        await update.message.reply_text("📊 Нет данных.")
        return

    sources = "\n".join(f"   ▸ {src}: {cnt}" for src, cnt in s.get("top_sources", []))
    users = "\n".join(f"   ▸ {u or '?'}: {c} скач." for u, c in s.get("top_users", []))

    await update.message.reply_text(
        f"<b>📊 Статистика BlackBox Video</b>\n\n"
        f"👥 Всего пользователей: <b>{s.get('total_users', 0)}</b>\n"
        f"🚫 Забанено: <b>{s.get('banned', 0)}</b>  ·  🔇 Заблокировали бота: <b>{s.get('blocked', 0)}</b>\n"
        f"⬇️ Всего скачиваний: <b>{s.get('total_dl', 0)}</b>\n"
        f"📅 Сегодня: <b>{s.get('today_dl', 0)}</b>\n"
        f"💾 Общий объём: <b>{_size_fmt(s.get('total_size', 0))}</b>\n\n"
        f"<b>🌐 Топ источников:</b>\n{sources or '   нет данных'}\n\n"
        f"<b>👤 Топ пользователей:</b>\n{users or '   нет данных'}",
        parse_mode="HTML",
    )


async def setlogo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global LOGO_FILE_ID
    reply = update.message.reply_to_message
    if not reply or not reply.photo:
        await update.message.reply_text("Ответь на сообщение с фото командой /setlogo")
        return
    photo = reply.photo[-1]
    LOGO_FILE_ID = photo.file_id
    try:
        file = await ctx.bot.get_file(photo.file_id)
        await file.download_to_drive(str(LOGO_PATH))
        await update.message.reply_text("✅ Логотип сохранён!")
    except Exception as e:
        await update.message.reply_text(f"✅ file_id сохранён, но файл не скачался: {e}")


async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = URL_RE.findall(text)
    if not urls:
        return

    user = update.effective_user
    _ensure_user(user.id, user.username or "", user.first_name or "")

    url = urls[0].rstrip(".,;:!?)")

    if _is_unsupported(url):
        await update.message.reply_text(
            "⚠️ <b>Ссылки share.google нельзя обработать</b> — они используют JS-редирект.\n\n"
            "Открой ссылку в браузере и отправь прямую ссылку.",
            parse_mode="HTML",
        )
        return

    if _needs_redirect(url):
        url = await resolve_redirects(url)

    # Preview: show title + duration + buttons
    msg = await update.message.reply_text("🔍 Загружаю информацию...", parse_mode="HTML")
    msg_id = msg.message_id

    meta = await _get_metadata(url, msg_id)
    title = meta["title"][:60]
    dur = _dur_fmt(meta["duration"])
    uploader = meta.get("uploader", "")[:30]

    preview_text = (
        f"<b>{title}</b>\n"
        f"{'👤 ' + uploader + '  ·  ' if uploader and uploader != 'NA' else ''}"
        f"⏱ {dur}\n\n"
        f"Что скачать?"
    )

    from hashlib import md5
    url_key = md5(url.encode()).hexdigest()[:10]
    _url_store[url_key] = url

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Видео", callback_data=f"go:{url_key}:video"),
            InlineKeyboardButton("🎵 Аудио", callback_data=f"go:{url_key}:audio"),
        ],
    ])

    # Try to send thumbnail preview
    thumb_url = meta.get("thumbnail", "")
    sent = False
    if thumb_url and thumb_url.startswith("http"):
        try:
            await ctx.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            await update.message.reply_photo(photo=thumb_url, caption=preview_text, parse_mode="HTML", reply_markup=keyboard)
            sent = True
        except Exception:
            pass

    if not sent:
        try:
            await ctx.bot.edit_message_text(
                preview_text, chat_id=update.effective_chat.id, message_id=msg_id,
                parse_mode="HTML", reply_markup=keyboard,
            )
        except Exception:
            pass


# URL store for preview → download
_url_store: dict[str, str] = {}


async def go_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle video/audio button press from preview."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3:
        return

    _, url_key, mode = parts
    url = _url_store.get(url_key)
    if not url:
        await query.edit_message_text("❌ Ссылка устарела, отправь заново.")
        return

    is_audio = mode == "audio"
    user = update.effective_user
    uid = user.id
    uname = user.username or user.first_name or str(uid)

    # Ban check
    if _is_banned(uid):
        await query.edit_message_text("🚫 Ты заблокирован.")
        return

    # Daily limit (admins unlimited)
    if uid not in ADMIN_IDS:
        today = _get_today_count(uid)
        if today >= DAILY_LIMIT_FREE:
            await query.edit_message_text(
                f"⚠️ Лимит на сегодня исчерпан ({DAILY_LIMIT_FREE} скачиваний).\nПопробуй завтра!",
            )
            return

    # Cache check — instant delivery
    cached_fid = _cache_get(url, mode)
    if cached_fid:
        try:
            if is_audio:
                await ctx.bot.send_audio(chat_id=query.message.chat_id, audio=cached_fid, caption="🎵 Из кэша — мгновенно!")
            else:
                await ctx.bot.send_video(chat_id=query.message.chat_id, video=cached_fid, caption="🎬 Из кэша — мгновенно!", supports_streaming=True)
            await query.edit_message_text("✅ <b>Готово!</b> (из кэша)", parse_mode="HTML")
            _save_download(uid, uname, "cached", url, mode, 0)
            return
        except Exception:
            _file_cache.pop(_cache_key(url, mode), None)

    # Prepare progress message
    msg_id = query.message.message_id
    if query.message.photo:
        try:
            await query.message.delete()
        except Exception:
            pass
        new_msg = await ctx.bot.send_message(
            chat_id=query.message.chat_id,
            text="⬇️ <b>Скачиваю</b>\n\n" + _progress_bar(0) + "  0%",
            parse_mode="HTML",
        )
        msg_id = new_msg.message_id
    else:
        try:
            await query.edit_message_text(
                "⬇️ <b>Скачиваю</b>\n\n" + _progress_bar(0) + "  0%",
                parse_mode="HTML",
            )
        except Exception:
            pass

    asyncio.create_task(_queued_download(
        ctx.bot, query.message.chat_id, msg_id, url, uid, uname, is_audio,
    ))


async def cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Отменяю...")
    parts = query.data.split(":")
    if len(parts) != 2:
        return
    msg_id = int(parts[1])
    evt = _cancel_flags.get(msg_id)
    if evt:
        evt.set()
    proc = _active_procs.get(msg_id)
    if proc and proc.returncode is None:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        await query.edit_message_text("🚫 <b>Отменено</b>", parse_mode="HTML")
    except Exception:
        pass


# ══════════════════════════════════════
# Admin commands
# ══════════════════════════════════════

async def ban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /ban <user_id>")
        return
    try:
        uid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Некорректный user_id")
        return
    if uid in ADMIN_IDS:
        await update.message.reply_text("❌ Нельзя забанить админа.")
        return
    _ensure_user(uid, "", "")
    _set_banned(uid, True)
    await update.message.reply_text(f"🚫 Пользователь <code>{uid}</code> забанен.", parse_mode="HTML")


async def unban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /unban <user_id>")
        return
    try:
        uid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Некорректный user_id")
        return
    _set_banned(uid, False)
    await update.message.reply_text(f"✅ Пользователь <code>{uid}</code> разбанен.", parse_mode="HTML")


async def users_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    page = 0
    if ctx.args:
        try:
            page = max(0, int(ctx.args[0]) - 1)
        except ValueError:
            pass
    rows, total = _get_all_users(page=page)
    if not rows:
        await update.message.reply_text("👥 Нет пользователей.")
        return

    lines = [f"<b>👥 Пользователи</b> (стр. {page + 1}, всего {total})\n"]
    for uid, uname, fname, dl_count, banned, blocked in rows:
        flags = ""
        if banned:
            flags += "🚫"
        if blocked:
            flags += "🔇"
        name = uname or fname or str(uid)
        lines.append(f"▸ <code>{uid}</code> {name} — {dl_count} скач. {flags}")

    # Navigation buttons
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️", callback_data=f"users_page:{page - 1}"))
    if (page + 1) * 20 < total:
        buttons.append(InlineKeyboardButton("➡️", callback_data=f"users_page:{page + 1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=markup)


async def users_page_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("🔒")
        return
    await query.answer()
    page = int(query.data.split(":")[1])
    rows, total = _get_all_users(page=page)
    if not rows:
        await query.edit_message_text("👥 Нет данных.")
        return

    lines = [f"<b>👥 Пользователи</b> (стр. {page + 1}, всего {total})\n"]
    for uid, uname, fname, dl_count, banned, blocked in rows:
        flags = ""
        if banned:
            flags += "🚫"
        if blocked:
            flags += "🔇"
        name = uname or fname or str(uid)
        lines.append(f"▸ <code>{uid}</code> {name} — {dl_count} скач. {flags}")

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️", callback_data=f"users_page:{page - 1}"))
    if (page + 1) * 20 < total:
        buttons.append(InlineKeyboardButton("➡️", callback_data=f"users_page:{page + 1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None
    await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=markup)


# Broadcast state
_broadcast_pending: dict[int, str] = {}  # admin_id → pending text


async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text(
            "📢 <b>Рассылка</b>\n\nИспользование: /broadcast текст сообщения\n\n"
            "Также можно ответить на сообщение (текст/фото/видео) командой /broadcast для пересылки.",
            parse_mode="HTML",
        )
        return

    recipients = _get_broadcast_users()
    if not recipients:
        await update.message.reply_text("👥 Нет доступных пользователей для рассылки.")
        return

    progress = await update.message.reply_text(f"📢 Отправляю {len(recipients)} пользователям...")
    sent, failed, blocked = 0, 0, 0

    for uid in recipients:
        try:
            # If replying to a message with media, forward it
            reply = update.message.reply_to_message
            if reply and reply.photo:
                await ctx.bot.send_photo(
                    chat_id=uid, photo=reply.photo[-1].file_id,
                    caption=text, parse_mode="HTML",
                )
            elif reply and reply.video:
                await ctx.bot.send_video(
                    chat_id=uid, video=reply.video.file_id,
                    caption=text, parse_mode="HTML",
                )
            else:
                await ctx.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err or "deactivated" in err or "not found" in err:
                _set_bot_blocked(uid, True)
                blocked += 1
            else:
                failed += 1
        # Rate limiting
        if sent % 25 == 0:
            await asyncio.sleep(1)

    await progress.edit_text(
        f"📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Доставлено: {sent}\n"
        f"🔇 Заблокировали бота: {blocked}\n"
        f"❌ Ошибки: {failed}",
        parse_mode="HTML",
    )


async def post_init(app):
    from telegram import BotCommandScopeChat
    # Default menu for all users
    await app.bot.set_my_commands([
        BotCommand("start", "🚀 Запустить бота"),
        BotCommand("help", "📖 Как пользоваться"),
        BotCommand("history", "📜 История скачиваний"),
        BotCommand("about", "🖤 О BlackBox Video"),
    ])
    # Extended menu for each admin
    admin_commands = [
        BotCommand("start", "🚀 Запустить бота"),
        BotCommand("help", "📖 Как пользоваться"),
        BotCommand("history", "📜 История скачиваний"),
        BotCommand("about", "🖤 О BlackBox Video"),
        BotCommand("stats", "📊 Статистика"),
        BotCommand("users", "👥 Пользователи"),
        BotCommand("ban", "🚫 Забанить (user_id)"),
        BotCommand("unban", "✅ Разбанить (user_id)"),
        BotCommand("broadcast", "📢 Рассылка"),
        BotCommand("setlogo", "🖼 Сменить логотип"),
    ]
    for aid in ADMIN_IDS:
        try:
            await app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=aid))
        except Exception as e:
            log.warning("Failed to set admin commands for %s: %s", aid, e)
    log.info("Bot menu commands set (+ admin menus)")


def main():
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("setlogo", setlogo))
    # Admin commands
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    # Callbacks
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^cancel:"))
    app.add_handler(CallbackQueryHandler(go_callback, pattern=r"^go:"))
    app.add_handler(CallbackQueryHandler(users_page_callback, pattern=r"^users_page:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    log.info("BlackBox Video bot v4.0 started!")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
