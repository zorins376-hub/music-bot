"""
story_cards.py — Generate shareable story cards (1080×1920).

Creates branded images with track info, gradient background, and QR code deep-link.
Used for track sharing and Weekly Recap stories.
"""
import hashlib
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy imports to avoid import-time failures if Pillow not installed
_PIL_AVAILABLE = False
try:
    from PIL import Image, ImageDraw, ImageFont
    import qrcode
    _PIL_AVAILABLE = True
except ImportError:
    pass

_WIDTH = 1080
_HEIGHT = 1920
_BG_TOP = (15, 15, 25)      # Dark gradient top
_BG_BOTTOM = (30, 10, 45)   # Dark gradient bottom
_ACCENT = (200, 160, 255)   # Purple accent
_WHITE = (255, 255, 255)
_GREY = (180, 180, 180)

_BOT_USERNAME = "TSmymusicbot_bot"


def _gradient_bg() -> "Image.Image":
    """Create a vertical gradient 1080×1920."""
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(_HEIGHT):
        ratio = y / _HEIGHT
        r = int(_BG_TOP[0] + (_BG_BOTTOM[0] - _BG_TOP[0]) * ratio)
        g = int(_BG_TOP[1] + (_BG_BOTTOM[1] - _BG_TOP[1]) * ratio)
        b = int(_BG_TOP[2] + (_BG_BOTTOM[2] - _BG_TOP[2]) * ratio)
        draw.line([(0, y), (_WIDTH, y)], fill=(r, g, b))
    return img


def _get_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont":
    """Load font with fallback to default."""
    try:
        from pathlib import Path
        font_dir = Path(__file__).parent.parent / "assets" / "fonts"
        font_file = font_dir / ("Inter-Bold.ttf" if bold else "Inter-Regular.ttf")
        if font_file.exists():
            return ImageFont.truetype(str(font_file), size)
    except Exception:
        pass
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _make_qr(url: str, size: int = 200) -> "Image.Image":
    """Generate QR code image."""
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="white", back_color="transparent")
    return img.resize((size, size), Image.LANCZOS)


def generate_track_card(
    artist: str,
    title: str,
    track_id: int | str,
    duration: str = "",
    cover_bytes: bytes | None = None,
) -> bytes | None:
    """Generate a 1080×1920 story card for a track. Returns PNG bytes."""
    if not _PIL_AVAILABLE:
        logger.warning("Pillow not installed, cannot generate story card")
        return None

    img = _gradient_bg()
    draw = ImageDraw.Draw(img)

    # Branding
    font_brand = _get_font(48, bold=True)
    draw.text((_WIDTH // 2, 120), "BLACK ROOM", fill=_ACCENT, font=font_brand, anchor="mm")

    # Cover (placeholder circle if no cover)
    cover_y = 400
    cover_size = 400
    if cover_bytes:
        try:
            cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
            cover = cover.resize((cover_size, cover_size), Image.LANCZOS)
            # Round corners
            mask = Image.new("L", (cover_size, cover_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (cover_size, cover_size)], radius=30, fill=255)
            img.paste(cover, ((_WIDTH - cover_size) // 2, cover_y), mask)
        except Exception:
            _draw_placeholder(draw, cover_y, cover_size)
    else:
        _draw_placeholder(draw, cover_y, cover_size)

    # Title
    font_title = _get_font(52, bold=True)
    font_artist = _get_font(40)
    font_dur = _get_font(32)

    text_y = cover_y + cover_size + 80
    draw.text((_WIDTH // 2, text_y), title[:40], fill=_WHITE, font=font_title, anchor="mm")
    draw.text((_WIDTH // 2, text_y + 70), artist[:40], fill=_GREY, font=font_artist, anchor="mm")
    if duration:
        draw.text((_WIDTH // 2, text_y + 130), f"◷ {duration}", fill=_GREY, font=font_dur, anchor="mm")

    # QR code
    deep_link = f"https://t.me/{_BOT_USERNAME}?start=tr_{track_id}"
    try:
        qr_img = _make_qr(deep_link, 200)
        qr_pos = ((_WIDTH - 200) // 2, _HEIGHT - 380)
        img.paste(qr_img, qr_pos)
    except Exception:
        pass

    # Footer
    font_footer = _get_font(28)
    draw.text((_WIDTH // 2, _HEIGHT - 120), "Отсканируй QR или нажми ▶", fill=_GREY, font=font_footer, anchor="mm")
    draw.text((_WIDTH // 2, _HEIGHT - 70), f"@{_BOT_USERNAME}", fill=_ACCENT, font=font_footer, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, "PNG", quality=95)
    return buf.getvalue()


def generate_recap_card(
    user_name: str,
    play_count: int,
    top_artists: list[str],
    top_track: str = "",
) -> bytes | None:
    """Generate a Weekly Recap story card. Returns PNG bytes."""
    if not _PIL_AVAILABLE:
        return None

    img = _gradient_bg()
    draw = ImageDraw.Draw(img)

    font_brand = _get_font(48, bold=True)
    font_title = _get_font(44, bold=True)
    font_text = _get_font(36)
    font_stat = _get_font(80, bold=True)

    # Branding
    draw.text((_WIDTH // 2, 120), "BLACK ROOM", fill=_ACCENT, font=font_brand, anchor="mm")
    draw.text((_WIDTH // 2, 200), "WEEKLY RECAP", fill=_WHITE, font=font_title, anchor="mm")

    # User name
    draw.text((_WIDTH // 2, 360), user_name, fill=_GREY, font=font_text, anchor="mm")

    # Play count - big number
    draw.text((_WIDTH // 2, 550), str(play_count), fill=_ACCENT, font=font_stat, anchor="mm")
    draw.text((_WIDTH // 2, 640), "треков на этой неделе", fill=_GREY, font=font_text, anchor="mm")

    # Top artists
    if top_artists:
        y = 800
        draw.text((_WIDTH // 2, y), "ТОП АРТИСТЫ", fill=_WHITE, font=font_title, anchor="mm")
        for i, artist in enumerate(top_artists[:5], 1):
            y += 60
            draw.text((_WIDTH // 2, y), f"{i}. {artist}", fill=_GREY, font=font_text, anchor="mm")

    # Top track
    if top_track:
        draw.text((_WIDTH // 2, 1200), "ТРЕК НЕДЕЛИ", fill=_WHITE, font=font_title, anchor="mm")
        draw.text((_WIDTH // 2, 1270), top_track[:50], fill=_ACCENT, font=font_text, anchor="mm")

    # Footer
    font_footer = _get_font(28)
    draw.text((_WIDTH // 2, _HEIGHT - 70), f"@{_BOT_USERNAME}", fill=_ACCENT, font=font_footer, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, "PNG", quality=95)
    return buf.getvalue()


def _draw_placeholder(draw: "ImageDraw.ImageDraw", y: int, size: int) -> None:
    """Draw a placeholder circle for missing cover art."""
    cx, cy = _WIDTH // 2, y + size // 2
    r = size // 2 - 10
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=_ACCENT, width=3)
    font = _get_font(80, bold=True)
    draw.text((cx, cy), "♪", fill=_ACCENT, font=font, anchor="mm")
