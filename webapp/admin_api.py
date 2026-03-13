"""
Admin Panel API — backend для веб-админки.

Endpoints:
  GET  /admin/api/stats         — общая статистика
  GET  /admin/api/system        — CPU/RAM/Disk
  GET  /admin/api/tracks        — список треков (paginated)
  GET  /admin/api/users         — список юзеров (paginated)
  GET  /admin/api/users/growth  — прирост юзеров по дням
  GET  /admin/api/logs          — последние ошибки
  GET  /admin/api/logs/stream   — SSE поток логов
  DELETE /admin/api/tracks/{id} — удалить трек
  POST /admin/api/users/{id}/ban — забанить юзера
  POST /admin/api/users/{id}/premium — выдать премиум
"""
import asyncio
import os
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, case, and_, desc

from bot.config import settings
from bot.models.base import async_session
from bot.models.user import User
from bot.models.track import Track, ListeningHistory, Payment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api", tags=["admin"])


async def _read_cpu_percent(sample_seconds: float = 0.2) -> float:
    """Measure CPU usage from /proc/stat over a short interval."""
    def _read_cpu_times() -> tuple[int, int]:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        values = [int(value) for value in parts[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        return idle, total

    idle_before, total_before = _read_cpu_times()
    await asyncio.sleep(sample_seconds)
    idle_after, total_after = _read_cpu_times()

    total_delta = total_after - total_before
    idle_delta = idle_after - idle_before
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100))

# ── Auth ─────────────────────────────────────────────────────────────────

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "admin-secret-token-change-me")


async def verify_admin(authorization: str = Header(None)) -> bool:
    """Verify admin token from Authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    # Bearer token or plain token
    token = authorization.replace("Bearer ", "").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return True


# ── Schemas ──────────────────────────────────────────────────────────────

class StatsResponse(BaseModel):
    total_users: int
    users_today: int
    users_week: int
    dau: int
    wau: int
    mau: int
    premium_users: int
    banned_users: int
    total_tracks: int
    total_plays: int
    plays_today: int
    plays_week: int
    total_downloads: int
    total_revenue: int
    revenue_month: int


class SystemStats(BaseModel):
    cpu_percent: float
    memory_used_gb: float
    memory_total_gb: float
    memory_percent: float
    disk_used_gb: float
    disk_total_gb: float
    disk_percent: float
    load_avg: list[float]
    uptime_hours: float
    containers: list[dict]


class TrackItem(BaseModel):
    id: int
    source_id: str
    title: str
    artist: str
    source: Optional[str]
    downloads: int
    duration: Optional[int]
    created_at: Optional[datetime]


class UserItem(BaseModel):
    id: int
    username: Optional[str]
    first_name: Optional[str]
    language: str
    is_premium: bool
    is_banned: bool
    request_count: int
    created_at: Optional[datetime]
    last_active: Optional[datetime]


class GrowthPoint(BaseModel):
    date: str
    count: int
    cumulative: int


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int


# ── Stats ────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsResponse)
async def get_stats(_: bool = Depends(verify_admin)):
    """Get overall bot statistics."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    async with async_session() as session:
        # Users stats
        user_stats = await session.execute(
            select(
                func.count().label("total"),
                func.sum(case((User.created_at >= today_start, 1), else_=0)),
                func.sum(case((User.created_at >= week_ago, 1), else_=0)),
                func.sum(case((User.last_active >= today_start, 1), else_=0)),
                func.sum(case((User.last_active >= week_ago, 1), else_=0)),
                func.sum(case((User.last_active >= month_ago, 1), else_=0)),
                func.sum(case((User.is_premium == True, 1), else_=0)),
                func.sum(case((User.is_banned == True, 1), else_=0)),
            )
        )
        u = user_stats.one()

        # Tracks stats
        track_stats = await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Track.downloads), 0),
            ).select_from(Track)
        )
        tr = track_stats.one()

        # Plays stats
        play_stats = await session.execute(
            select(
                func.count().label("total"),
                func.sum(case((ListeningHistory.created_at >= today_start, 1), else_=0)),
                func.sum(case((ListeningHistory.created_at >= week_ago, 1), else_=0)),
            ).where(ListeningHistory.action == "play")
        )
        pl = play_stats.one()

        # Revenue
        rev_stats = await session.execute(
            select(
                func.coalesce(func.sum(Payment.amount), 0),
                func.coalesce(func.sum(case((Payment.created_at >= month_ago, Payment.amount), else_=0)), 0),
            )
        )
        rv = rev_stats.one()

    return StatsResponse(
        total_users=u[0] or 0,
        users_today=int(u[1] or 0),
        users_week=int(u[2] or 0),
        dau=int(u[3] or 0),
        wau=int(u[4] or 0),
        mau=int(u[5] or 0),
        premium_users=int(u[6] or 0),
        banned_users=int(u[7] or 0),
        total_tracks=tr[0] or 0,
        total_plays=pl[0] or 0,
        plays_today=int(pl[1] or 0),
        plays_week=int(pl[2] or 0),
        total_downloads=int(tr[1] or 0),
        total_revenue=int(rv[0] or 0),
        revenue_month=int(rv[1] or 0),
    )


# ── System Metrics ───────────────────────────────────────────────────────

@router.get("/system", response_model=SystemStats)
async def get_system_stats(_: bool = Depends(verify_admin)):
    """Get system resource usage (CPU, RAM, Disk)."""
    try:
        # CPU & Memory via /proc (Linux)
        with open("/proc/loadavg") as f:
            load_parts = f.read().split()
            load_avg = [float(load_parts[0]), float(load_parts[1]), float(load_parts[2])]

        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    meminfo[key] = int(val)
            mem_total = meminfo.get("MemTotal", 0) / 1024 / 1024  # GB
            mem_free = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1024 / 1024
            mem_used = mem_total - mem_free
            mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0

        # Disk
        stat = os.statvfs("/")
        disk_total = stat.f_blocks * stat.f_frsize / 1024 / 1024 / 1024
        disk_free = stat.f_bavail * stat.f_frsize / 1024 / 1024 / 1024
        disk_used = disk_total - disk_free
        disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0

        # Uptime
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
            uptime_hours = uptime_seconds / 3600

        # CPU usage from /proc/stat is more accurate than load average.
        cpu_percent = await _read_cpu_percent()

        # Docker containers
        containers = []
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    containers.append({
                        "name": parts[0] if len(parts) > 0 else "",
                        "status": parts[1] if len(parts) > 1 else "",
                        "ports": parts[2] if len(parts) > 2 else "",
                    })
        except Exception:
            pass

        return SystemStats(
            cpu_percent=round(cpu_percent, 1),
            memory_used_gb=round(mem_used, 2),
            memory_total_gb=round(mem_total, 2),
            memory_percent=round(mem_percent, 1),
            disk_used_gb=round(disk_used, 2),
            disk_total_gb=round(disk_total, 2),
            disk_percent=round(disk_percent, 1),
            load_avg=load_avg,
            uptime_hours=round(uptime_hours, 1),
            containers=containers,
        )
    except Exception as e:
        logger.error("System stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Tracks ───────────────────────────────────────────────────────────────

@router.get("/tracks")
async def get_tracks(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(None),
    source: str = Query(None),
    sort: str = Query("downloads"),  # downloads, created_at, title
    _: bool = Depends(verify_admin),
):
    """Get paginated list of tracks."""
    async with async_session() as session:
        query = select(Track)
        count_query = select(func.count()).select_from(Track)

        # Filters
        if search:
            search_filter = Track.title.ilike(f"%{search}%") | Track.artist.ilike(f"%{search}%")
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)
        
        if source:
            query = query.where(Track.source == source)
            count_query = count_query.where(Track.source == source)

        # Sorting
        if sort == "downloads":
            query = query.order_by(desc(Track.downloads))
        elif sort == "created_at":
            query = query.order_by(desc(Track.created_at))
        elif sort == "title":
            query = query.order_by(Track.title)

        # Pagination
        total = (await session.execute(count_query)).scalar() or 0
        query = query.offset((page - 1) * per_page).limit(per_page)
        
        result = await session.execute(query)
        tracks = result.scalars().all()

    return {
        "items": [
            TrackItem(
                id=t.id,
                source_id=t.source_id,
                title=t.title or "",
                artist=t.artist or "",
                source=t.source,
                downloads=t.downloads or 0,
                duration=t.duration,
                created_at=t.created_at,
            ).model_dump()
            for t in tracks
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.delete("/tracks/{track_id}")
async def delete_track(track_id: int, _: bool = Depends(verify_admin)):
    """Delete a track from database."""
    async with async_session() as session:
        track = await session.get(Track, track_id)
        if not track:
            raise HTTPException(status_code=404, detail="Track not found")
        await session.delete(track)
        await session.commit()
    return {"ok": True, "deleted": track_id}


# ── Users ────────────────────────────────────────────────────────────────

@router.get("/users")
async def get_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(None),
    premium_only: bool = Query(False),
    banned_only: bool = Query(False),
    sort: str = Query("last_active"),  # last_active, created_at, request_count
    _: bool = Depends(verify_admin),
):
    """Get paginated list of users."""
    async with async_session() as session:
        query = select(User)
        count_query = select(func.count()).select_from(User)

        # Filters
        if search:
            search_filter = User.username.ilike(f"%{search}%") | User.first_name.ilike(f"%{search}%")
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)
        
        if premium_only:
            query = query.where(User.is_premium == True)
            count_query = count_query.where(User.is_premium == True)
        
        if banned_only:
            query = query.where(User.is_banned == True)
            count_query = count_query.where(User.is_banned == True)

        # Sorting
        if sort == "last_active":
            query = query.order_by(desc(User.last_active))
        elif sort == "created_at":
            query = query.order_by(desc(User.created_at))
        elif sort == "request_count":
            query = query.order_by(desc(User.request_count))

        # Pagination
        total = (await session.execute(count_query)).scalar() or 0
        query = query.offset((page - 1) * per_page).limit(per_page)
        
        result = await session.execute(query)
        users = result.scalars().all()

    return {
        "items": [
            UserItem(
                id=u.id,
                username=u.username,
                first_name=u.first_name,
                language=u.language or "ru",
                is_premium=u.is_premium or False,
                is_banned=u.is_banned or False,
                request_count=u.request_count or 0,
                created_at=u.created_at,
                last_active=u.last_active,
            ).model_dump()
            for u in users
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/users/growth")
async def get_user_growth(
    days: int = Query(30, ge=1, le=365),
    _: bool = Depends(verify_admin),
):
    """Get user growth over time."""
    async with async_session() as session:
        # Get daily signups
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        result = await session.execute(
            select(
                func.date(User.created_at).label("date"),
                func.count().label("count")
            )
            .where(User.created_at >= start_date)
            .group_by(func.date(User.created_at))
            .order_by(func.date(User.created_at))
        )
        daily = {str(row[0]): row[1] for row in result.all()}

        # Get total users before start_date
        base_count = (await session.execute(
            select(func.count()).select_from(User).where(User.created_at < start_date)
        )).scalar() or 0

    # Build cumulative data
    growth = []
    cumulative = base_count
    current = start_date.date()
    end = datetime.now(timezone.utc).date()
    
    while current <= end:
        date_str = str(current)
        count = daily.get(date_str, 0)
        cumulative += count
        growth.append(GrowthPoint(
            date=date_str,
            count=count,
            cumulative=cumulative,
        ).model_dump())
        current += timedelta(days=1)

    return {"growth": growth}


@router.post("/users/{user_id}/ban")
async def ban_user(user_id: int, unban: bool = Query(False), _: bool = Depends(verify_admin)):
    """Ban or unban a user."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_banned = not unban
        await session.commit()
    return {"ok": True, "user_id": user_id, "is_banned": not unban}


@router.post("/users/{user_id}/premium")
async def toggle_premium(user_id: int, remove: bool = Query(False), _: bool = Depends(verify_admin)):
    """Grant or remove premium."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_premium = not remove
        if not remove:
            user.premium_until = None  # admin premium = unlimited
        await session.commit()
    return {"ok": True, "user_id": user_id, "is_premium": not remove}


# ── Logs ─────────────────────────────────────────────────────────────────

LOG_DIR = Path("/app/logs") if Path("/app").exists() else Path("logs")


@router.get("/logs")
async def get_logs(
    lines: int = Query(100, ge=1, le=1000),
    level: str = Query(None),  # ERROR, WARNING, INFO
    _: bool = Depends(verify_admin),
):
    """Get recent log entries from errors.log."""
    log_file = LOG_DIR / "errors.log"
    if not log_file.exists():
        return {"logs": [], "file": str(log_file), "exists": False}

    entries = []
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            # Read last N lines efficiently
            all_lines = f.readlines()
            recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
            
            for line in recent:
                line = line.strip()
                if not line:
                    continue
                
                # Parse: "2026-03-13 12:00:00,123 [ERROR] logger: message"
                try:
                    parts = line.split(" ", 3)
                    if len(parts) >= 4:
                        ts = f"{parts[0]} {parts[1]}"
                        lvl = parts[2].strip("[]")
                        rest = parts[3]
                        logger_name = rest.split(":")[0] if ":" in rest else "unknown"
                        msg = rest.split(":", 1)[1].strip() if ":" in rest else rest
                        
                        if level and lvl != level:
                            continue
                            
                        entries.append(LogEntry(
                            timestamp=ts,
                            level=lvl,
                            logger=logger_name,
                            message=msg[:500],  # truncate long messages
                        ).model_dump())
                except Exception:
                    entries.append(LogEntry(
                        timestamp="",
                        level="UNKNOWN",
                        logger="",
                        message=line[:500],
                    ).model_dump())
    except Exception as e:
        logger.error("Error reading logs: %s", e)

    return {"logs": entries, "file": str(log_file), "exists": True}


@router.get("/logs/stream")
async def stream_logs(_: bool = Depends(verify_admin)):
    """SSE stream of new log entries."""
    log_file = LOG_DIR / "errors.log"
    
    async def generate():
        if not log_file.exists():
            yield f"data: {{}}\n\n"
            return
        
        # Start from end of file
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, 2)  # Go to end
            while True:
                line = f.readline()
                if line:
                    yield f"data: {line.strip()}\n\n"
                else:
                    await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── Sources breakdown ────────────────────────────────────────────────────

@router.get("/sources")
async def get_source_stats(_: bool = Depends(verify_admin)):
    """Get track sources breakdown."""
    async with async_session() as session:
        result = await session.execute(
            select(
                ListeningHistory.source,
                func.count().label("plays")
            )
            .where(ListeningHistory.action == "play")
            .group_by(ListeningHistory.source)
        )
        sources = {row[0] or "unknown": row[1] for row in result.all()}

        # Track sources
        track_sources = await session.execute(
            select(Track.source, func.count())
            .group_by(Track.source)
        )
        tracks_by_source = {row[0] or "unknown": row[1] for row in track_sources.all()}

    return {
        "plays_by_source": sources,
        "tracks_by_source": tracks_by_source,
    }
