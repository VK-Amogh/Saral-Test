"""
Saral AI — Mock Portal CAPTCHA Generator
File: mock_portal/captcha.py

Generates distorted 6-character PNG CAPTCHA images simulating
the UIDAI portal challenge with noise, wave distortion, and jitter.
"""

import io
import math
import random
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Character set excluding confusing glyphs (0, O, 1, I)
CAPTCHA_CHARSET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

# Fallback minimal 1x1 valid PNG if Pillow is unavailable
FALLBACK_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def generate_random_captcha_text(length: int = 6) -> str:
    """Generate a random alphanumeric CAPTCHA text string."""
    return "".join(random.choice(CAPTCHA_CHARSET) for _ in range(length))


def generate_captcha_image(
    text: str = "VALID_CAP",
    width: int = 200,
    height: int = 70,
    noise_level: int = 4
) -> bytes:
    """Generate a realistic distorted PNG CAPTCHA image for the given text.

    Args:
        text: The text solution for the CAPTCHA (default: 'VALID_CAP').
        width: Image width in pixels.
        height: Image height in pixels.
        noise_level: Intensity of background lines and dots.

    Returns:
        bytes: Binary PNG image data.
    """
    if not PIL_AVAILABLE:
        return FALLBACK_PNG

    # 1. Base image with light grayish background
    bg_color = (245, 247, 250)
    image = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(image)

    # 2. Add background noise lines
    for _ in range(noise_level * 3):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        line_color = (random.randint(180, 220), random.randint(180, 220), random.randint(180, 220))
        draw.line([(x1, y1), (x2, y2)], fill=line_color, width=random.randint(1, 2))

    # 3. Add background dots / noise points
    for _ in range(width * height // 25):
        px = random.randint(0, width - 1)
        py = random.randint(0, height - 1)
        dot_color = (random.randint(170, 210), random.randint(170, 210), random.randint(170, 210))
        draw.point((px, py), fill=dot_color)

    # 4. Load font (system default or fallback)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    # 5. Render characters with jitter
    num_chars = len(text)
    char_slot_width = (width - 30) / max(num_chars, 1)

    for i, char in enumerate(text):
        char_x = int(15 + i * char_slot_width + random.randint(-2, 3))
        char_y = int(height / 2 - 12 + random.randint(-4, 4))
        text_color = (
            random.randint(20, 70),
            random.randint(20, 70),
            random.randint(40, 100)
        )

        # Create isolated char tile to allow rotation
        char_tile = Image.new("RGBA", (40, 40), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_tile)
        char_draw.text((10, 8), char, fill=text_color, font=font)

        # Rotate character
        angle = random.randint(-18, 18)
        rotated_tile = char_tile.rotate(angle, resample=Image.Resampling.BILINEAR, expand=0)

        # Paste onto main image using alpha mask
        image.paste(rotated_tile, (char_x - 10, char_y - 8), rotated_tile)

    # 6. Foreground interference lines across characters
    for _ in range(2):
        x1 = random.randint(0, 20)
        y1 = random.randint(10, height - 10)
        x2 = random.randint(width - 25, width)
        y2 = random.randint(10, height - 10)
        strike_color = (random.randint(100, 160), random.randint(100, 160), random.randint(120, 180))
        draw.line([(x1, y1), (x2, y2)], fill=strike_color, width=1)

    # 7. Apply gentle blur
    image = image.filter(ImageFilter.SMOOTH_MORE)

    # 8. Encode to PNG
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
