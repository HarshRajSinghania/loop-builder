"""What the API's route modules share: the event open in the editor, the Loop Builder folder (the library), export
jobs, and helpers. One Context per app; each module's register(app, ctx) takes the names it uses from it."""

import copy
import filecmp
import io
import re
import shutil
import threading
import time
from pathlib import Path

import yaml
from fastapi import HTTPException

from loopgen import load_event
from loopgen.checks import full_url
from loopgen.draw import decode_qr
from loopgen.event import DEFAULT_THEME, EventError, read_event_file
from loopgen.slides import Renderer

from app.library import LOOK_COLOURS, LibraryError

STATIC = Path(__file__).resolve().parent.parent / "static"


class Session:
    """The open event: its file, parsed form and a renderer that caches board templates."""

    HISTORY = 50  # undo steps kept for the session

    def __init__(self, path, override=None, default=lambda: None):
        """`override`: a template folder from the command line (developer use); `default()`: the app setting,
        used when the event file names no folder of its own."""
        self.path = Path(path).expanduser().resolve()
        self.override, self.default = override, default
        self.lock = threading.Lock()
        self.undo_stack, self.redo_stack = [], []
        self.reload()

    def reload(self):
        self.data = read_event_file(self.path)  # a malformed file: EventError, so opening it answers 422
        own = self.data.get("templates")
        self.folder_source = "override" if self.override else "event" if own else "settings"
        self.event = load_event(self.path, self.override or (None if own else self.default()))
        self.renderer = Renderer(self.event)

    def loop(self, i):
        try:
            return self.event.loops[i]
        except IndexError as exc:
            raise HTTPException(404, f"no loop {i}") from exc

    def save(self):
        """Write the event file; if the result doesn't load as an event, put the old file back."""
        before = self.path.read_text(encoding="utf-8")
        after = yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True)
        if after == before:
            return
        self.path.write_text(after, encoding="utf-8")
        try:
            self.reload()
        except EventError:
            self.path.write_text(before, encoding="utf-8")
            self.reload()
            raise
        self.undo_stack = (self.undo_stack + [before])[-self.HISTORY :]
        self.redo_stack = []

    def step(self, back):
        """Undo (back=True) or redo one saved change."""
        source, target = (self.undo_stack, self.redo_stack) if back else (self.redo_stack, self.undo_stack)
        if not source:
            return False
        target.append(self.path.read_text(encoding="utf-8"))
        self.path.write_text(source.pop(), encoding="utf-8")
        self.reload()
        return True

    def restore(self, text):
        """Put back a saved version as one undoable change."""
        self.data = yaml.safe_load(text)
        self.save()

    def change(self, edit):
        """Apply `edit(data)` to the event file and save it; on any problem nothing changes."""
        draft = copy.deepcopy(self.data)
        edit(draft)
        self.data = draft
        try:
            self.save()
        except (EventError, IndexError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc


HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def legal_text(name):
    """LICENSE, NOTICE or THIRD_PARTY_NOTICES.md: at the repo root when run from source, in app/legal when packaged."""
    here = Path(__file__).resolve().parent.parent  # app/, as before app/api existed
    for path in (here.parent / name, here / "legal" / name):
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def template_folder_status(folder):
    """Whether a DisplayLink Plus template folder (as typed, ~ allowed) exists, and how many .tpl files it holds:
    {"found", "count"}. The one check behind Settings' live count, the events home and the editor."""
    path = Path(str(folder or "").strip()).expanduser() if str(folder or "").strip() else None
    found = bool(path) and path.is_dir()
    return {"found": found, "count": sum(1 for _ in path.rglob("*.tpl")) if found else 0}


def look_colours(theme):
    """Just the colours of a look, checked: #RRGGBB, upper case."""
    colours = {k: str(v).upper() for k, v in (theme or {}).items() if k in LOOK_COLOURS}
    bad = [k for k, v in colours.items() if not HEX.fullmatch(v)]
    if bad:
        raise HTTPException(422, f"not a colour: {', '.join(bad)}")
    return colours


VERSIONS_KEPT = 20


def keep_version(event_file):
    """Copy the event file into versions/ when exporting, so "what we showed last Thursday" can come back."""
    folder = event_file.parent / "versions"
    folder.mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H.%M.%S")
    shutil.copyfile(event_file, folder / f"{stamp}.yaml")
    for old in sorted(folder.glob("*.yaml"))[:-VERSIONS_KEPT]:
        old.unlink()


def qr_status(slide, img):
    """For QR slides and Text + QR cards: "ok", "fail" (doesn't read back) or "incomplete" (not a full address)."""
    p = slide.props
    url = p.get("url") if slide.type == "qr" else p.get("qr") if p.get("layout") == "text-qr" else None
    if url is None:
        return ""
    if not full_url(url):
        return "incomplete"
    return "ok" if url in decode_qr(img) else "fail"


def png(img, scale=1):
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), 0)
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=1)
    return buf.getvalue()


class Open:  # pylint: disable=too-few-public-methods  # a holder for the open event
    """The event open in the editor, if any."""

    session = None


class _Current:  # pylint: disable=too-few-public-methods  # `s.` in the routes always means the open event
    def __init__(self, current):
        self._open = current

    def __getattr__(self, name):
        if self._open.session is None:
            raise HTTPException(409, "no event is open")
        return getattr(self._open.session, name)


class Context:
    """The state a running app shares between its route modules."""

    def __init__(self, lib, folder_override=None):
        self.lib = lib
        self.folder_override = folder_override  # the template folder given at launch, over the setting
        self.current = Open()
        self.s = _Current(self.current)
        self.jobs = {}
        self.update = {}  # filled in the background at launch, so the home page never waits on the network

    def open_event(self, path):
        self.current.session = Session(path, self.folder_override, lambda: self.lib.settings().get("templates"))

    def event_file_path(self, path):
        """A file inside the open event's folder, never outside it."""
        root = self.s.path.parent.resolve()
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file():
            raise HTTPException(404, "no such picture in this event")
        return target

    def home_lanes(self, data):
        """The lanes in an event's lane slides that show the home team (its logo is assets/teams/_home.*)."""
        for loop in data.get("loops") or []:
            for slide in loop.get("slides") or []:
                for lane in (slide.get("lanes") or {}).get("lanes") or [] if isinstance(slide, dict) else []:
                    if isinstance(lane, dict) and Path(str(lane.get("logo") or "")).stem == self.lib.HOME_TEAM:
                        yield lane

    def look_key(self, data):
        return self.lib.team_look_key(with_name=any(self.home_lanes(data)))

    @staticmethod
    def same_name(shown, team):
        """A lane's name is the team's if only case, spacing or a | line break differ (RIVERSIDE|OTTERS)."""
        return " ".join(str(shown or "").replace("|", " ").split()).upper() == " ".join(team.split()).upper()

    def matches_team_look(self, data, event_folder):
        """Whether an event still has the team theme: the same colours and logo picture, and the home team's
        lanes show the team's name and logo from Settings."""
        theme = data.get("theme") or {}
        colours = {k: str(theme.get(k) or DEFAULT_THEME[k]).upper() for k in LOOK_COLOURS}
        if colours != {k: v.upper() for k, v in self.lib.team_look().items()}:
            return False
        team, name = self.lib.team_logo(), (self.lib.settings().get("team") or "").strip()
        for lane in self.home_lanes(data):
            picture = event_folder / lane["logo"]
            if not self.same_name(lane.get("name"), name) or not (
                team and picture.exists() and filecmp.cmp(picture, team, shallow=False)
            ):
                return False
        if team is None:  # no team logo yet: the look is just the colours
            return True
        logo = theme.get("logo")
        return bool(logo) and (event_folder / logo).exists() and filecmp.cmp(event_folder / logo, team, shallow=False)

    @staticmethod
    def library_call(fn, *args):
        try:
            return fn(*args)
        except (LibraryError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
