# Loop Builder

## Problem

Swim and dive teams run video loops on a DisplayLink Plus scoreboard: welcome screens, diving etiquette,
warm-up countdowns, fundraiser slides. Each loop is a WMV at the board's exact pixel size. Making them
today takes image tools, a video encoder and a lot of trial and error, and the result only shows up
on the board.

## Features

- Seven slide types: Board (a DisplayLink Plus template), Card (text in four fixed layouts), QR, Image (with
  framing and an optional pan), Countdown, Crawl and Lanes (guest teams by lane, from a team library).
- A team theme in Settings (colours and logo) that every new event starts from; each event can change its own.
- One event file holds every loop for a meet, so next week's meet starts from this one.
- The preview is drawn by the same renderer as the export, so it matches the WMV pixel for pixel.
- Checks before export: QR codes decode to their links, lines fit, pictures are present.
- Export straight to WMV (wmv2, 30 fps) for DisplayLink Plus, plus an optional enlarged MP4 to review.
- An events home with starters (dual meet, Sections, True Team, blank), duplicate, and `.loopevent` packages
  for moving an event to another computer.
- A drag-and-drop editor: palette, slide strip, an editor per slide type, autosave, undo and redo, copying a slide
  to another loop, and versions kept on each export.
- Runs offline. Events, templates and pictures stay on the computer.

## Quick Start

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
# the editor, in its app window, on the example event
.venv/bin/python -m app            # the events home; first launch asks for the DisplayLink Plus template folder
.venv/bin/python -m app examples/dual-meet/event.yaml --templates "<DisplayLink Plus template folder>"   # one event
# or straight to WMVs
.venv/bin/python -m loopgen examples/dual-meet/event.yaml --templates "<DisplayLink Plus template folder>" --out out
```

For working on the editor itself, `--browser` opens it in a browser tab instead, for reloading and dev tools.

## Architecture

- `loopgen/` renders slides and loops from an event file and encodes them with FFmpeg through PyAV.
  `tpl.py` and `nrbf.py` read DisplayLink Plus `.tpl` templates.
- `app/` is a local server (FastAPI, 127.0.0.1 only) and the editor page it serves. The packaged app shows
  that page in a pywebview window.
- `packaging/` builds the desktop app with PyInstaller as a folder app (`.app` on Mac, a folder with
  `Loop Builder.exe` on Windows).

## Details

- Build the app: `.venv/bin/pyinstaller packaging/loopbuilder.spec --noconfirm`; installers, signing and CI are
  in [packaging/README.md](packaging/README.md). The version is set in `app/version.py`.
- Events live in Documents › Loop Builder (set `LOOPBUILDER_HOME` to use another folder, as the tests do).
- Tests: `.venv/bin/python -m pytest`. Lint: `.venv/bin/pylint loopgen app tests`. Format: `black -l 120`.
- Pictures added to an event are kept as working copies at most 2048 px on the long side, so previews stay fast.
- PyAV's FFmpeg build includes GPL components (x264, x265); the licence for distributed builds is still to decide.
