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
_ACCENT = (200, 160, 255)   # Purple accent
_WHITE = (255, 255, 255)
_GREY = (180, 180, 180)

_BOT_USERNAME = "TSmymusicbot_bot"


def _gradient_bg(dominant_rgb: tuple[int, int, int] | None = None) -> "Image.Image":
    """Create a vertical gradient 1080×1920 based on dominant cover colour."""
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    draw = ImageDraw.Draw(img)

    if dominant_rgb:
        r0, g0, b0 = dominant_rgb
        # Darken for top and extra-darken for bottom
        top = (max(r0 // 2, 8), max(g0 // 2, 8), max(b0 // 2, 8))
        bot = (max(r0 // 6, 4), max(g0 // 6, 4), max(b0 // 6, 4))
    else:
        top = (15, 15, 25)
        bot = (30, 10, 45)

    for y in range(_HEIGHT):
        ratio = y / _HEIGHT
        r = int(top[0] + (bot[0] - top[0]) * ratio)
        g = int(top[1] + (bot[1] - top[1]) * ratio)
        b = int(top[2] + (bot[2] - top[2]) * ratio)
        draw.line([(0, y), (_WIDTH, y)], fill=(r, g, b))
    return img


def _dominant_color(cover_bytes: bytes) -> tuple[int, int, int]:
    """Extract dominant colour from cover image bytes."""
    try:
        cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
        small = cover.resize((40, 40), Image.LANCZOS)
        pixels = list(small.getdata())
        # Filter out near-black/near-white
        filtered = [(r, g, b) for r, g, b in pixels if (r + g + b) > 60 and (r + g + b) < 700]
        if not filtered:
            filtered = pixels
        avg_r = sum(p[0] for p in filtered) // len(filtered)
        avg_g = sum(p[1] for p in filtered) // len(filtered)
        avg_b = sum(p[2] for p in filtered) // len(filtered)
        return (avg_r, avg_g, avg_b)
    except Exception:
        return (100, 60, 180)


def _get_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont":
    """Load font with fallback to system DejaVu."""
    # 1) Custom bundled fonts
    try:
        from pathlib import Path
        font_dir = Path(__file__).parent.parent / "assets" / "fonts"
        font_file = font_dir / ("Inter-Bold.ttf" if bold else "Inter-Regular.ttf")
        if font_file.exists():
            return ImageFont.truetype(str(font_file), size)
    except Exception:
        logger.debug("custom font load failed", exc_info=True)
    # 2) System DejaVu (installed via fonts-dejavu-core in Docker)
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    # 3) arial / any truetype
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

    # Extract dominant colour from cover for dynamic gradient
    dominant = _dominant_color(cover_bytes) if cover_bytes else None
    img = _gradient_bg(dominant)
    draw = ImageDraw.Draw(img)

    # --- Accent colour derived from cover ---
    if dominant:
        dr, dg, db = dominant
        # Brighten for accent text
        accent = (min(dr + 80, 255), min(dg + 80, 255), min(db + 80, 255))
    else:
        accent = _ACCENT

    # --- Large cover image (640×640) ---
    cover_size = 640
    cover_x = (_WIDTH - cover_size) // 2
    cover_y = 300

    if cover_bytes:
        try:
            cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
            cover = cover.resize((cover_size, cover_size), Image.LANCZOS)

            # Round corners mask
            mask = Image.new("L", (cover_size, cover_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (cover_size, cover_size)], radius=40, fill=255)

            # Drop shadow
            shadow_offset = 12
            shadow = Image.new("RGBA", (cover_size + 40, cover_size + 40), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.rounded_rectangle(
                [(20, 20), (cover_size + 20, cover_size + 20)],
                radius=40, fill=(0, 0, 0, 100),
            )
            try:
                from PIL import ImageFilter
                shadow = shadow.blur(radius=20) if hasattr(shadow, "blur") else shadow.filter(ImageFilter.GaussianBlur(20))
            except Exception:
                pass
            img.paste(shadow, (cover_x - 20 + shadow_offset, cover_y - 20 + shadow_offset), shadow)

            img.paste(cover, (cover_x, cover_y), mask)
        except Exception:
            _draw_placeholder(draw, cover_y, cover_size)
    else:
        _draw_placeholder(draw, cover_y, cover_size)

    # --- Track info ---
    font_title = _get_font(56, bold=True)
    font_artist = _get_font(42)
    font_dur = _get_font(34)

    text_y = cover_y + cover_size + 60

    # Title (truncate with ellipsis)
    display_title = title[:35] + "…" if len(title) > 35 else title
    draw.text((_WIDTH // 2, text_y), display_title, fill=_WHITE, font=font_title, anchor="mm")

    # Artist
    display_artist = artist[:35] + "…" if len(artist) > 35 else artist
    draw.text((_WIDTH // 2, text_y + 70), display_artist, fill=_GREY, font=font_artist, anchor="mm")

    # Duration pill
    if duration:
        pill_y = text_y + 135
        pill_text = f"  {duration}  "
        font_pill = _get_font(30)
        bbox = font_pill.getbbox(pill_text)
        pw = bbox[2] - bbox[0] + 30
        ph = bbox[3] - bbox[1] + 16
        px = (_WIDTH - pw) // 2
        py = pill_y - ph // 2
        draw.rounded_rectangle(
            [(px, py), (px + pw, py + ph)],
            radius=ph // 2,
            fill=(255, 255, 255, 15) if not dominant else (dominant[0] // 3, dominant[1] // 3, dominant[2] // 3),
            outline=(*accent, 80) if dominant else (*_ACCENT, 80),
        )
        draw.text((_WIDTH // 2, pill_y), f"♪ {duration}", fill=accent, font=font_pill, anchor="mm")

    # --- Decorative line ---
    line_y = text_y + 200
    line_w = 200
    draw.line(
        [(_WIDTH // 2 - line_w, line_y), (_WIDTH // 2 + line_w, line_y)],
        fill=(*accent, 60), width=2,
    )

    # --- QR code ---
    deep_link = f"https://t.me/{_BOT_USERNAME}?start=tr_{track_id}"
    qr_size = 180
    try:
        qr_img = _make_qr(deep_link, qr_size)
        qr_y = _HEIGHT - 340
        img.paste(qr_img, ((_WIDTH - qr_size) // 2, qr_y))
    except Exception:
        logger.debug("QR code generation failed", exc_info=True)

    # --- Footer ---
    font_footer = _get_font(28)
    draw.text((_WIDTH // 2, _HEIGHT - 110), "Слушай в", fill=_GREY, font=font_footer, anchor="mm")
    font_bot = _get_font(32, bold=True)
    draw.text((_WIDTH // 2, _HEIGHT - 65), f"@{_BOT_USERNAME}", fill=accent, font=font_bot, anchor="mm")

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
