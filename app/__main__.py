"""Start Loop Builder: the app window on the events home, backed by a local server on 127.0.0.1.

python -m app [EVENT.yaml] [--templates "<DisplayLink Plus template folder>"]

With EVENT.yaml the editor opens on that event straight away. Developer options: --browser opens a
browser tab instead (reload and dev tools); --no-open only serves; --port picks the port (default: any free one).
"""

import argparse
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from app.library import default_root
from app.server import create_app


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NativeDialogs:
    """The system's own folder and save pickers, offered to the page as window.pywebview.api."""

    def __init__(self):
        self._window = None  # private: pywebview exposes every public attribute to the page

    def _dialog(self, kind, **kwargs):
        import webview  # pylint: disable=import-outside-toplevel

        mode = getattr(getattr(webview, "FileDialog", None), kind, None) or getattr(webview, f"{kind}_DIALOG")
        picked = self._window.create_file_dialog(mode, **kwargs)
        if isinstance(picked, (list, tuple)):
            picked = picked[0] if picked else None
        return picked or None

    def pick_folder(self, start=""):
        return self._dialog("FOLDER", directory=start or "")

    def save_file(self, name, start=""):
        return self._dialog("SAVE", directory=start or "", save_filename=name)


WINDOW = (1440, 960)
MIN_WINDOW = (900, 560)  # fits a 1080p screen at 150% scaling (1280 x 720 before the taskbar)
SCREEN_MARGIN = 80  # the taskbar or Dock and the window's title bar


def window_fit(screens):
    """The window's size, smallest size and whether to open maximized. A window taller than the screen
    hides the bottom of the page, and dialogs' buttons with it, so on a small screen it opens maximized:
    that fills the screen without the taskbar, whatever the display scaling."""
    if not screens:
        return WINDOW, MIN_WINDOW, False
    width, height = screens[0].width, screens[0].height - SCREEN_MARGIN
    fits = WINDOW[0] <= width and WINDOW[1] <= height
    smallest = (min(MIN_WINDOW[0], width), min(MIN_WINDOW[1], height))
    return (WINDOW if fits else (min(WINDOW[0], width), min(WINDOW[1], height))), smallest, not fits


def ensure_streams():
    """A windowed build (no console) starts with no stdout/stderr, and uvicorn's logging fails on that: send
    them to loop-builder.log in the Loop Builder folder, fresh each start."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    log = default_root() / "loop-builder.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log, "w", encoding="utf-8", buffering=1)  # pylint: disable=consider-using-with  # app-long
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream
    return log


def main():
    ensure_streams()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("event", nargs="?")
    ap.add_argument("--templates", help="DisplayLink Plus template folder (overrides the setting)")
    ap.add_argument("--port", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--browser", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}/" + ("edit" if args.event else "")
    server = uvicorn.Server(
        uvicorn.Config(create_app(args.event, args.templates), host="127.0.0.1", port=port, log_level="warning")
    )
    if args.browser or args.no_open:
        if args.browser:
            threading.Timer(1.0, webbrowser.open, [url]).start()
        server.run()
        return

    import webview  # pylint: disable=import-outside-toplevel  # the window toolkit loads only for the app

    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:  # open the window only once the page can load
        time.sleep(0.05)
    dialogs = NativeDialogs()
    try:
        screens = webview.screens
    except Exception:  # pylint: disable=broad-except  # no screen list: the default size
        screens = []
    (width, height), smallest, maximized = window_fit(screens)
    dialogs._window = webview.create_window(  # pylint: disable=protected-access
        "Loop Builder", url, width=width, height=height, min_size=smallest, maximized=maximized, js_api=dialogs
    )
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
