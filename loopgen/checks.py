"""Pre-export checks. Errors block an export; warnings don't."""

from dataclasses import dataclass

from . import draw
from .draw import full_url
from .loops import build_clips, loop_length
from .slides import MissingAsset, Renderer

MAX_MINUTES = 30


@dataclass(frozen=True)
class Issue:
    level: str  # "error" or "warning"
    loop: str
    slide: int  # 1-based, 0 for the whole loop
    message: str

    def __str__(self):
        where = f"{self.loop}, slide {self.slide}" if self.slide else self.loop
        return f"{self.level}: {where}: {self.message}"


def _urls(slide):
    if slide.type == "qr":
        return [slide.props.get("url")]
    if slide.type == "card" and slide.props.get("layout") == "text-qr":
        return [slide.props.get("qr")]
    return []


def check_loop(event, loop, renderer=None):
    renderer = renderer or Renderer(event)
    issues = []
    for i, slide in enumerate(loop.slides, 1):
        renderer.issues = []
        try:
            clip = renderer.render(slide, 1)
        except (MissingAsset, ValueError, KeyError) as exc:
            msg = f"missing field {exc}" if isinstance(exc, KeyError) else str(exc)
            issues.append(Issue("error", loop.name, i, msg))
            continue
        for msg in dict.fromkeys(renderer.issues):
            issues.append(Issue("warning", loop.name, i, msg))
        for url in _urls(slide):
            if not url:
                issues.append(Issue("error", loop.name, i, "QR has no URL"))
            elif not full_url(url):
                issues.append(Issue("error", loop.name, i, f"QR link isn't a full web address: {url!r}"))
            elif url not in draw.decode_qr(clip.first):
                issues.append(Issue("error", loop.name, i, f"QR doesn't decode to {url}"))
    if not any(x.level == "error" for x in issues):
        minutes = loop_length(renderer, loop, build_clips(renderer, loop)) / event.fps / 60
        if minutes > MAX_MINUTES:
            issues.append(Issue("warning", loop.name, 0, f"runs {minutes:.0f} minutes"))
    return issues


def run_checks(event, loops=None):
    renderer = Renderer(event)
    return [x for loop in (loops or event.loops) for x in check_loop(event, loop, renderer)]
