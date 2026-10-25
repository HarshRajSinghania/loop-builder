"""The event open in the editor: its previews, edits, theme, visiting team, versions, pictures and checks."""

import copy
import tempfile
import time
from datetime import date
from urllib.parse import quote
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from loopgen import run_checks, slide_label
from loopgen import tpl
from loopgen.event import EventError, _slide
from loopgen.loops import build_clips, loop_length, render_slide
from loopgen.slides import MissingAsset
from loopgen.uploads import UploadError, prepare_upload

from app.library import apply_visitor
from app.api.state import look_colours, png, qr_status, template_folder_status
from app.api.models import (
    CopyBody,
    DetailsBody,
    FolderBody,
    LoopBody,
    PanelBody,
    SlideBody,
    TeamPick,
    ThemeBody,
)


def register(app, ctx):
    """The open event's routes."""
    s, lib, library_call, home_lanes, look_key, same_name, matches_team_look, event_file_path = (
        ctx.s,
        ctx.lib,
        ctx.library_call,
        ctx.home_lanes,
        ctx.look_key,
        ctx.same_name,
        ctx.matches_team_look,
        ctx.event_file_path,
    )

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
        team_look = matches_team_look(s.data, s.path.parent)
        return {
            "theme": s.data.get("theme") or {},
            "team_look": team_look,
            # offer the team theme unless the event has it, or kept its own while the team theme was as it is now
            "offer_team_theme": not team_look and s.data.get("own_theme") != look_key(s.data),
            "panels": s.event.panels,
            "templates_folder": str(s.event.templates),
            "templates_found": s.event.templates.is_dir(),
            "templates_set": s.folder_source != "settings" or bool(s.default()),  # else none chosen yet
            "templates_source": s.folder_source,
            "can_undo": bool(s.undo_stack),
            "can_redo": bool(s.redo_stack),
            "slug": s.path.parent.name,
            "name": s.event.name,
            "visitor": s.data.get("visitor"),
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

    @app.put("/api/event/visitor")
    def set_visitor(body: TeamPick):
        """Make a team the open event's visiting team: its name and logo go on the cards that say VISITING TEAM or
        the previous visitor's name (apply_visitor). Undoable like any edit."""
        visitor = library_call(lib.use_team, body.team, s.path.parent)
        changed = []
        with s.lock:
            s.change(lambda d: changed.append(apply_visitor(d, visitor)))
        return {"visitor": visitor, "cards": changed[0]}

    @app.put("/api/event/details")
    def save_details(body: DetailsBody):
        """Rename the open event or change its date (undoable). Its folder keeps the name it was made with:
        the folder is how the app finds the event, and the events home shows the name from the event file."""
        name = " ".join(body.name.split())
        if not name:
            raise HTTPException(422, "an event needs a name")
        when = body.date.strip()
        if when:
            try:
                when = date.fromisoformat(when).isoformat()
            except ValueError as exc:
                raise HTTPException(422, f"not a date: {body.date}") from exc

        def edit(d):
            d["event"] = name
            if when:
                d["date"] = when
            else:
                d.pop("date", None)

        with s.lock:
            s.change(edit)
        return {"ok": True}

    @app.put("/api/theme")
    def save_theme(body: ThemeBody):
        colours = look_colours(body.theme)
        with s.lock:
            key = look_key(s.data)
            s.change(lambda d: d.update(theme={**(d.get("theme") or {}), **colours}, own_theme=key))
        return {"ok": True}

    @app.post("/api/theme/keep")
    def keep_theme():
        """Keep the open event's theme though it differs from the team theme as it is now (undoable)."""
        key = look_key(s.data)
        with s.lock:
            s.change(lambda d: d.__setitem__("own_theme", key))
        return {"ok": True}

    @app.post("/api/theme/reset")
    def reset_theme():
        """Give the open event the team theme again: its colours and a fresh copy of the team logo, and the
        team's name and logo in the home team's lanes (undoable)."""
        logo = lib.copy_team_logo(s.path.parent)
        home = next((t for t in lib.teams() if t.get("home")), None)
        used = lib.use_team(home["id"], s.path.parent) if home and any(home_lanes(s.data)) else None

        def edit(d):
            theme = {**(d.get("theme") or {}), **lib.team_look()}
            if logo:
                theme["logo"] = logo
            d["theme"] = theme
            d.pop("own_theme", None)
            for lane in home_lanes(d) if used else []:
                lane["logo"] = used["logo"]
                if not same_name(lane.get("name"), used["name"]):  # keeps a | break the name already has
                    lane["name"] = used["name"]

        with s.lock:
            s.change(edit)
        return {"ok": True}

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
        """The DisplayLink Plus template folder for this whole event (saved in its file); optionally the app default
        too."""
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
        on_board = 0 <= x and 0 <= y and x + w <= s.event.width and y + h <= s.event.height
        if w < 40 or h < 30 or not on_board:
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

    @app.get("/api/templates/count")
    def count_templates(folder: str = ""):
        """How many .tpl files a folder holds, for Settings to say so as a folder is typed or picked."""
        return template_folder_status(folder)

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
        return FileResponse(event_file_path(path), headers={"Cache-Control": "no-store"})

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
                # replace=False: another poster.png mustn't change the slides already using this one
                stored = prepare_upload(src, assets, replace=False)
            except UploadError as exc:
                raise HTTPException(422, str(exc)) from exc
        return {"file": f"assets/{stored.name}", "bytes": stored.stat().st_size}

    @app.get("/api/checks")
    def checks():
        with s.lock:
            return [
                {"level": i.level, "loop": i.loop, "slide": i.slide, "message": i.message} for i in run_checks(s.event)
            ]
