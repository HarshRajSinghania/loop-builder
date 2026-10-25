"""Starting without a console, as the packaged Windows app does."""

import sys
from types import SimpleNamespace

import uvicorn

from app.__main__ import ensure_streams, window_size


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


def screen(width, height):
    return SimpleNamespace(width=width, height=height)


def test_the_window_keeps_its_usual_size_on_a_big_screen():
    assert window_size([screen(1920, 1080)]) == ((1440, 960), (1024, 700))


def test_the_window_fits_a_screen_smaller_than_its_usual_size():
    (width, height), least = window_size([screen(1512, 949)])  # 1440 x 960 ran off this one
    assert (width, height) == (1440, 829) and least == (1024, 700)


def test_the_minimum_size_gives_way_on_a_very_small_screen():
    assert window_size([screen(1024, 768)]) == ((960, 648), (960, 648))


def test_no_screen_list_opens_at_the_usual_size():
    assert window_size([]) == ((1440, 960), (1024, 700))
