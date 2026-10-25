"""The Loop Builder folder on this computer: settings, the team's logo and one folder per event.

    Documents/Loop Builder/settings.json
    Documents/Loop Builder/Team/logo.png
    Documents/Loop Builder/Events/<event>/event.yaml (+ assets/)

Set LOOPBUILDER_HOME to use another folder (tests do)."""

import copy
import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path

import yaml
from PIL import Image

from loopgen.event import DEFAULT_THEME, EventError, read_event_file
from loopgen.uploads import prepare_logo, prepare_picture

LOOK_COLOURS = ("primary", "accent", "text", "muted", "background")  # the colours a look sets

PACKAGE_SUFFIX = ".loopevent"
DEFAULT_SETTINGS = {
    "team": "",
    "templates": None,
    "export_dir": None,
    "logo": None,
    "theme": {},
    "pool_lanes": 8,  # lanes in the team's pool: new lane slides start with this many
    "first_lane": 1,  # 1, or 0 for pools numbered from lane 0
}

_WELCOME = {
    "card": {
        "layout": "logo-center",
        "lines": [
            {"text": "Welcome", "size": "M", "style": "outlined"},
            {"text": "VISITING TEAM", "size": "L", "style": "outlined"},
            {"text": "Thanks for swimming with us!", "size": "S"},
        ],
    }
}
_DIVING = {
    "card": {
        "layout": "stack",
        "lines": [
            {"text": "DIVING", "size": "L", "style": "outlined"},
            {"text": "Quiet please", "size": "M", "style": "bold"},
            {"text": "during each dive", "size": "S"},
            {"text": "Cheer after the splash!", "size": "M", "style": "accent"},
        ],
    }
}
_RESUME = {
    "crawl": {
        "length": "3:00",
        "speed": "medium",
        "segments": [
            {"text": "The meet will "},
            {"text": "RESUME", "style": "outlined"},
            {"text": " shortly", "style": "accent"},
        ],
    }
}


def _headline(top, big, bottom):
    return {
        "card": {
            "layout": "logo-center",
            "lines": [
                {"text": top, "size": "M", "style": "outlined"},
                {"text": big, "size": "L", "style": "outlined"},
                {"text": bottom, "size": "S"},
            ],
        }
    }


def _warmup(minutes):
    return {
        "name": f"Warm-up {minutes} min + resume",
        "slides": [
            {"countdown": {"label": "WARM-UP", "length": f"{minutes}:00", "hold_at_zero": 5}},
            copy.deepcopy(_RESUME),
        ],
    }


STARTERS = {
    "dual-meet": {
        "title": "Dual meet",
        "about": "Welcome with visiting team, diving, 10-minute warm-up",
        "loops": [
            {
                "name": "Welcome loop",
                "slides": [copy.deepcopy(_WELCOME), _headline("Good luck", "SWIMMERS", "and divers!")],
            },
            {"name": "Diving loop", "slides": [copy.deepcopy(_DIVING), copy.deepcopy(_WELCOME)]},
            _warmup(10),
        ],
    },
    "sections": {
        "title": "Sections",
        "about": "Welcome to Sections, heat sheet QR, diving, warm-up countdowns",
        "loops": [
            {
                "name": "Welcome loop",
                "slides": [
                    _headline("Welcome to", "SECTIONS", "Good luck to all teams!"),
                    {"lanes": {"title": "Welcome to Sections!", "lanes": []}},
                    {"qr": {"url": "https://", "heading": ["HEAT", "SHEETS"]}},
                ],
            },
            {"name": "Diving loop", "slides": [copy.deepcopy(_DIVING)]},
            _warmup(20),
        ],
    },
    "true-team": {
        "title": "True Team",
        "about": "Welcome, team congratulations card, diving, warm-up countdowns",
        "loops": [
            {
                "name": "Welcome loop",
                "slides": [
                    _headline("Welcome to", "TRUE TEAM", "Good luck to all teams!"),
                    _headline("Congratulations", "ALL TEAMS", "on a great season!"),
                ],
            },
            {"name": "Diving loop", "slides": [copy.deepcopy(_DIVING)]},
            _warmup(20),
        ],
    },
    "blank": {
        "title": "Blank",
        "about": "Theme only, one empty loop",
        "loops": [
            {"name": "Loop 1", "slides": [{"card": {"layout": "stack", "lines": [{"text": "NEW CARD", "size": "L"}]}}]}
        ],
    },
}


class LibraryError(ValueError):
    """Something about the Loop Builder folder or an event package isn't right."""


def default_root():
    if os.environ.get("LOOPBUILDER_HOME"):
        return Path(os.environ["LOOPBUILDER_HOME"]).expanduser()
    return Path.home() / "Documents" / "Loop Builder"


VISITOR_PLACEHOLDER = "VISITING TEAM"  # what the Dual meet starter's cards say until a visiting team is chosen


def apply_visitor(data, visitor):
    """Put a visiting team ({"name", "logo"}) on an event's cards, in its file's data. A card line that still says
    VISITING TEAM, or the previous visiting team's name, gets the new name, and those cards' picture shows the new
    logo where it showed ours or the previous visitor's. Lines typed by hand are left alone. Returns cards changed."""
    old = data.get("visitor") or {}
    changed = 0
    for loop in data.get("loops") or []:
        for slide in loop.get("slides") or []:
            card = slide.get("card") if isinstance(slide, dict) else None
            if not isinstance(card, dict):
                continue
            lines = [line for line in card.get("lines") or [] if isinstance(line, dict)]
            ours = [
                line
                for line in lines
                if str(line.get("text", "")).strip().upper() == VISITOR_PLACEHOLDER
                or (old.get("name") and str(line.get("text", "")).strip() == old["name"])
            ]
            for line in ours:
                line["text"] = visitor["name"]
            if ours:
                changed += 1
                if card.get("layout") == "logo-center" and card.get("picture", "") in ("", "logo", old.get("logo")):
                    card["picture"] = visitor["logo"]
    data["visitor"] = {"name": visitor["name"], "logo": visitor["logo"]}
    return changed


def _slug(name):
    """A folder name from an event name: readable, and safe on Windows and Mac."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .")
    return " ".join(cleaned.split())[:80] or "Event"


class Library:  # pylint: disable=too-many-public-methods  # the one way in to the Loop Builder folder
    """The Loop Builder folder: settings, the team logo and the events."""

    def __init__(self, root=None):
        self.root = Path(root) if root else default_root()
        self.events_dir = self.root / "Events"
        self.team_dir = self.root / "Team"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.team_dir.mkdir(parents=True, exist_ok=True)

    # --- settings ---

    @property
    def settings_path(self):
        return self.root / "settings.json"

    def settings(self):
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            saved = {}
        return {**DEFAULT_SETTINGS, **saved}

    FOLDERS = ("templates", "export_dir")  # kept with ~ written out, so every reader finds the same folder

    def update_settings(self, **changes):
        changes = {k: str(Path(v).expanduser()) if k in self.FOLDERS and v else v for k, v in changes.items()}
        settings = {**self.settings(), **{k: v for k, v in changes.items() if k in DEFAULT_SETTINGS}}
        self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return settings

    def set_logo(self, picture):
        """Keep the team logo (already shrunk) in the Team folder."""
        target = self.team_dir / f"logo{Path(picture).suffix.lower()}"
        shutil.copyfile(picture, target)
        return self.update_settings(logo=str(target.relative_to(self.root)))

    # --- team logos for lane slides (Team/Teams: one PNG per team + teams.json) ---

    @property
    def teams_dir(self):
        return self.team_dir / "Teams"

    HOME_TEAM = "_home"  # the team from Settings; an added team's id never starts with "_"

    def teams(self):
        """The home team (Settings: team name and logo, when both are set) first, then the added teams."""
        try:
            found = json.loads((self.teams_dir / "teams.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            found = []
        added = [t for t in found if (self.teams_dir / t["logo"]).exists()]
        settings = self.settings()
        name, logo = (settings.get("team") or "").strip(), self.team_logo(settings)
        if not (name and logo):  # a name without a logo isn't a team on the board yet
            return added
        # "_home.png" in an event: an added team's file is "<id>.png" and an id never starts with "_"
        return [{"id": self.HOME_TEAM, "name": name, "logo": f"{self.HOME_TEAM}{logo.suffix}", "home": True}] + added

    def team_logo_path(self, team):
        """The file of a team's logo: the home team's is the Settings logo."""
        return self.team_logo() if team.get("home") else self.teams_dir / team["logo"]

    def _save_teams(self, teams):
        self.teams_dir.mkdir(parents=True, exist_ok=True)
        (self.teams_dir / "teams.json").write_text(json.dumps(teams, indent=2), encoding="utf-8")

    def add_team(self, name, picture, trim=True):
        """Add (or replace) a team: its name as shown on the board and its logo, kept for every event."""
        name = " ".join(str(name).split())
        if not name:
            raise LibraryError("a team needs a name")
        team_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "team"
        prepare_logo(picture, self.teams_dir / f"{team_id}.png", trim)
        teams = [t for t in self.teams() if t["id"] != team_id and not t.get("home")]
        teams.append({"id": team_id, "name": name, "logo": f"{team_id}.png"})
        self._save_teams(sorted(teams, key=lambda t: t["name"]))
        return team_id

    def rename_team(self, team_id, name):
        if team_id == self.HOME_TEAM:
            raise LibraryError("your own team's name is set in Settings")
        teams = [t for t in self.teams() if not t.get("home")]
        for t in teams:
            if t["id"] == team_id:
                t["name"] = " ".join(str(name).split()) or t["name"]
        self._save_teams(teams)

    def delete_team(self, team_id):
        if team_id == self.HOME_TEAM:
            raise LibraryError("your own team is set in Settings")
        self._save_teams([t for t in self.teams() if t["id"] != team_id and not t.get("home")])
        (self.teams_dir / f"{team_id}.png").unlink(missing_ok=True)

    def use_team(self, team_id, event_folder):
        """Copy a team's logo into an event (so the event and its package stand alone); returns name and path."""
        team = next((t for t in self.teams() if t["id"] == team_id), None)
        if team is None:
            raise LibraryError(f"no team {team_id!r}")
        target = Path(event_folder) / "assets" / "teams" / team["logo"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.team_logo_path(team), target)
        return {"name": team["name"], "logo": f"assets/teams/{team['logo']}"}

    # --- Pictures: badges, league logos and other pictures kept for every event ---

    @property
    def pictures_dir(self):
        return self.root / "Pictures"

    def pictures(self):
        """The saved pictures, by name; one whose file has gone is left out."""
        try:
            found = json.loads((self.pictures_dir / "pictures.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            found = []
        return [pic for pic in found if (self.pictures_dir / pic["file"]).exists()]

    def picture_path(self, picture_id):
        pic = next((p for p in self.pictures() if p["id"] == picture_id), None)
        if pic is None:
            raise LibraryError(f"no picture {picture_id!r}")
        return self.pictures_dir / pic["file"]

    def _save_pictures(self, pictures):
        self.pictures_dir.mkdir(parents=True, exist_ok=True)
        pictures = sorted(pictures, key=lambda p: p["name"].lower())
        (self.pictures_dir / "pictures.json").write_text(json.dumps(pictures, indent=2), encoding="utf-8")

    def add_picture(self, name, picture, trim=False, replace=True):
        """Add a picture kept for every event; returns its id. One of the same name is replaced, or with
        replace=False the new one gets a free name ("duck 2")."""
        name = " ".join(str(name).split())
        if not name:
            raise LibraryError("a picture needs a name")

        def make_id(n):
            return re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-") or "picture"

        def same(n):  # a saved picture of this name (or whose id this name would take), renamed or not
            return next((p for p in self.pictures() if p["name"].lower() == n.lower() or p["id"] == make_id(n)), None)

        base, n = name, 1
        while not replace and same(name):
            n += 1
            name = f"{base} {n}"
        old = same(name)
        picture_id = old["id"] if old else make_id(name)
        keep = [p for p in self.pictures() if p["id"] != picture_id]
        for old in self.pictures_dir.glob(f"{picture_id}.*"):  # a replaced PNG may come back as a JPEG
            if old.suffix != ".json":
                old.unlink()
        stored = prepare_picture(picture, self.pictures_dir / picture_id, trim)
        with Image.open(stored) as img:
            size = list(img.size)
        self._save_pictures(keep + [{"id": picture_id, "name": name, "file": stored.name, "size": size}])
        return picture_id

    def rename_picture(self, picture_id, name):
        pictures = self.pictures()
        for p in pictures:
            if p["id"] == picture_id:
                p["name"] = " ".join(str(name).split()) or p["name"]
        self._save_pictures(pictures)

    def delete_picture(self, picture_id):
        path = self.picture_path(picture_id)
        self._save_pictures([p for p in self.pictures() if p["id"] != picture_id])
        path.unlink(missing_ok=True)

    def use_picture(self, picture_id, event_folder):
        """Copy a saved picture into an event (so the event and its package stand alone); returns its path there."""
        source = self.picture_path(picture_id)
        target = Path(event_folder) / "assets" / "pictures" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return {"file": f"assets/pictures/{source.name}"}

    def set_visitor(self, slug, team_id):
        """Make a team the visiting team of an event that isn't open (see apply_visitor); returns cards changed."""
        path = self.event_file(slug)
        visitor = self.use_team(team_id, path.parent)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        changed = apply_visitor(data, visitor)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return changed

    # --- events ---

    def event_file(self, slug):
        path = (self.events_dir / slug / "event.yaml").resolve()
        if self.events_dir.resolve() not in path.parents or not path.exists():
            raise LibraryError(f"no event named {slug!r}")
        return path

    def events(self):
        found = []
        for path in self.events_dir.glob("*/event.yaml"):
            try:
                data = read_event_file(path)
            except EventError:  # a hand-edited or half-synced file: left out, so the other events still show
                continue
            found.append(
                {
                    "slug": path.parent.name,
                    "name": data.get("event") or path.parent.name,
                    "date": str(data.get("date") or ""),
                    "edited": path.stat().st_mtime,
                    "loops": [
                        {"name": l.get("name", "Loop"), "slides": len(l.get("slides") or [])}
                        for l in data.get("loops") or []
                    ],
                }
            )
        return sorted(found, key=lambda e: e["edited"], reverse=True)

    def _free_name(self, name):
        """A name no event here has, and a free folder for it: "<name> (2)" when an event is called that or has that
        folder. Both count: a renamed event keeps the folder of its first name."""
        taken = {str(e["name"]).casefold() for e in self.events()}
        base, n = _slug(name), 2
        new, folder = name, self.events_dir / base
        while folder.exists() or new.casefold() in taken:
            new, folder, n = f"{name} ({n})", self.events_dir / f"{base} ({n})", n + 1
        return new, folder

    def _free_folder(self, name):
        base = _slug(name)
        folder, n = self.events_dir / base, 2
        while folder.exists():
            folder, n = self.events_dir / f"{base} ({n})", n + 1
        return folder

    def team_look(self):
        """The team's colours (Settings → Team theme), with the defaults for any not chosen yet."""
        return {**{k: DEFAULT_THEME[k] for k in LOOK_COLOURS}, **self.settings().get("theme", {})}

    def team_logo(self, settings=None):
        """The team logo's file, or None."""
        logo = (settings or self.settings()).get("logo")
        return self.root / logo if logo and (self.root / logo).exists() else None

    def team_look_key(self, with_name=False):
        """A short fingerprint of the team theme (colours and logo picture, and the team name for an event whose
        lanes show the home team): an event that kept its own theme stores it, so the editor offers the team
        theme again only once the team theme has changed."""
        logo = self.team_logo()
        look = {**self.team_look(), **({"team": (self.settings().get("team") or "").strip()} if with_name else {})}
        data = json.dumps(look, sort_keys=True).encode() + (logo.read_bytes() if logo else b"")
        return hashlib.sha1(data, usedforsecurity=False).hexdigest()[:12]

    def copy_team_logo(self, event_folder):
        """Copy the team logo into an event's assets; returns its path in the event, or None."""
        logo = self.team_logo()
        if logo is None:
            return None
        shutil.copyfile(logo, Path(event_folder) / "assets" / logo.name)
        return f"assets/{logo.name}"

    def create(self, name, starter="dual-meet", when=None):
        if starter not in STARTERS:
            raise LibraryError(f"unknown starter {starter!r}")
        folder = self._free_folder(name)
        (folder / "assets").mkdir(parents=True)
        theme = self.team_look()
        logo = self.copy_team_logo(folder)
        if logo:
            theme["logo"] = logo
        loops = copy.deepcopy(STARTERS[starter]["loops"])
        settings = self.settings()
        for loop in loops:  # lane slides start with the team's pool
            for slide in loop["slides"]:
                if "lanes" in slide:
                    slide["lanes"].setdefault("first", settings["first_lane"])
                    slide["lanes"].setdefault("last", settings["first_lane"] + settings["pool_lanes"] - 1)
        data = {
            "event": name,
            "date": str(when or date.today()),
            "board": {"width": 320, "height": 176},
            "theme": theme,
            "loops": loops,
        }
        (folder / "event.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return folder.name

    def duplicate(self, slug, name, when=None):
        source = self.event_file(slug).parent
        folder = self._free_folder(name)
        shutil.copytree(source, folder)
        path = folder / "event.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["event"], data["date"] = name, str(when or date.today())
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return folder.name

    def delete(self, slug):
        """Remove an event's folder: its file, its pictures and its kept versions."""
        folder = self.event_file(slug).parent
        if folder.parent != self.events_dir.resolve():  # only ever one event's own folder
            raise LibraryError(f"no event named {slug!r}")
        shutil.rmtree(folder)

    # --- .loopevent packages: an event folder in one zip file ---

    def export_package(self, slug, dest):
        source = self.event_file(slug).parent
        dest = Path(dest)
        if dest.suffix != PACKAGE_SUFFIX:
            dest = dest.with_name(dest.name + PACKAGE_SUFFIX)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(source.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(source).as_posix())
        return dest

    def import_package(self, package):
        with zipfile.ZipFile(package) as z:
            names = z.namelist()
            if "event.yaml" not in names:
                raise LibraryError("this file isn't a Loop Builder event (no event.yaml inside)")
            for n in names:
                if n.startswith("/") or ".." in Path(n).parts or ":" in n:
                    raise LibraryError(f"unsafe path in package: {n}")
            data = yaml.safe_load(z.read("event.yaml")) or {}
            name = str(data.get("event") or Path(package).stem)
            new, folder = self._free_name(name)
            z.extractall(folder)
        if new != name:  # "<name> (2)", so the home screen tells the two apart
            path = folder / "event.yaml"
            data["event"] = new
            path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return folder.name
