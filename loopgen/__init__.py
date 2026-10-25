"""loopgen: render scoreboard loops (WMV videos and PNG stills for DisplayLink Plus) from an event file.

An event file holds a theme and loops; each loop is an ordered list of slides
(board, card, qr, image, countdown, crawl). See examples/ for the format."""

from .event import Event, load_event
from .checks import Issue, run_checks
from .loops import build_clips, existing_exports, export_loop, export_pngs, loop_frames, render_slide, slide_label

__all__ = [
    "Event",
    "Issue",
    "build_clips",
    "existing_exports",
    "export_loop",
    "export_pngs",
    "load_event",
    "loop_frames",
    "render_slide",
    "run_checks",
    "slide_label",
]
