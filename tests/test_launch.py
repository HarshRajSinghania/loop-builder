"""Starting without a console, as the packaged Windows app does, in a window that fits the screen."""

import sys
from types import SimpleNamespace as Screen

import uvicorn

from app.__main__ import MIN_WINDOW, WINDOW, ensure_streams, window_fit


def test_a_windowed_start_logs_to_a_file_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOPBUILDER_HOME", str(tmp_path / "Loop Builder"))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log = ensure_streams()
    try:
        uvicorn.Config(lambda scope, receive, send: None, log_level="warning")  # set up logging: failed before
        print("started")
    finally:
        sys.stdout.close()
    assert log == tmp_path / "Loop Builder" / "loop-builder.log" and "started" in log.read_text(encoding="utf-8")


def test_a_console_start_keeps_its_streams():
    assert ensure_streams() is None


def test_the_window_fits_the_screen():
    assert window_fit([Screen(width=2560, height=1440)]) == (WINDOW, MIN_WINDOW, False)
    size, smallest, maximized = window_fit([Screen(width=1280, height=720)])  # 1080p at 150%
    assert maximized and size[1] <= 640 and smallest[1] <= 640
    assert window_fit([]) == (WINDOW, MIN_WINDOW, False)
