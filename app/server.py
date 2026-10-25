"""Local API for Loop Builder: the events home and settings, and for the open event its previews,
checks, edits and exports.

Runs on 127.0.0.1 only. The pages (app/static) are served from the same origin. The routes live in app/api by
area (home, editing, export); create_app puts them together around one shared Context."""

import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import editing, export, home
from app.api.state import STATIC, Context
from app.library import Library
from app.updates import check_for_update
from app.version import RELEASES_URL, VERSION


def create_app(event_path=None, templates=None, library=None):
    """`event_path` opens one event straight away (developer use); otherwise the app starts on the events home.
    `templates` overrides the DisplayLink Plus template folder setting."""
    ctx = Context(library or Library(), templates)
    app = FastAPI(title="Loop Builder")
    if event_path:
        ctx.open_event(event_path)
    if RELEASES_URL:  # asked once, in the background, so the home page never waits on the network
        threading.Thread(
            target=lambda: ctx.update.update(check_for_update(VERSION, RELEASES_URL) or {}), daemon=True
        ).start()

    home.register(app, ctx)
    editing.register(app, ctx)
    export.register(app, ctx)

    @app.get("/")
    def home_page():
        return FileResponse(STATIC / "home.html")

    @app.get("/edit")
    def editor_page():
        if ctx.current.session is None:
            return RedirectResponse("/")
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
