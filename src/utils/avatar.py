"""Generate unique avatar images for account onboarding."""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _initials(first_name: str | None, last_name: str | None) -> str:
    parts = []
    if first_name:
        parts.append(first_name.strip()[0].upper())
    if last_name:
        parts.append(last_name.strip()[0].upper())
    return "".join(parts) or "U"


def generate_avatar(
    first_name: str | None,
    last_name: str | None,
    dest_dir: Path,
    phone: str,
) -> Path:
    """Create a 512x512 avatar PNG with initials on a random pastel background."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{phone.replace('+', '')}.png"

    hue = random.randint(0, 360)
    bg = _hsl_to_rgb(hue, 45, 55)
    fg = _hsl_to_rgb(hue, 30, 95)

    size = 512
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)
    initials = _initials(first_name, last_name)

    try:
        font = ImageFont.truetype("arial.ttf", 180)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 10), initials, fill=fg, font=font)

    img.save(path, "PNG")
    return path


def generate_story_image(
    caption_hint: str,
    dest_dir: Path,
    phone: str,
) -> Path:
    """Create a simple story image (1080x1920) for posting to Telegram stories."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{phone.replace('+', '')}_story.png"

    w, h = 1080, 1920
    hue = random.randint(0, 360)
    bg = _hsl_to_rgb(hue, 35, 45)
    accent = _hsl_to_rgb((hue + 40) % 360, 50, 70)

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([80, 800, w - 80, 1120], fill=accent)

    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        font = ImageFont.load_default()

    text = (caption_hint or "Привет! 👋")[:80]
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) / 2, 940), text, fill=(255, 255, 255), font=font)

    img.save(path, "PNG")
    return path


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    s, l = s / 100, l / 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
