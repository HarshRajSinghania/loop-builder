"""Assemble a loop's slides into frames (holds, crossfades, timed slides) and encode it."""

import glob
from pathlib import Path

import av
from PIL import Image

from .slides import Renderer


def build_clips(renderer, loop):
    """One Clip per slide, in play order."""
    return [renderer.render(s, loop.hold if s.hold is None else s.hold) for s in loop.slides]


def fade_frames(renderer, loop, i):
    s = loop.slides[i]
    return round((loop.fade if s.fade is None else s.fade) * renderer.fps)


def loop_frames(renderer, loop, clips=None):
    """Yield (image, count) runs for the whole loop. Stills crossfade into the next slide;
    Countdown and Crawl cut in and out. With repeat on, the last slide fades back to the first."""
    clips = clips or build_clips(renderer, loop)
    n = len(clips)
    for i, clip in enumerate(clips):
        yield from clip.runs()
        if i == n - 1 and not (loop.repeat and n > 1):
            break
        nxt = clips[(i + 1) % n]
        if clip.timed or nxt.timed:
            continue
        f = fade_frames(renderer, loop, i)
        for k in range(1, f + 1):
            yield Image.blend(clip.last, nxt.first, k / (f + 1)), 1


def loop_length(renderer, loop, clips):
    """Frames in the loop, fades included, without rendering it."""
    n = len(clips)
    total = sum(c.frames for c in clips)
    for i, clip in enumerate(clips):
        if i == n - 1 and not (loop.repeat and n > 1):
            break
        if not (clip.timed or clips[(i + 1) % n].timed):
            total += fade_frames(renderer, loop, i)
    return total


def _encoder(container, codec, event, scale, bitrate=None):
    stream = container.add_stream(codec, rate=event.fps)
    stream.width, stream.height = event.width * scale, event.height * scale
    stream.pix_fmt = "yuv420p"
    if bitrate:
        stream.bit_rate = bitrate
    else:
        stream.options = {"crf": "16"}
    return stream


def export_loop(event, loop, out_dir, preview_mp4=False, renderer=None, progress=None):
    """Write `<loop name>.wmv` (and a 4x review MP4 if asked); return the paths written.

    Frames go straight to FFmpeg's encoders through PyAV, so no separate FFmpeg program is needed.
    `progress(fraction)` is called as frames are written."""
    renderer = renderer or Renderer(event)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clips = build_clips(renderer, loop)
    total = max(1, loop_length(renderer, loop, clips))
    bitrate = 1_000_000 if any(c.timed for c in clips) else 2_000_000
    wmv, mp4 = _video_files(loop, out_dir)
    outputs = [(av.open(str(wmv), "w"), "wmv2", 1, bitrate)]
    if preview_mp4:
        outputs.append((av.open(str(mp4), "w"), "libx264", 4, None))
    streams = [(c, _encoder(c, codec, event, scale, rate), scale) for c, codec, scale, rate in outputs]
    try:
        n = 0
        for img, count in loop_frames(renderer, loop, clips):
            frames = [
                (
                    stream,
                    av.VideoFrame.from_image(
                        img
                        if scale == 1
                        else img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
                    ),
                )
                for _, stream, scale in streams
            ]
            for _ in range(count):
                for (container, _, _), (stream, frame) in zip(streams, frames):
                    frame.pts = n
                    container.mux(stream.encode(frame))
                n += 1
            if progress:
                progress(n / total)
        for container, stream, _ in streams:
            container.mux(stream.encode())
    finally:
        for container, _, _ in streams:
            container.close()
    return [wmv, mp4] if preview_mp4 else [wmv]


def slide_label(slide):
    """A short name for a slide: shown in the editor's strip and used in exported file names."""
    p = slide.props
    if slide.type == "board":
        return Path(str(p.get("template", ""))).stem
    if slide.type == "card":
        lines = p.get("lines") or []
        big = next((l for l in lines if l.get("size") == "L"), lines[0] if lines else {})
        return str(big.get("text", "Card"))
    if slide.type == "qr":
        return " ".join(p.get("heading") or []) or p.get("url", "QR")
    if slide.type == "image":
        return Path(str(p.get("file", "Image"))).stem
    if slide.type == "countdown":
        return f"{p.get('label', 'Countdown')} {p.get('length', '')}".strip()
    if slide.type == "crawl":
        return "".join(s.get("text", "") for s in p.get("segments") or []).strip() or "Crawl"
    if slide.type == "lanes":
        return str(p.get("title") or "Lane assignments")
    return slide.type


_NOT_IN_FILE_NAMES = '\\/:*?"<>|'  # on Windows; a Mac takes all but / and :


def _file_safe(text):
    """Text usable in a file name on Windows and Mac."""
    cleaned = "".join("-" if c in _NOT_IN_FILE_NAMES else c for c in text).strip(" .")
    return " ".join(cleaned.split())[:60] or "slide"


def _video_files(loop, out_dir):
    """The WMV and review MP4 for `loop`: named after it, with any character a file name can't hold made a dash
    ("Raffle: 10/12" → "Raffle- 10-12.wmv"). Not shortened, so a WMV the scoreboard already plays keeps its name."""
    name = "".join("-" if c in _NOT_IN_FILE_NAMES else c for c in loop.name).strip(" .") or "loop"
    return out_dir / f"{name}.wmv", out_dir / f"{name} (preview).mp4"


def existing_exports(loop, out_dir, formats=("wmv",), preview_mp4=False):
    """The files an export of `loop` into `out_dir` would replace: its WMV, its review MP4, and the PNGs an earlier
    export left under its name. Names only, nothing is rendered, so the editor can ask before replacing them."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    found = []
    wmv, mp4 = _video_files(loop, out_dir)
    if "wmv" in formats or preview_mp4:
        found.append(wmv)
    if preview_mp4:
        found.append(mp4)
    if "png" in formats:
        found += sorted(out_dir.glob(f"{glob.escape(_file_safe(loop.name))} [0-9][0-9] - *.png"))
    return [p for p in found if p.is_file()]


def export_pngs(event, loop, out_dir, renderer=None):
    """Write one board-size PNG per still slide, for the DisplayLink Plus library or a sequence.

    Countdowns, crawls and panning images move, so they have no single picture: they are
    returned as skipped (slide number, reason) and stay WMV-only. Returns (paths, skipped)."""
    renderer = renderer or Renderer(event)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, skipped = [], []
    for i, (slide, clip) in enumerate(zip(loop.slides, build_clips(renderer, loop)), 1):
        if clip.timed or clip.first is not clip.last:
            skipped.append((i, f"{slide.type} moves, so it's in the WMV only"))
            continue
        path = out_dir / f"{_file_safe(loop.name)} {i:02d} - {_file_safe(slide_label(slide))}.png"
        clip.first.convert("RGB").save(path, optimize=True)
        written.append(path)
    return written, skipped


def render_slide(event, loop, index, at=None, renderer=None):
    """One slide as a still: its first frame, or the frame `at` seconds into a timed or panning slide."""
    renderer = renderer or Renderer(event)
    slide = loop.slides[index]
    clip = renderer.render(slide, loop.hold if slide.hold is None else slide.hold)
    if at is None:
        return clip.first
    target = round(at * event.fps)
    if clip.seek:
        return clip.seek(target)
    seen = 0
    for img, count in clip.runs():
        if seen + count > target:
            return img
        seen += count
    return clip.last
