"""Start Loop Builder: the app window on the events home, backed by a local server on 127.0.0.1.

python -m app [EVENT.yaml] [--templates "<DisplayLink Plus template folder>"]

With EVENT.yaml the editor opens on that event straight away. Developer options: --browser opens a
browser tab instead (reload and dev tools); --no-open only serves; --port picks the port (default: any free one).
"""

import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

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


def main():
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
    dialogs._window = webview.create_window(  # pylint: disable=protected-access
        "Loop Builder", url, width=1440, height=960, min_size=(1024, 700), js_api=dialogs
    )
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
