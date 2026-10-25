"""Local API for Loop Builder: the events home and settings, and for the open event its previews,
checks, edits and exports.

Runs on 127.0.0.1 only. The pages (app/static) are served from the same origin. The routes live in app/api by
area (home, editing, export); create_app puts them together around one shared Context."""

import threading
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import editing, export, home
from app.api.state import STATIC, Context
from app.library import Library
from app.updates import check_for_update
from app.version import RELEASES_URL, VERSION

LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")  # the names this computer's own pages reach the app by
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def from_this_app(request):
    """Whether a request comes from the app's own pages (or from no page at all, like a script or the tests' client),
    not from a website. The server only listens on 127.0.0.1, but a site the user visits can still aim a form post
    at it, or point a name of its own at 127.0.0.1 (DNS rebinding) to read the answers. So the Host must be this
    computer, and a change must come from no page or from this one (its Origin, or Referer when there's none)."""
    host = request.headers.get("host", "").lower()
    name = host[: host.index("]") + 1] if host.startswith("[") else host.split(":")[0]
    if name not in LOCAL_HOSTS:
        return False
    if request.method in SAFE_METHODS:
        return True
    origin = request.headers.get("origin")
    if origin is None and request.headers.get("referer"):
        parts = urlsplit(request.headers["referer"])
        origin = f"{parts.scheme}://{parts.netloc}"
    return origin is None or origin.lower() == f"http://{host}"


def create_app(event_path=None, templates=None, library=None):
    """`event_path` opens one event straight away (developer use); otherwise the app starts on the events home.
    `templates` overrides the DisplayLink Plus template folder setting."""
    ctx = Context(library or Library(), templates)
    app = FastAPI(title="Loop Builder")

    @app.middleware("http")
    async def only_this_app(request: Request, call_next):
        if not from_this_app(request):
            return PlainTextResponse("Loop Builder only answers its own window.", status_code=403)
        return await call_next(request)

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
