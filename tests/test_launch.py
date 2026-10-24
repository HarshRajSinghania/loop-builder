"""Starting without a console, as the packaged Windows app does, in a window that fits the screen."""

import sys
from types import SimpleNamespace as Screen

import uvicorn

from app.__main__ import WINDOW, ensure_streams, first_size, fit_to, spills


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


def test_the_window_fits_any_screen():
    assert fit_to(0, 0, 2560, 1400) == (560, 220, *WINDOW)  # room for the usual size: centred
    for area in [(0, 0, 1280, 672), (0, 40, 1366, 728), (-1920, 0, 1920, 1032), (0, 0, 3840, 2100)]:
        x, y, w, h = fit_to(*area)
        left, top, width, height = area
        assert left <= x and x + w <= left + width and top <= y and y + h <= top + height  # on the screen
    assert not spills((256, 141, 1000, 700), (0, 33, 1512, 892))
    assert spills((0, 0, 1500, 1400), (0, 33, 1512, 892)) and spills((-10, 100, 800, 600), (0, 0, 1920, 1040))
    assert first_size([Screen(width=1280, height=720)])[1] < 720 and first_size([]) == WINDOW
