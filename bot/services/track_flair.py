"""Optional caption flair for specific tracks (team dedications, easter eggs)."""
from __future__ import annotations

from bot.i18n import t

_KOKA_LOVA_YM_IDS = frozenset({114644167})
_KOKA_LOVA_VIDS = frozenset({"ym_114644167"})


def is_koka_lova_jax_track(track_info: dict) -> bool:
    """Jax (02.14), Nel (02.14) — Koka Lova on Yandex Music."""
    vid = str(track_info.get("video_id") or "")
    if vid in _KOKA_LOVA_VIDS:
        return True
    ym_id = track_info.get("ym_track_id")
    if ym_id is not None:
        try:
            if int(ym_id) in _KOKA_LOVA_YM_IDS:
                return True
        except (TypeError, ValueError):
            pass
    title = (track_info.get("title") or "").lower()
    artist = (track_info.get("uploader") or track_info.get("artist") or "").lower()
    blob = f"{artist} {title}"
    if "koka lova" not in title and "koka lova" not in blob:
        return False
    return any(marker in artist for marker in ("jax", "02.14", "0214", "nel"))


def track_extra_caption_lines(lang: str, track_info: dict) -> str | None:
    """Return extra HTML caption block for known tracks, or None."""
    if is_koka_lova_jax_track(track_info):
        return t(lang, "koka_lova_teni_flair")
    return None
