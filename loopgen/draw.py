"""Fonts, fitted text and QR codes at board resolution."""

import os
import re
from functools import lru_cache
from pathlib import Path

import qrcode
import zxingcpp
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).with_name("fonts")
SUPPLEMENTAL = Path("/System/Library/Fonts/Supplemental")
LINUX = [
    Path("/usr/share/fonts/truetype/croscore"),
    Path("/usr/share/fonts/truetype/arimo"),
    Path("/usr/share/fonts/opentype/arimo"),
    Path("/usr/share/fonts/truetype/liberation"),
]
# family -> weight -> candidate files, first found wins. Arimo has Arial's metrics, so fitting matches.
WINDOWS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
FAMILIES = {
    "arial": {
        "regular": [
            SUPPLEMENTAL / "Arial.ttf",
            WINDOWS / "arial.ttf",
            *(d / "Arimo-Regular.ttf" for d in [FONT_DIR, *LINUX]),
            LINUX[3] / "LiberationSans-Regular.ttf",
        ],
        "bold": [
            SUPPLEMENTAL / "Arial Bold.ttf",
            WINDOWS / "arialbd.ttf",
            *(d / "Arimo-Bold.ttf" for d in [FONT_DIR, *LINUX]),
            LINUX[3] / "LiberationSans-Bold.ttf",
        ],
    },
}
FAMILIES["arimo"] = {w: [p for p in paths if "Arial" not in p.name] for w, paths in FAMILIES["arial"].items()}
MIN_SIZE = 10


@lru_cache(maxsize=None)
def font_path(family, weight):
    for p in FAMILIES.get(family.lower(), FAMILIES["arial"])[weight]:
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"no {weight} font for {family!r}; put Arimo-{weight.title()}.ttf in {FONT_DIR}")


@lru_cache(maxsize=4096)
def font(family, weight, size):
    return ImageFont.truetype(font_path(family, weight), size)


_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def width(text, f, stroke=0):
    return _MEASURE.textlength(text, font=f) + 2 * stroke


def fit(family, weight, text, size, max_w, stroke=0):
    """Largest font from `size` down to MIN_SIZE that fits max_w; (font, too_long)."""
    while size > MIN_SIZE and width(text, font(family, weight, size), stroke) > max_w:
        size -= 1
    f = font(family, weight, size)
    return f, width(text, f, stroke) > max_w


def line_height(f, stroke=0):
    ascent, descent = f.getmetrics()
    return ascent + descent + 2 * stroke


def text_centred(d, cx, y, text, f, fill, stroke=0, stroke_fill=None):
    d.text(
        (round(cx - width(text, f) / 2), y + stroke),
        text,
        font=f,
        fill=fill,
        stroke_width=stroke,
        stroke_fill=stroke_fill,
    )


def distribute(top, bottom, heights, max_gap):
    """Top y of each item, spread evenly between top and bottom (gap capped, block centred)."""
    free = bottom - top - sum(heights)
    gap = min(free / (len(heights) - 1), max_gap) if len(heights) > 1 else 0
    y = top + (free - gap * (len(heights) - 1)) / 2
    out = []
    for h in heights:
        out.append(round(y))
        y += h + gap
    return out


FULL_URL = re.compile(r"^https?://[^\s/.]+(\.[^\s/.]+)+(/\S*)?$", re.IGNORECASE)  # any case: links are kept as typed


def full_url(url):
    """A web address someone can actually open: scheme, a host with a dot, no spaces."""
    return bool(url and FULL_URL.match(url))


def short_url(url):
    """A link as people read it: no https://, www. or trailing slash."""
    return url.split("://", 1)[-1].removeprefix("www.").removeprefix("WWW.").rstrip("/")


def qr_modules(url):
    """The code as a 1-px-per-module image, quiet zone of 2 modules included (error correction M)."""
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=2)
    q.add_data(url)
    q.make(fit=True)
    return q.make_image(fill_color="black", back_color="white").convert("RGB")


def qr_image(url, max_px):
    """Crisp code at the largest whole number of board pixels per module within max_px; (image, px)."""
    m = qr_modules(url)
    px = max(1, max_px // m.width)
    return m.resize((m.width * px, m.height * px), Image.Resampling.NEAREST), px


def decode_qr(img):
    """Every QR payload found in a board image (scaled up first so small modules decode)."""
    big = img.convert("RGB").resize((img.width * 4, img.height * 4), Image.Resampling.NEAREST)
    return {r.text for r in zxingcpp.read_barcodes(big) if r.format.name.startswith("QR")}
