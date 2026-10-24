"""Local API for Loop Builder: the events home and settings, and for the open event its previews,
checks, edits and exports.

Runs on 127.0.0.1 only. The pages (app/static) are served from the same origin."""

import copy
import filecmp
import io
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from urllib.parse import quote
from pathlib import Path

import yaml
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from loopgen import export_loop, export_pngs, load_event, run_checks, slide_label
from loopgen.checks import full_url
from loopgen import tpl
from loopgen.draw import decode_qr
from loopgen.event import DEFAULT_THEME, Event, EventError, Loop, _slide
from loopgen.loops import build_clips, loop_length, render_slide
from loopgen.slides import MissingAsset, Renderer
from loopgen.uploads import UploadError, prepare_upload

from app.library import LOOK_COLOURS, STARTERS, Library, LibraryError
from app.updates import check_for_update
from app.version import RELEASES_URL, VERSION

STATIC = Path(__file__).with_name("static")


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
        self.data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
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


THEME_KEYS = ("primary", "accent", "text", "muted", "background", "logo", "font")
HEX = re.compile(r"#[0-9A-Fa-f]{6}")


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


class SlideBody(BaseModel):
    """A slide sent from the editor: a draft to preview, or a change to save."""

    loop: int
    n: int
    slide: dict  # one event-file slide, e.g. {"card": {...}}
    at: float | None = None


class LoopBody(BaseModel):
    """A whole loop from the editor: its settings and slides in play order."""

    name: str
    hold: float = 10.0
    fade: float = 0.5
    slides: list[dict]


class SettingsBody(BaseModel):
    """Settings the home screen and Settings dialog change; a field left out stays as it is."""

    team: str | None = None
    templates: str | None = None
    export_dir: str | None = None
    pool_lanes: int | None = None
    first_lane: int | None = None
    theme: dict | None = None  # the team theme: colours only (the logo has its own upload)


class NewEventBody(BaseModel):
    """A new event from a starter, or a copy of an existing one."""

    name: str
    date: str | None = None
    starter: str = "dual-meet"


class ThemeBody(BaseModel):
    """The open event's own theme (its colours); Settings holds the team theme new events start from."""

    theme: dict


class LookBody(BaseModel):
    """Colours to preview in Settings, before they're saved."""

    theme: dict


class CopyBody(BaseModel):
    """Copy slide `n` of `loop` to the end of another loop."""

    loop: int
    n: int
    target: int


class FolderBody(BaseModel):
    """A DisplayLink Plus template folder for the open event; `make_default` also sets it for new events."""

    folder: str
    make_default: bool = False


class PanelBody(BaseModel):
    """The rectangle of a board template that a countdown or crawl may draw in: [x, y, width, height] in board px."""

    template: str
    panel: list[int]


class PathBody(BaseModel):
    """A file path chosen with the app's own Save dialog."""

    path: str


class ExportBody(BaseModel):
    """Which loops to export, and to which folder."""

    loops: list[int]
    out_dir: str
    formats: list[str] = ["wmv"]  # "wmv" (video) and/or "png" (one still per slide)
    preview_mp4: bool = False


class Open:
    """The event open in the editor, if any."""

    session = None


def create_app(event_path=None, templates=None, library=None):
    """`event_path` opens one event straight away (developer use); otherwise the app starts on the events home.
    `templates` overrides the DisplayLink Plus template folder setting."""
    folder_override = templates  # its own name, so no endpoint function below can shadow it
    lib = library or Library()
    current = Open()
    jobs = {}
    app = FastAPI(title="Loop Builder")

    def open_event(path):
        current.session = Session(path, folder_override, lambda: lib.settings().get("templates"))

    if event_path:
        open_event(event_path)

    update = {}  # filled in the background at launch, so the home page never waits on the network
    if RELEASES_URL:
        threading.Thread(
            target=lambda: update.update(check_for_update(VERSION, RELEASES_URL) or {}), daemon=True
        ).start()

    class _Current:  # `s.` below always means the open event
        def __getattr__(self, name):
            if current.session is None:
                raise HTTPException(409, "no event is open")
            return getattr(current.session, name)

    s = _Current()

    # ---------- home, events and settings ----------

    @app.get("/api/home")
    def home():
        settings = lib.settings()
        return {
            "settings": {k: settings[k] for k in ("team", "templates", "export_dir", "pool_lanes", "first_lane")}
            | {"logo": bool(settings["logo"]), "theme": lib.team_look()},
            "templates_found": bool(settings["templates"]) and Path(settings["templates"]).is_dir(),
            "template_count": (
                sum(1 for _ in Path(settings["templates"]).rglob("*.tpl"))
                if settings["templates"] and Path(settings["templates"]).is_dir()
                else 0
            ),
            "events": lib.events(),
            "starters": [{"id": k, "title": v["title"], "about": v["about"]} for k, v in STARTERS.items()],
            "open": current.session.path.parent.name if current.session else None,
            "folder": str(lib.root),
            "version": VERSION,
            "update": update or None,
        }

    @app.put("/api/settings")
    def save_settings(body: SettingsBody):
        changes = body.model_dump(exclude_none=True)
        if "pool_lanes" in changes and not 1 <= changes["pool_lanes"] <= 10:
            raise HTTPException(422, "a pool has 1 to 10 lanes")
        if "first_lane" in changes and changes["first_lane"] not in (0, 1):
            raise HTTPException(422, "lanes are numbered from 0 or 1")
        if "templates" in changes and changes["templates"] and not Path(changes["templates"]).expanduser().is_dir():
            raise HTTPException(422, f"folder not found: {changes['templates']}")
        if "theme" in changes:
            changes["theme"] = look_colours(changes["theme"])
        before = lib.settings().get("templates")
        settings = lib.update_settings(**changes)
        if current.session and settings.get("templates") != before:
            with current.session.lock:
                current.session.reload()  # redraw boards from the new folder; undo history stays
        return settings

    @app.post("/api/settings/logo")
    def team_logo(file: UploadFile):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / Path(file.filename or "logo").name
            src.write_bytes(file.file.read())
            try:
                lib.set_logo(prepare_upload(src, Path(tmp) / "shrunk"))
            except UploadError as exc:
                raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    @app.get("/api/teams")
    def list_teams():
        return lib.teams()

    @app.post("/api/teams")
    def add_team(file: UploadFile, name: str = Form(...), trim: bool = Form(True)):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / Path(file.filename or "logo").name
            src.write_bytes(file.file.read())
            try:
                team_id = lib.add_team(name, src, trim)
            except (LibraryError, UploadError) as exc:
                raise HTTPException(422, str(exc)) from exc
        return {"id": team_id}

    @app.put("/api/teams/{team_id}")
    def rename_team(team_id: str, body: NewEventBody):
        library_call(lib.rename_team, team_id, body.name)
        return {"ok": True}

    @app.delete("/api/teams/{team_id}")
    def delete_team(team_id: str):
        library_call(lib.delete_team, team_id)
        return {"ok": True}

    @app.get("/api/teams/{team_id}/logo")
    def team_logo_png(team_id: str):
        team = next((t for t in lib.teams() if t["id"] == team_id), None)
        if team is None:
            raise HTTPException(404, "no such team")
        return FileResponse(lib.team_logo_path(team), headers={"Cache-Control": "no-store"})

    @app.post("/api/teams/{team_id}/use")
    def use_team(team_id: str):
        """Copy a team's logo into the open event, for a lane; returns the lane's name and logo path."""
        return library_call(lib.use_team, team_id, s.path.parent)

    @app.get("/api/team/logo")
    def team_logo_file():
        logo = lib.settings().get("logo")
        if not logo or not (lib.root / logo).exists():
            raise HTTPException(404, "no team logo yet")
        return FileResponse(lib.root / logo, headers={"Cache-Control": "no-store"})

    def matches_team_look(theme, event_folder):
        """Whether an event still has the team theme: the same colours and the same logo picture."""
        colours = {k: str(theme.get(k) or DEFAULT_THEME[k]).upper() for k in LOOK_COLOURS}
        if colours != {k: v.upper() for k, v in lib.team_look().items()}:
            return False
        logo, team = theme.get("logo"), lib.team_logo()
        if team is None:  # no team logo yet: the look is just the colours
            return True
        return bool(logo) and (event_folder / logo).exists() and filecmp.cmp(event_folder / logo, team, shallow=False)

    def library_call(fn, *args):
        try:
            return fn(*args)
        except (LibraryError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/events")
    def new_event(body: NewEventBody):
        return {"slug": library_call(lib.create, body.name, body.starter, body.date)}

    @app.post("/api/events/{slug}/duplicate")
    def duplicate_event(slug: str, body: NewEventBody):
        return {"slug": library_call(lib.duplicate, slug, body.name, body.date)}

    @app.post("/api/events/{slug}/open")
    def open_slug(slug: str):
        path = library_call(lib.event_file, slug)
        try:
            open_event(path)
        except EventError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    @app.get("/api/events/{slug}/thumb.png")
    def event_thumb(slug: str):
        """The event's first slide, for its row on the home screen."""
        try:
            path = library_call(lib.event_file, slug)
            own = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("templates")
            event = load_event(path, folder_override or (None if own else lib.settings().get("templates")))
            first = event.loops[0].slides[0]
            img = render_slide(event, event.loops[0], 0, 3.0 if first.type == "crawl" else None)
        except (EventError, MissingAsset, ValueError, KeyError, IndexError):
            return Response(status_code=204)
        return Response(png(img), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/events/import")
    def import_event(file: UploadFile):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / Path(file.filename or "event.loopevent").name
            package.write_bytes(file.file.read())
            try:
                return {"slug": lib.import_package(package)}
            except (LibraryError, OSError, zipfile.BadZipFile) as exc:
                raise HTTPException(422, f"couldn't import: {exc}") from exc

    @app.post("/api/events/{slug}/package")
    def save_package(slug: str, body: PathBody):
        return {"file": str(library_call(lib.export_package, slug, Path(body.path).expanduser()))}

    @app.get("/api/events/{slug}/package")
    def download_package(slug: str):
        tmp = Path(tempfile.mkdtemp())
        dest = library_call(lib.export_package, slug, tmp / slug)
        return FileResponse(dest, filename=dest.name, media_type="application/zip")

    # ---------- the open event ----------

    @app.get("/api/event")
    def event():
        loops = []
        for i, loop in enumerate(s.event.loops):
            try:
                length = loop_length(s.renderer, loop, build_clips(s.renderer, loop)) / s.event.fps
            except (MissingAsset, ValueError, KeyError):
                length = None
            raw = s.data["loops"][i]["slides"]
            loops.append(
                {
                    "name": loop.name,
                    "hold": loop.hold,
                    "fade": loop.fade,
                    "repeat": loop.repeat,
                    "length": length,
                    "slides": [
                        {
                            "type": sl.type,
                            "label": slide_label(sl),
                            "hold": sl.hold,
                            "timed": sl.timed,
                            "id": sl.id,
                            "raw": raw[j],
                        }
                        for j, sl in enumerate(loop.slides)
                    ],
                }
            )
        uses = {}
        for lp in s.data["loops"]:
            for raw in lp.get("slides") or []:
                props = next(iter(raw.values())) or {}
                key = props.get("ref") or props.get("id")
                if key:
                    uses[key] = uses.get(key, 0) + 1
        for lp in loops:
            for sl in lp["slides"]:
                props = next(iter(sl["raw"].values())) or {}
                key = props.get("ref") or props.get("id")
                sl["linked"] = uses.get(key, 0) if key and uses.get(key, 0) > 1 else 0
        team_look = matches_team_look(s.data.get("theme") or {}, s.path.parent)
        return {
            "theme": s.data.get("theme") or {},
            "team_look": team_look,
            # offer the team theme unless the event has it, or kept its own while the team theme was as it is now
            "offer_team_theme": not team_look and s.data.get("own_theme") != lib.team_look_key(),
            "panels": s.event.panels,
            "templates_folder": str(s.event.templates),
            "templates_found": s.event.templates.is_dir(),
            "templates_set": s.folder_source != "settings" or bool(s.default()),  # else none chosen yet
            "templates_source": s.folder_source,
            "can_undo": bool(s.undo_stack),
            "can_redo": bool(s.redo_stack),
            "slug": s.path.parent.name,
            "name": s.event.name,
            "date": s.event.date,
            "width": s.event.width,
            "height": s.event.height,
            "loops": loops,
        }

    @app.get("/api/slide.png")
    def slide_png(loop: int, n: int, at: float | None = None, scale: int = 1):
        start = time.perf_counter()
        with s.lock:
            lp = s.loop(loop)
            if not 0 <= n < len(lp.slides):
                raise HTTPException(404, f"no slide {n}")
            if at is None and lp.slides[n].type == "crawl":
                at = 3.0  # a crawl's first frame is empty (the text enters from the right): show it under way
            s.renderer.issues = []  # only this slide's warnings
            try:
                img = render_slide(s.event, lp, n, at, s.renderer)
            except (MissingAsset, ValueError, KeyError) as exc:
                raise HTTPException(422, str(exc)) from exc
            qr = qr_status(lp.slides[n], img) if scale > 1 else ""  # only for the big preview, not thumbnails
            issues = quote(" | ".join(dict.fromkeys(s.renderer.issues))[:500])
        ms = (time.perf_counter() - start) * 1000
        return Response(
            png(img, max(1, min(scale, 4))),
            media_type="image/png",
            headers={"X-Render-Ms": f"{ms:.0f}", "X-QR": qr, "X-Issues": issues, "Cache-Control": "no-store"},
        )

    @app.post("/api/render")
    def render_draft(body: SlideBody):
        """Render an edited slide without saving it: the live preview while someone types."""
        start = time.perf_counter()
        with s.lock:
            lp = copy.copy(s.loop(body.loop))
            try:
                draft = _slide(body.slide, "draft")
                s.renderer.issues = []  # only this draft's warnings
                lp.slides = list(lp.slides)
                lp.slides[body.n] = draft
                img = render_slide(s.event, lp, body.n, body.at, s.renderer)
            except (EventError, MissingAsset, ValueError, KeyError, IndexError) as exc:
                raise HTTPException(422, str(exc)) from exc
            issues = list(dict.fromkeys(s.renderer.issues))
            s.renderer.issues = []
            qr = qr_status(draft, img)
        ms = (time.perf_counter() - start) * 1000
        return Response(
            png(img, 3),
            media_type="image/png",
            headers={
                "X-Render-Ms": f"{ms:.0f}",
                "X-Issues": quote(" | ".join(issues)[:500]),  # headers are latin-1 only: send it percent-encoded
                "X-QR": qr,
                "Cache-Control": "no-store",
            },
        )

    @app.put("/api/slide")
    def save_slide(body: SlideBody):
        with s.lock:
            try:
                _slide(body.slide, "slide")
            except EventError as exc:
                raise HTTPException(422, str(exc)) from exc
            s.change(lambda d: d["loops"][body.loop]["slides"].__setitem__(body.n, body.slide))
        return {"ok": True}

    @app.put("/api/loops/{i}")
    def save_loop(i: int, body: LoopBody):
        """Reorder, add, duplicate or delete slides, or change the loop's settings: the editor sends the loop whole."""

        def edit(d):
            d["loops"][i].update({"name": body.name, "hold": body.hold, "fade": body.fade})
            d["loops"][i].pop("repeat", None)  # no longer a setting: see Loop.repeat
            d["loops"][i]["slides"] = body.slides

        with s.lock:
            s.loop(i)
            s.change(edit)
        return {"ok": True}

    @app.post("/api/loops")
    def add_loop(body: LoopBody):
        with s.lock:
            s.change(lambda d: d["loops"].append(body.model_dump()))
        return {"index": len(s.event.loops) - 1}

    @app.delete("/api/loops/{i}")
    def delete_loop(i: int):
        with s.lock:
            s.loop(i)
            if len(s.event.loops) == 1:
                raise HTTPException(422, "an event keeps at least one loop")
            s.change(lambda d: d["loops"].pop(i))
        return {"ok": True}

    @app.post("/api/undo")
    def undo():
        with s.lock:
            return {"changed": s.step(True)}

    @app.post("/api/redo")
    def redo():
        with s.lock:
            return {"changed": s.step(False)}

    @app.put("/api/theme")
    def save_theme(body: ThemeBody):
        colours = look_colours(body.theme)
        with s.lock:
            key = lib.team_look_key()
            s.change(lambda d: d.update(theme={**(d.get("theme") or {}), **colours}, own_theme=key))
        return {"ok": True}

    @app.post("/api/theme/keep")
    def keep_theme():
        """Keep the open event's theme though it differs from the team theme as it is now (undoable)."""
        key = lib.team_look_key()
        with s.lock:
            s.change(lambda d: d.__setitem__("own_theme", key))
        return {"ok": True}

    @app.post("/api/theme/reset")
    def reset_theme():
        """Give the open event the team theme again: its colours and a fresh copy of the team logo (undoable)."""
        logo = lib.copy_team_logo(s.path.parent)

        def edit(d):
            theme = {**(d.get("theme") or {}), **lib.team_look()}
            if logo:
                theme["logo"] = logo
            d["theme"] = theme
            d.pop("own_theme", None)

        with s.lock:
            s.change(edit)
        return {"ok": True}

    @app.post("/api/settings/preview")
    def preview_look(body: LookBody):
        """A sample welcome card in some colours and the team logo, drawn by the real renderer."""
        logo = lib.team_logo()
        theme = {**DEFAULT_THEME, **lib.team_look(), **look_colours(body.theme), "logo": str(logo) if logo else None}
        card = _slide(
            {
                "card": {
                    "layout": "logo-center" if logo else "stack",
                    "lines": [
                        {"text": "Welcome", "size": "M", "style": "outlined"},
                        {"text": "VISITING TEAM", "size": "L", "style": "outlined"},
                        {"text": "Thanks for swimming with us!", "size": "S"},
                    ],
                }
            },
            "preview",
        )
        event = Event("Preview", lib.root / "preview.yaml", 320, 176, theme, [], lib.root)
        try:
            img = render_slide(event, Loop("Preview", [card]), 0, None, Renderer(event))
        except (MissingAsset, ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(png(img, 2), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/theme/logo")
    def event_logo_file():
        logo = (s.data.get("theme") or {}).get("logo")
        if not logo or not (s.path.parent / logo).exists():
            raise HTTPException(404, "no logo in this event's theme")
        return FileResponse(s.path.parent / logo, headers={"Cache-Control": "no-store"})

    @app.post("/api/copy")
    def copy_slide(body: CopyBody):
        """Add a copy of a slide to another loop. The copy is its own slide: editing one leaves the other as it is."""

        def edit(d):
            kind, props = next(iter(d["loops"][body.loop]["slides"][body.n].items()))
            props = copy.deepcopy(props or {})
            if "ref" in props:  # a linked slide from an older event: copy what it shows
                key = props.pop("ref")
                source = next(
                    (
                        r
                        for l in d["loops"]
                        for r in l.get("slides") or []
                        if (next(iter(r.values())) or {}).get("id") == key and "ref" not in next(iter(r.values()))
                    ),
                    None,
                )
                if source is None:
                    raise HTTPException(422, f"the slide it links to ({key}) is gone")
                props = {**copy.deepcopy(next(iter(source.values()))), **props}
            props.pop("id", None)
            d["loops"][body.target]["slides"].append({kind: props})

        with s.lock:
            s.loop(body.target)
            s.change(edit)
        return {"ok": True}

    @app.put("/api/event/templates")
    def set_event_templates(body: FolderBody):
        """The DisplayLink Plus template folder for this whole event (saved in its file); optionally the app default too."""
        folder = Path(body.folder).expanduser()
        if not folder.is_dir():
            raise HTTPException(422, f"folder not found: {body.folder}")
        if not any(folder.rglob("*.tpl")):
            raise HTTPException(422, f"no DisplayLink Plus templates (.tpl) in {folder}")
        with s.lock:
            s.change(lambda d: d.__setitem__("templates", str(folder)))
        if body.make_default:
            lib.update_settings(templates=str(folder))
        return {"ok": True, "templates": sum(1 for _ in folder.rglob("*.tpl"))}

    @app.put("/api/panels")
    def save_panel(body: PanelBody):
        x, y, w, h = (list(body.panel) + [0, 0, 0, 0])[:4]
        if w < 40 or h < 30 or x < 0 or y < 0 or x + w > s.event.width or y + h > s.event.height:
            raise HTTPException(422, f"the panel must fit inside the {s.event.width} × {s.event.height} board")
        name = Path(body.template).name
        with s.lock:
            s.change(lambda d: d.setdefault("template_panels", {}).__setitem__(name, {"panel": [x, y, w, h]}))
        return {"ok": True}

    @app.get("/api/versions")
    def versions():
        folder = s.path.parent / "versions"
        found = sorted(folder.glob("*.yaml"), reverse=True) if folder.is_dir() else []
        return [{"name": f.stem, "bytes": f.stat().st_size} for f in found]

    @app.post("/api/versions/{name}/restore")
    def restore_version(name: str):
        path = (s.path.parent / "versions" / f"{name}.yaml").resolve()
        if path.parent != (s.path.parent / "versions").resolve() or not path.exists():
            raise HTTPException(404, "no such version")
        with s.lock:
            try:
                s.restore(path.read_text(encoding="utf-8"))
            except EventError as exc:
                raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    @app.get("/api/templates")
    def list_templates():
        """The .tpl files in the DisplayLink Plus template folder, for the Board slide's picker."""
        folder = s.event.templates
        if not folder.is_dir():
            return {"folder": str(folder), "found": False, "templates": []}
        names = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*.tpl"))
        details = []
        with s.lock:
            for name in names:
                try:
                    s.renderer.board(name)  # draws it once (cached) and notes its live fields
                    codes = s.renderer._live.get(s.event.template(name), [])  # pylint: disable=protected-access
                    details.append({"name": name, "live": bool(codes), "about": tpl.describe_fields(codes)})
                except Exception as exc:  # pylint: disable=broad-except  # a template this reader can't draw
                    details.append({"name": name, "live": False, "broken": str(exc)[:120]})
            s.renderer.issues = []
        return {"folder": str(folder), "found": True, "templates": names, "details": details}

    @app.get("/api/asset")
    def event_asset(path: str):
        """A picture from the open event's folder (e.g. assets/poster.jpg), for the crop box."""
        root = s.path.parent.resolve()
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file():
            raise HTTPException(404, "no such picture in this event")
        return FileResponse(target, headers={"Cache-Control": "no-store"})

    @app.get("/api/template.png")
    def template_png(name: str):
        """A template drawn at board size, for the picker."""
        with s.lock:
            try:
                img = s.renderer.board(name)
            except (MissingAsset, ValueError, KeyError, OSError) as exc:
                raise HTTPException(422, str(exc)) from exc
            s.renderer.issues = []
        return Response(png(img), media_type="image/png", headers={"Cache-Control": "max-age=60"})

    @app.post("/api/pictures")
    def add_picture(file: UploadFile):
        """Save a shrunk working copy of a picked picture in the event's folder; returns its path for the slide."""
        assets = s.path.parent / "assets"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / Path(file.filename or "picture").name
            src.write_bytes(file.file.read())
            try:
                stored = prepare_upload(src, assets)
            except UploadError as exc:
                raise HTTPException(422, str(exc)) from exc
        return {"file": f"assets/{stored.name}", "bytes": stored.stat().st_size}

    @app.get("/api/checks")
    def checks():
        with s.lock:
            return [
                {"level": i.level, "loop": i.loop, "slide": i.slide, "message": i.message} for i in run_checks(s.event)
            ]

    @app.post("/api/export")
    def export(body: ExportBody):
        if body.preview_mp4 and "wmv" not in body.formats:
            body.formats = ["wmv", *body.formats]  # the review MP4 is made alongside the WMV
        if not body.loops:
            raise HTTPException(422, "pick at least one loop to export")
        with s.lock:
            errors = [i for i in run_checks(s.event, [s.loop(i) for i in body.loops]) if i.level == "error"]
        if errors:  # errors block an export; warnings don't
            raise HTTPException(422, "Fix these first: " + "; ".join(str(e).removeprefix("error: ") for e in errors))
        job = {
            "id": uuid.uuid4().hex[:8],
            "state": "running",
            "done": [],
            "error": None,
            "total": len(body.loops),
            "started": time.time(),
        }
        jobs[job["id"]] = job
        with s.lock:
            keep_version(s.path)

        def work():
            try:
                with s.lock:
                    event, loops = s.event, [s.loop(i) for i in body.loops]
                renderer = Renderer(event)  # its own renderer, so previews keep working meanwhile
                for loop in loops:
                    job["current"] = loop.name
                    paths, skipped = [], []
                    if "wmv" in body.formats:
                        paths += export_loop(event, loop, body.out_dir, body.preview_mp4, renderer)
                    if "png" in body.formats:
                        pngs, skipped = export_pngs(event, loop, body.out_dir, renderer)
                        paths += pngs
                    job["done"].append(
                        {
                            "loop": loop.name,
                            "files": [str(p) for p in paths],
                            "bytes": sum(p.stat().st_size for p in paths),
                            "skipped": [{"slide": n, "reason": why} for n, why in skipped],
                        }
                    )
                job["state"] = "done"
            except Exception as exc:  # pylint: disable=broad-except  # reported to the editor
                job["state"], job["error"] = "failed", str(exc)
            job["seconds"] = round(time.time() - job["started"], 1)

        threading.Thread(target=work, daemon=True).start()
        return job

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "no such job")
        return jobs[job_id]

    @app.get("/")
    def home_page():
        return FileResponse(STATIC / "home.html")

    @app.get("/edit")
    def editor_page():
        if current.session is None:
            return RedirectResponse("/")
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
