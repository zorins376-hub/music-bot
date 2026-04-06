"""
story_cards.py — Generate shareable story cards (1080×1920).

Creates branded images with track info, blurred cover background,
bokeh effects, and QR code deep-link.
"""
import hashlib
import io
import logging
import math
import random
from typing import Optional

logger = logging.getLogger(__name__)

_PIL_AVAILABLE = False
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import qrcode
    _PIL_AVAILABLE = True
except ImportError:
    pass

_WIDTH = 1080
_HEIGHT = 1920
_ACCENT = (200, 160, 255)
_WHITE = (255, 255, 255)
_GREY = (180, 180, 180)
_BOT_USERNAME = "TSmymusicbot_bot"


def _dominant_color(cover_bytes: bytes) -> tuple[int, int, int]:
    """Extract dominant colour from cover image bytes."""
    try:
        cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
        small = cover.resize((40, 40), Image.LANCZOS)
        pixels = list(small.getdata())
        filtered = [(r, g, b) for r, g, b in pixels if (r + g + b) > 60 and (r + g + b) < 700]
        if not filtered:
            filtered = pixels
        avg_r = sum(p[0] for p in filtered) // len(filtered)
        avg_g = sum(p[1] for p in filtered) // len(filtered)
        avg_b = sum(p[2] for p in filtered) // len(filtered)
        return (avg_r, avg_g, avg_b)
    except Exception:
        return (100, 60, 180)


def _build_background(cover_bytes: bytes | None, dominant: tuple[int, int, int] | None) -> "Image.Image":
    """Build a premium background: blurred cover + dark overlay + bokeh circles + dither."""
    import numpy as np

    img = Image.new("RGBA", (_WIDTH, _HEIGHT), (10, 10, 18, 255))

    # Layer 1: Blurred & stretched cover as background
    if cover_bytes:
        try:
            bg_cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
            bg_cover = bg_cover.resize((_WIDTH, _HEIGHT), Image.LANCZOS)
            bg_cover = bg_cover.filter(ImageFilter.GaussianBlur(radius=60))
            img.paste(bg_cover, (0, 0))
        except Exception:
            pass

    # Layer 2: Dark gradient overlay — built via numpy for smooth result
    alpha_arr = np.zeros((_HEIGHT, _WIDTH), dtype=np.float64)
    for y in range(_HEIGHT):
        ratio = y / _HEIGHT
        if ratio < 0.15:
            alpha_arr[y, :] = 220 - ratio / 0.15 * 60
        elif ratio > 0.75:
            alpha_arr[y, :] = 160 + (ratio - 0.75) / 0.25 * 80
        else:
            alpha_arr[y, :] = 160
    # Add ±2 noise to break banding
    noise = np.random.default_rng(seed=7).uniform(-2.0, 2.0, alpha_arr.shape)
    alpha_arr = np.clip(alpha_arr + noise, 0, 255).astype(np.uint8)
    overlay = Image.new("RGBA", (_WIDTH, _HEIGHT), (0, 0, 0, 0))
    overlay.putalpha(Image.fromarray(alpha_arr, mode="L"))
    # Set RGB channels to black
    black = Image.new("RGB", (_WIDTH, _HEIGHT), (0, 0, 0))
    overlay = Image.merge("RGBA", (*black.split(), overlay.split()[3]))
    img = Image.alpha_composite(img, overlay)

    # Layer 3: Radial glow behind cover area — numpy for smooth gradient
    if dominant:
        dr, dg, db = dominant
        cx, cy, max_r = _WIDTH // 2, 620, 500
        ys = np.arange(_HEIGHT, dtype=np.float64)
        xs = np.arange(_WIDTH, dtype=np.float64)
        yy, xx = np.meshgrid(ys, xs, indexing="ij")
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        glow_alpha = np.where(dist < max_r, 40.0 * (1.0 - dist / max_r), 0.0)
        glow_noise = np.random.default_rng(seed=13).uniform(-1.5, 1.5, glow_alpha.shape)
        glow_alpha = np.clip(glow_alpha + glow_noise, 0, 255).astype(np.uint8)
        glow = Image.new("RGBA", (_WIDTH, _HEIGHT), (dr, dg, db, 0))
        glow.putalpha(Image.fromarray(glow_alpha, mode="L"))
        img = Image.alpha_composite(img, glow)

    # Layer 4: Bokeh circles
    bokeh = Image.new("RGBA", (_WIDTH, _HEIGHT), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(bokeh)
    rng = random.Random(42)
    for _ in range(18):
        bx = rng.randint(-100, _WIDTH + 100)
        by = rng.randint(-100, _HEIGHT + 100)
        br = rng.randint(30, 180)
        ba = rng.randint(8, 30)
        bc = (*dominant, ba) if dominant else (200, 160, 255, ba)
        bdraw.ellipse([(bx - br, by - br), (bx + br, by + br)], fill=bc)
    try:
        bokeh = bokeh.filter(ImageFilter.GaussianBlur(radius=15))
    except Exception:
        pass
    img = Image.alpha_composite(img, bokeh)

    # Final dither pass: add ±1 noise to the whole RGB to eliminate any remaining banding
    arr = np.array(img.convert("RGB"), dtype=np.int16)
    final_noise = np.random.default_rng(seed=21).integers(-2, 3, arr.shape, dtype=np.int16)
    arr = np.clip(arr + final_noise, 0, 255).astype(np.uint8)

    return Image.fromarray(arr, "RGB")


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
    """Generate a crisp QR code image at target size."""
    qr = qrcode.QRCode(version=1, box_size=20, border=2, error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="white", back_color="black").convert("RGBA")
    # Make black pixels transparent
    data = qr_img.getdata()
    new_data = [(r, g, b, a) if r > 128 else (0, 0, 0, 0) for r, g, b, a in data]
    qr_img.putdata(new_data)
    # Resize with NEAREST to keep crisp pixels
    return qr_img.resize((size, size), Image.NEAREST)


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

    dominant = _dominant_color(cover_bytes) if cover_bytes else None
    img = _build_background(cover_bytes, dominant)
    draw = ImageDraw.Draw(img)

    # Accent colour from cover
    if dominant:
        dr, dg, db = dominant
        accent = (min(dr + 80, 255), min(dg + 80, 255), min(db + 80, 255))
    else:
        accent = _ACCENT

    # ── Cover image (640×640) with glow ring ──
    cover_size = 640
    cover_x = (_WIDTH - cover_size) // 2
    cover_y = 320

    if cover_bytes:
        try:
            cover = Image.open(io.BytesIO(cover_bytes)).convert("RGBA")
            cover = cover.resize((cover_size, cover_size), Image.LANCZOS)

            # Rounded corners
            mask = Image.new("L", (cover_size, cover_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (cover_size, cover_size)], radius=36, fill=255)

            # Glowing border ring behind cover
            ring = Image.new("RGBA", (cover_size + 16, cover_size + 16), (0, 0, 0, 0))
            ring_draw = ImageDraw.Draw(ring)
            ring_draw.rounded_rectangle(
                [(0, 0), (cover_size + 15, cover_size + 15)],
                radius=40, outline=(*accent, 120), width=4,
            )
            try:
                ring = ring.filter(ImageFilter.GaussianBlur(radius=6))
            except Exception:
                pass
            img.paste(ring, (cover_x - 8, cover_y - 8), ring)

            # Paste cover
            temp = Image.new("RGBA", img.size, (0, 0, 0, 0))
            temp.paste(cover, (cover_x, cover_y), mask)
            img = Image.alpha_composite(img.convert("RGBA"), temp).convert("RGB")
            draw = ImageDraw.Draw(img)
        except Exception:
            _draw_placeholder(draw, cover_y, cover_size)
    else:
        _draw_placeholder(draw, cover_y, cover_size)

    # ── Track info ──
    font_title = _get_font(58, bold=True)
    font_artist = _get_font(44)

    text_y = cover_y + cover_size + 65

    display_title = title[:35] + "…" if len(title) > 35 else title
    draw.text((_WIDTH // 2, text_y), display_title, fill=_WHITE, font=font_title, anchor="mm")

    display_artist = artist[:35] + "…" if len(artist) > 35 else artist
    draw.text((_WIDTH // 2, text_y + 72), display_artist, fill=_GREY, font=font_artist, anchor="mm")

    # Duration pill
    if duration:
        pill_y = text_y + 145
        font_pill = _get_font(30)
        pill_text = f"♪  {duration}"
        bbox = font_pill.getbbox(pill_text)
        pw = bbox[2] - bbox[0] + 48
        ph = bbox[3] - bbox[1] + 20
        px = (_WIDTH - pw) // 2
        py = pill_y - ph // 2
        # Semi-transparent pill background
        pill_bg = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        pill_draw = ImageDraw.Draw(pill_bg)
        pill_draw.rounded_rectangle(
            [(0, 0), (pw - 1, ph - 1)],
            radius=ph // 2,
            fill=(accent[0] // 4, accent[1] // 4, accent[2] // 4, 120),
            outline=(*accent, 70),
        )
        img.paste(pill_bg, (px, py), pill_bg)
        draw = ImageDraw.Draw(img)
        draw.text((_WIDTH // 2, pill_y), pill_text, fill=accent, font=font_pill, anchor="mm")

    # ── Thin decorative line ──
    sep_y = text_y + 215
    line_half = 160
    for x in range(_WIDTH // 2 - line_half, _WIDTH // 2 + line_half):
        dist = abs(x - _WIDTH // 2)
        alpha = int(60 * (1 - dist / line_half))
        draw.point((x, sep_y), fill=(*accent, alpha))

    # ── QR code (crisp) ──
    deep_link = f"https://t.me/{_BOT_USERNAME}?start=tr_{track_id}"
    qr_size = 180
    try:
        qr_img = _make_qr(deep_link, qr_size)
        qr_y = _HEIGHT - 330

        # QR glow
        qr_glow = Image.new("RGBA", (qr_size + 40, qr_size + 40), (0, 0, 0, 0))
        qg_draw = ImageDraw.Draw(qr_glow)
        qg_draw.rounded_rectangle(
            [(0, 0), (qr_size + 39, qr_size + 39)],
            radius=20,
            fill=(accent[0] // 5, accent[1] // 5, accent[2] // 5, 60),
        )
        try:
            qr_glow = qr_glow.filter(ImageFilter.GaussianBlur(radius=10))
        except Exception:
            pass
        img.paste(qr_glow, ((_WIDTH - qr_size) // 2 - 20, qr_y - 20), qr_glow)

        img.paste(qr_img, ((_WIDTH - qr_size) // 2, qr_y), qr_img)
    except Exception:
        logger.debug("QR code generation failed", exc_info=True)

    # ── Footer ──
    draw = ImageDraw.Draw(img)
    font_footer = _get_font(28)
    font_bot = _get_font(32, bold=True)
    draw.text((_WIDTH // 2, _HEIGHT - 100), "Слушай в", fill=_GREY, font=font_footer, anchor="mm")
    draw.text((_WIDTH // 2, _HEIGHT - 55), f"@{_BOT_USERNAME}", fill=accent, font=font_bot, anchor="mm")

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

    img = _build_background(None, None)
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
