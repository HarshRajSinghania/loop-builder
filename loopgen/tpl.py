"""Render approximate DisplayLink Plus Scoreboard previews from saved NRBF layouts."""

import argparse
import html
import io
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .nrbf import FormatError, Object, Reader

HOME = Path(__file__).resolve().parent
MAX_DIMENSION = 8192
FONT_DIRS = [
    Path("/System/Library/Fonts/Supplemental"),  # macOS
    Path("/Library/Fonts"),
    Path.home() / "Library" / "Fonts",
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",  # Windows
    Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local")) / "Microsoft" / "Windows" / "Fonts",
    Path("/usr/share/fonts/truetype/msttcorefonts"),  # Linux, if installed
]
# File names per family and style (regular, bold, italic, bold italic), Mac name first, then Windows.
FONT_FILES = {
    "arial": (
        ["Arial.ttf", "arial.ttf"],
        ["Arial Bold.ttf", "arialbd.ttf"],
        ["Arial Italic.ttf", "ariali.ttf"],
        ["Arial Bold Italic.ttf", "arialbi.ttf"],
    ),
    "tahoma": (["Tahoma.ttf", "tahoma.ttf"], ["Tahoma Bold.ttf", "tahomabd.ttf"], [], []),
    "arial narrow": (
        ["Arial Narrow.ttf", "ARIALN.TTF"],
        ["Arial Narrow Bold.ttf", "ARIALNB.TTF"],
        ["Arial Narrow Italic.ttf", "ARIALNI.TTF"],
        ["Arial Narrow Bold Italic.ttf", "ARIALNBI.TTF"],
    ),
    "impact": (["Impact.ttf", "impact.ttf"], [], [], []),
}
NARROW = re.compile(r"knockout|condensed|narrow|compressed|gothic|oswald", re.IGNORECASE)


def _files(family, bold, italic):
    styles = FONT_FILES.get(family, ((), (), (), ()))
    names = styles[(1 if bold else 0) + (2 if italic else 0)] or styles[0]
    return [d / n for n in names for d in FONT_DIRS]


def known_font(name, bold, italic):
    """Files for the fonts DisplayLink Plus templates commonly use, on Mac or Windows."""
    return _files(name.strip().lower(), bold, italic) if name.strip().lower() in FONT_FILES else []


@lru_cache(maxsize=None)
def _installed():
    """Every font file in the system font folders, by its family name (read once)."""
    found = {}
    for d in FONT_DIRS:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                family, style = ImageFont.truetype(str(f), 12).getname()
            except OSError:
                continue
            found.setdefault(family.lower(), {})[style.lower()] = f
    return found


def installed_font(name, bold, italic):
    """The font itself, when it's installed (e.g. Knockout on the DisplayLink Plus PC)."""
    styles = _installed().get(name.strip().lower())
    if not styles:
        return None
    want = "bold italic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
    return styles.get(want) or styles.get("regular") or next(iter(styles.values()))


def stand_ins(name, bold, italic):
    """What to draw with when a template's font isn't installed: narrow faces for narrow fonts, else Arial."""
    if NARROW.search(name):
        return _files("arial narrow", True, italic) + _files("impact", False, False) + _files("arial", True, italic)
    return _files("arial", bold, italic) + [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]


def scale_picture(image, size):
    """A template picture at its item's size: smooth (as DisplayLink Plus draws it), with alpha premultiplied
    so transparent edges don't pick up dark fringes."""
    if image.size == tuple(size):
        return image
    return image.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")


KNOWN_COLORS = {27: "transparent", 35: "black", 108: "lime", 164: "white"}


class Renderer:
    """Draws a saved DisplayLink Plus layout as an approximate preview, noting what it couldn't draw exactly."""

    def __init__(self, reader, font_dir=None):
        self.reader = reader
        self.font_dir = font_dir
        self.warnings = set()
        self.fonts = {}

    def field(self, obj, name, default=None):
        return self.reader.field(obj, name, default)

    def color(self, value):
        if value is None:
            return (0, 0, 0, 0)
        state = self.field(value, "state", 0)
        if state & 2:
            argb = self.field(value, "value", 0)
            return ((argb >> 16) & 255, (argb >> 8) & 255, argb & 255, (argb >> 24) & 255)
        known = self.field(value, "knownColor", 0)
        name = KNOWN_COLORS.get(known) if state & 1 else self.field(value, "name")
        if name == "transparent" or state == 0:
            return (0, 0, 0, 0)
        if name is None:
            raise FormatError(f"Unsupported System.Drawing.KnownColor: {known}")
        return ImageColor.getcolor(name, "RGBA")

    def bitmap(self, value):
        value = self.reader.resolve(value)
        if not isinstance(value, Object) or value.class_name != "System.Drawing.Bitmap":
            raise FormatError("Expected an embedded System.Drawing.Bitmap")
        data = self.field(value, "Data")
        if not isinstance(data, bytes):
            raise FormatError("Bitmap has no embedded byte array")
        with Image.open(io.BytesIO(data)) as image:
            return image.convert("RGBA")

    def font(self, item):
        name = self.field(item, "fontName", "")
        bold = self.field(item, "fontBold", False)
        italic = self.field(item, "fontItalic", False)
        pixel_font = re.fullmatch(r"DisplayLink (\d+)x(\d+)", name)
        height = int(pixel_font[2]) if pixel_font else max(1, round(self.field(item, "fontSize", 12) * 96 / 72))
        key = (name, height, bold, italic)
        if key in self.fonts:
            return self.fonts[key], height, bool(pixel_font)
        candidates = []
        if self.font_dir:
            wanted = re.sub(r"[^a-z0-9]", "", name.lower())
            for p in sorted(self.font_dir.iterdir()):
                if p.suffix.lower() in (".ttf", ".otf") and re.sub(r"[^a-z0-9]", "", p.stem.lower()) == wanted:
                    candidates.append(p)
        candidates += known_font(name, bold, italic)
        exact = next((p for p in candidates if p.is_file()), None) or installed_font(name, bold, italic)
        if exact:
            selected = ImageFont.truetype(str(exact), height)
        else:
            self.warnings.add(f"Font substituted: {name}{' (bold)' if bold else ''}{' (italic)' if italic else ''}")
            fallback = next((p for p in stand_ins(name, bold, italic) if p.is_file()), None)
            selected = ImageFont.truetype(str(fallback), height) if fallback else ImageFont.load_default(size=height)
        self.fonts[key] = selected
        return selected, height, bool(pixel_font)

    def geometry(self, item):
        width = self.field(item, "width", 0)
        height = self.field(item, "height", 0) or self.field(item, "Height", 0)
        if not 0 <= width <= MAX_DIMENSION or not 0 <= height <= MAX_DIMENSION:
            raise FormatError(f"Invalid item dimensions: {width} x {height}")
        return self.field(item, "Left", 0), self.field(item, "Top", 0), width, height

    def text(self, item, width, height):
        text = self.field(item, "_textToDraw", "")
        if not isinstance(text, str):
            raise FormatError("Text item contains a non-string text value")
        tile = Image.new("RGBA", (width, height), self.color(self.field(item, "backgroundColor")))
        if not text:
            return tile
        font, line_height, pixel_font = self.font(item)
        if self.field(item, "Scroll", False):
            self.warnings.add("Scrolling text shown as a static, clipped frame")
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        widths = [font.getlength(line) for line in lines]
        measured = max(widths, default=0)
        actual = self.field(item, "ActualWidth", 0)
        # Saved measurements preserve the horizontal footprint of missing fonts.
        factor = actual / measured if actual > 0 and measured > 0 else 1
        ink_height = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
        draw_height = max(1, line_height - 1) if pixel_font else ink_height
        block_height = len(lines) * line_height
        alignment = self.field(self.field(item, "Alignment"), "value__", 1)
        rows = {1: 0, 2: 0, 4: 0, 16: 1, 32: 1, 64: 1, 256: 2, 512: 2, 1024: 2}
        columns = {1: 0, 2: 1, 4: 2, 16: 0, 32: 1, 64: 2, 256: 0, 512: 1, 1024: 2}
        if alignment not in rows:
            raise FormatError(f"Unsupported ContentAlignment: {alignment}")
        top = (height - block_height) * rows[alignment] // 2
        fill = self.color(self.field(item, "dimFontColor" if self.field(item, "fontDim") else "fontColor"))
        outline = self.color(self.field(item, "outlineColor"))
        for index, line in enumerate(lines):
            if not line:
                continue
            bbox = font.getbbox(line)
            padding = 1 if outline[3] else 0
            glyph = Image.new(
                "RGBA",
                (
                    max(1, bbox[2] - bbox[0] + 2 * padding),
                    max(1, bbox[3] - bbox[1] + 2 * padding),
                ),
            )
            ImageDraw.Draw(glyph).text(
                (padding - bbox[0], padding - bbox[1]),
                line,
                font=font,
                fill=fill,
                stroke_width=padding,
                stroke_fill=outline,
            )
            target_width = max(1, round(widths[index] * factor))
            glyph = glyph.resize(
                (target_width, draw_height),
                Image.Resampling.NEAREST if pixel_font else Image.Resampling.LANCZOS,
            )
            left = (width - target_width) * columns[alignment] // 2
            y = top + index * line_height
            tile.alpha_composite(glyph, (left, y))
            if self.field(item, "fontUnderline", False):
                ImageDraw.Draw(tile).line(
                    (left, y + draw_height - 1, left + target_width - 1, y + draw_height - 1),
                    fill=fill,
                )
        return tile

    def render(self, root):
        if not isinstance(root, Object) or root.class_name != "Cts.DisplayLink.Graphics.Templates.Template":
            raise FormatError("Root is not a DisplayLink Plus template")
        width, height = self.field(root, "width"), self.field(root, "height")
        if (
            not isinstance(width, int)
            or not isinstance(height, int)
            or not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION)
        ):
            raise FormatError("Invalid canvas dimensions")
        canvas = Image.new("RGBA", (width, height), self.color(self.field(root, "Background")))
        background = self.field(root, "backgroundGraphic")
        if background is not None:
            canvas.alpha_composite(self.bitmap(background).resize((width, height), Image.Resampling.NEAREST))
        collection = self.field(root, "items")
        array = self.field(collection, "_items")
        size = self.field(collection, "_size", 0)
        if not isinstance(array, list) or not isinstance(size, int) or not 0 <= size <= len(array):
            raise FormatError("Invalid template item collection")
        metadata = []
        for ref in array[:size]:
            item = self.reader.resolve(ref)
            if not isinstance(item, Object):
                raise FormatError("Invalid template item")
            left, top, w, h = self.geometry(item)
            kind = item.class_name.rsplit(".", 1)[-1]
            info = {"type": kind, "left": left, "top": top, "width": w, "height": h}
            if kind in ("TextTemplateItem", "DataTextTemplateItem"):
                info.update(
                    {
                        name: self.field(item, name)
                        for name in (
                            "_textToDraw",
                            "fontName",
                            "fontSize",
                            "fontBold",
                            "fontItalic",
                            "fontUnderline",
                            "Code",
                            "SourceClass",
                            "Index",
                            "Source",
                            "Options",
                            "Scroll",
                            "ScrollOffset",
                        )
                    }
                )
            if w and h:
                if kind in ("TextTemplateItem", "DataTextTemplateItem"):
                    tile = self.text(item, w, h)
                elif kind == "GraphicTemplateItem":
                    tile = scale_picture(self.bitmap(self.field(item, "graphic")), (w, h))
                elif kind == "ShapeTemplateItem":
                    shape = self.field(self.field(item, "shape"), "value__")
                    if shape != 0:
                        raise FormatError(f"Unsupported TemplateShape: {shape}")
                    tile = Image.new("RGBA", (w, h), self.color(self.field(item, "BackgroundColor")))
                    thickness = max(1, round(self.field(item, "thickness", 1)))
                    ImageDraw.Draw(tile).rectangle(
                        (0, 0, w - 1, h - 1),
                        outline=self.color(self.field(item, "OutlineColor")),
                        width=thickness,
                    )
                else:
                    raise FormatError(f"Unsupported template item: {kind}")
                canvas.alpha_composite(tile, (left, top))
            elif kind not in ("TextTemplateItem", "DataTextTemplateItem", "GraphicTemplateItem", "ShapeTemplateItem"):
                raise FormatError(f"Unsupported template item: {kind}")
            metadata.append(info)
        return canvas, {
            "width": width,
            "height": height,
            "description": self.field(root, "Description"),
            "libraries": self.reader.libraries,
            "items": metadata,
            "warnings": sorted(self.warnings),
        }


LIVE_FIELD_NAMES = {  # field code prefixes -> what DisplayLink Plus fills in, in plain words
    "MM_SW_NM": "swimmer names",
    "MM_SW_AF": "teams",
    "MM_SW_ET": "event title",
    "MM_SW_MT": "meet title",
    "MM_DV_NM": "diver name",
    "MM_DV_AF": "diver's team",
    "MM_DV_ET": "diving event",
    "SCBD_SW_": "times and places",
    "SCBD_DV_": "diving scores",
    "SCBD_": "scoreboard data",
    "MM_": "meet data",
}


def live_fields(path):
    """The live data codes (MM_..., SCBD_...) a template's DataText items show, sorted; [] = a static template."""
    reader = Reader(Path(path).read_bytes())
    _, meta = Renderer(reader).render(reader.parse())
    return sorted({i.get("Code") or "?" for i in meta["items"] if i["type"] == "DataTextTemplateItem"})


def describe_fields(codes):
    """['MM_SW_NM', 'SCBD_SW_EV', ...] -> 'swimmer names, times and places'."""
    words = []
    for code in codes:
        word = next((w for prefix, w in LIVE_FIELD_NAMES.items() if code.startswith(prefix)), "live data")
        if word not in words:
            words.append(word)
    return ", ".join(words)


def gallery(output, entries):
    cards = []
    for entry in entries:
        label = html.escape(entry["source"])
        image = html.escape(quote(entry["image"]), quote=True)
        metadata = html.escape(quote(entry["metadata"]), quote=True)
        warnings = "<br>".join(html.escape(w) for w in entry["warnings"])
        cards.append(
            f'<article><h2>{label}</h2><a href="{image}"><img src="{image}" alt="{label}"></a>'
            f'<p>{entry["width"]} x {entry["height"]} pixels &middot; <a href="{metadata}">Layout JSON</a></p>'
            f"<details><summary>Preview limitations</summary>{warnings or 'None recorded'}</details></article>"
        )
    page = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>DisplayLink Plus template previews</title>
<style>
body{background:#181a1d;color:#eee;font:15px system-ui;margin:24px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,640px),1fr));gap:24px}
article{background:#24272b;padding:16px;border-radius:8px;min-width:0}
h2{font-size:16px;overflow-wrap:anywhere}a{color:#9ed4ff}
img{width:100%;height:auto;image-rendering:pixelated;background:repeating-conic-gradient(#333 0% 25%,#444 0% 50%) 0/16px 16px}
details{color:#ccc;font-size:13px}
</style>
<h1>DisplayLink Plus template previews</h1>
<p>Approximate static previews. Text uses saved values, not live timing data.
Missing fonts are substituted; font metrics, wrapping, outlines, scrolling and draw order
have not been compared with DisplayLink Plus's native renderer. Checkerboards indicate transparency.</p>
<main>__CARDS__</main></html>""".replace("__CARDS__", "".join(cards))
    (output / "index.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="A .tpl file or directory (searched recursively)")
    parser.add_argument("--output", type=Path, default=HOME / "previews")
    parser.add_argument("--scale", type=int, default=3, help="Integer PNG enlargement, default 3")
    parser.add_argument("--font-dir", type=Path, help="Optional directory of matching .ttf/.otf fonts")
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not 1 <= args.scale <= 8:
        parser.error("--scale must be between 1 and 8")
    font_dir = args.font_dir.expanduser().resolve() if args.font_dir else None
    if font_dir is not None and not font_dir.is_dir():
        parser.error("--font-dir must be an existing directory")
    if not (source.is_dir() or source.is_file() and source.suffix.lower() == ".tpl"):
        parser.error("input must be an existing .tpl file or directory")  # exits
    if source.is_dir():
        files, base = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() == ".tpl"), source
    else:
        files, base = [source], source.parent
    if not files:
        parser.error("No .tpl files found")
    output.mkdir(parents=True, exist_ok=True)
    entries, failures = [], []
    for path in files:
        relative = path.relative_to(base)
        try:
            reader = Reader(path.read_bytes())
            root = reader.parse()
            image, metadata = Renderer(reader, font_dir).render(root)
            target = output / relative.with_suffix(".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            image.resize((image.width * args.scale, image.height * args.scale), Image.Resampling.NEAREST).save(target)
            metadata["source"] = str(path)
            metadata["scale"] = args.scale
            json_path = target.with_suffix(".json")
            json_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            entries.append(
                {
                    "source": relative.as_posix(),
                    "image": target.relative_to(output).as_posix(),
                    "metadata": json_path.relative_to(output).as_posix(),
                    "width": image.width,
                    "height": image.height,
                    "warnings": metadata["warnings"],
                }
            )
        except (FormatError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            failures.append({"source": str(path), "error": str(exc)})
            print(f"ERROR: {path}: {exc}", file=sys.stderr)
    gallery(output, entries)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "rendered": len(entries),
                "failed": len(failures),
                "entries": entries,
                "failures": failures,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Rendered {len(entries)}/{len(files)} templates. Gallery: {output / 'index.html'}")
    substitutions = sorted({w for e in entries for w in e["warnings"]})
    for warning in substitutions:
        print("WARNING: " + warning, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
