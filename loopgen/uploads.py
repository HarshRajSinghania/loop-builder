"""Pictures added to an event: a working copy, shrunk to what a scoreboard can use.

There's no size limit on what someone picks. Shrinking keeps previews fast (a phone
photo is decoded on every redraw otherwise) and keeps event folders and .loopevent
packages small. The renderer applies the same shrink to anything it opens, so a
preview always matches what an imported picture will draw."""

import io
from collections import deque
from pathlib import Path

from PIL import Image, ImageOps

LONG_SIDE = 2048  # px; enough for a 3x zoom on a 320x176 board
JPEG_QUALITY = 85


class UploadError(ValueError):
    """The file isn't a picture that can be read."""


def shrink(img):
    """Upright, and no more than LONG_SIDE px on its long side."""
    img = ImageOps.exif_transpose(img)
    if max(img.size) > LONG_SIDE:
        img = img.copy()
        img.thumbnail((LONG_SIDE, LONG_SIDE), Image.Resampling.LANCZOS)
    return img


def _has_alpha(img):
    """True only when some pixel is actually see-through, not just an alpha channel that's all opaque."""
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    if img.mode not in ("RGBA", "LA", "PA"):
        return False
    return img.getchannel("A").getextrema()[0] < 255


def encode(img):
    """Shrunk picture as (bytes, extension): PNG when it has transparency, else JPEG."""
    buf = io.BytesIO()
    if _has_alpha(img):
        img.convert("RGBA").save(buf, "PNG", optimize=True)
        return buf.getvalue(), ".png"
    img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), ".jpg"


def trim_white(img, threshold=235):
    """Make the near-white background around a logo transparent (only white connected to the edge, so white
    inside the logo stays), then crop to what's left. For logos saved on a white page."""
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    queue = deque([(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)])
    seen = set()
    while queue:
        x, y = queue.popleft()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        r, g, b, a = px[x, y]
        if a and min(r, g, b) < threshold:
            continue
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen:
                queue.append((nx, ny))
    box = img.getbbox()
    return img.crop(box) if box else img


def prepare_logo(src, out, trim=True, long_side=512):
    """A team logo for lane slides: upright, at most `long_side` px, optionally trimmed of a white page, saved
    as PNG (it needs its transparency)."""
    try:
        img = shrink(Image.open(src))
    except OSError as exc:
        raise UploadError(f"{Path(src).name} isn't a picture Loop Builder can read") from exc
    img = img.convert("RGBA")
    img.thumbnail((long_side, long_side), Image.Resampling.LANCZOS)
    if trim:
        img = trim_white(img)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def prepare_upload(src, out_dir):
    """Shrink and re-encode one picked file into out_dir; returns the working copy's path."""
    src = Path(src)
    try:
        img = shrink(Image.open(src))
    except OSError as exc:
        raise UploadError(f"{src.name} isn't a picture Loop Builder can read") from exc
    data, ext = encode(img)
    out = Path(out_dir) / (src.stem + ext)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out
