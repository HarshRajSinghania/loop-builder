"""The request bodies of the local API."""

from pydantic import BaseModel


class SlideBody(BaseModel):
    """A slide sent from the editor: a draft to preview, or a change to save."""

    loop: int
    n: int
    slide: dict  # one event-file slide, e.g. {"card": {...}}
    at: float | None = None


class LoopBody(BaseModel):
    """A whole loop from the editor: its settings and slides in play order."""

    name: str
    hold: float = 10.0
    fade: float = 0.5
    slides: list[dict]


class SettingsBody(BaseModel):
    """Settings the home screen and Settings dialog change; a field left out stays as it is."""

    team: str | None = None
    templates: str | None = None
    export_dir: str | None = None
    pool_lanes: int | None = None
    first_lane: int | None = None
    theme: dict | None = None  # the team theme: colours only (the logo has its own upload)


class SavePictureBody(BaseModel):
    """A picture already in the open event, to keep in Pictures under a name."""

    path: str
    name: str


class NewEventBody(BaseModel):
    """A new event from a starter, or a copy of an existing one."""

    name: str
    date: str | None = None
    starter: str = "dual-meet"
    visitor: str | None = None  # a team's id: the visiting team, put on the starter's cards


class TeamPick(BaseModel):
    """A team from Teams, by id."""

    team: str


class DetailsBody(BaseModel):
    """The open event's name and date (YYYY-MM-DD; empty for none), as its header shows them."""

    name: str
    date: str = ""


class ThemeBody(BaseModel):
    """The open event's own theme (its colours); Settings holds the team theme new events start from."""

    theme: dict


class LookBody(BaseModel):
    """Colours to preview in Settings, before they're saved."""

    theme: dict


class CopyBody(BaseModel):
    """Copy slide `n` of `loop` to the end of another loop."""

    loop: int
    n: int
    target: int


class FolderBody(BaseModel):
    """A DisplayLink Plus template folder for the open event; `make_default` also sets it for new events."""

    folder: str
    make_default: bool = False


class PanelBody(BaseModel):
    """The rectangle of a board template that a countdown or crawl may draw in: [x, y, width, height] in board px."""

    template: str
    panel: list[int]


class PathBody(BaseModel):
    """A file path chosen with the app's own Save dialog."""

    path: str


class ExportBody(BaseModel):
    """Which loops to export, and to which folder."""

    loops: list[int]
    out_dir: str
    formats: list[str] = ["wmv"]  # "wmv" (video) and/or "png" (one still per slide)
    preview_mp4: bool = False
    replace: bool = False  # agreed to write over an earlier export: its stills of these loops go first
