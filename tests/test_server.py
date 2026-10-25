"""The editor's local API: loop edits save, and an edit that breaks the event changes nothing."""

import shutil
import threading
import time
from urllib.parse import unquote
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.library import Library
from app.server import create_app

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "dual-meet"


@pytest.fixture(name="client")
def fixture_client(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "event")
    app = create_app(tmp_path / "event" / "event.yaml", library=Library(tmp_path / "Loop Builder"))
    return TestClient(app), tmp_path / "event" / "event.yaml"


def loop_body(event, i):
    lp = event["loops"][i]
    return {
        "name": lp["name"],
        "hold": lp["hold"],
        "fade": lp["fade"],
        "slides": [s["raw"] for s in lp["slides"]],
    }


def test_reorder_and_delete_save(client):
    api, _ = client
    event = api.get("/api/event").json()
    body = loop_body(event, 2)  # Raffle: one card
    body["slides"].append({"countdown": {"label": "WARM-UP", "length": "0:10"}})
    body["slides"].reverse()
    assert api.put("/api/loops/2", json=body).status_code == 200
    assert [s["type"] for s in api.get("/api/event").json()["loops"][2]["slides"]] == ["countdown", "card"]


def test_a_broken_edit_leaves_the_file_alone(client):
    api, path = client
    before = path.read_text(encoding="utf-8")
    body = loop_body(api.get("/api/event").json(), 0)
    body["slides"] = [
        s for s in body["slides"] if not (s.get("card") or {}).get("id")
    ]  # drop the slides others link to
    res = api.put("/api/loops/0", json=body)
    assert res.status_code == 422 and "links to unknown id" in res.json()["detail"]
    assert path.read_text(encoding="utf-8") == before


def test_undo_and_redo_step_through_saved_changes(client):
    api, path = client
    original = path.read_text(encoding="utf-8")
    body = loop_body(api.get("/api/event").json(), 2)
    body["hold"] = 7
    api.put("/api/loops/2", json=body)
    assert api.get("/api/event").json()["can_undo"]
    api.post("/api/undo")
    assert path.read_text(encoding="utf-8") == original
    api.post("/api/redo")
    assert api.get("/api/event").json()["loops"][2]["hold"] == 7


def test_copy_a_slide_into_another_loop(client):
    api, _ = client
    assert api.post("/api/copy", json={"loop": 2, "n": 0, "target": 0}).status_code == 200
    event = api.get("/api/event").json()
    copied, original = event["loops"][0]["slides"][-1], event["loops"][2]["slides"][0]
    assert copied["raw"] == {k: v for k, v in original["raw"].items()}  # same content
    assert not copied["linked"] and "ref" not in next(iter(copied["raw"].values()))


def test_theme_change_and_version_restore(client, tmp_path):
    api, _ = client
    api.post(
        "/api/export", json={"loops": [2], "out_dir": str(tmp_path / "out"), "formats": ["png"]}
    )  # keeps a version
    (version,) = api.get("/api/versions").json()
    assert api.put("/api/theme", json={"theme": {"primary": "#0055AA"}}).status_code == 200
    assert api.get("/api/event").json()["theme"]["primary"] == "#0055AA"
    assert api.post(f"/api/versions/{version['name']}/restore").status_code == 200
    assert api.get("/api/event").json()["theme"]["primary"] == "#1F6FD1"


def test_the_team_look_starts_events_and_an_event_can_go_back_to_it(client):
    api, _ = client
    assert api.put("/api/settings", json={"theme": {"primary": "#1f6fd1", "accent": "#F2B632"}}).status_code == 200
    assert api.get("/api/home").json()["settings"]["theme"]["primary"] == "#1F6FD1"
    assert api.put("/api/settings", json={"theme": {"primary": "blue"}}).status_code == 422
    assert not api.get("/api/event").json()["team_look"]  # the example event has its own colours
    assert api.post("/api/theme/reset").status_code == 200
    event = api.get("/api/event").json()
    assert event["team_look"] and event["theme"]["primary"] == "#1F6FD1"
    api.put("/api/theme", json={"theme": {"accent": "#00FF00"}})
    assert not api.get("/api/event").json()["team_look"]
    api.post("/api/undo")
    assert api.get("/api/event").json()["team_look"]
    slug = api.post("/api/events", json={"name": "Next meet", "starter": "blank"}).json()["slug"]
    api.post(f"/api/events/{slug}/open")
    assert api.get("/api/event").json()["team_look"]


def test_reset_copies_the_team_logo_into_the_event(client):
    api, path = client
    logo = next((path.parent / "assets").glob("*.png"))
    with logo.open("rb") as fh:
        assert api.post("/api/settings/logo", files={"file": ("team.png", fh)}).status_code == 200
    assert not api.get("/api/event").json()["team_look"]  # a different logo picture
    api.post("/api/theme/reset")
    event = api.get("/api/event").json()
    assert event["team_look"] and (path.parent / event["theme"]["logo"]).exists()


def test_an_event_can_keep_its_own_theme_until_the_team_theme_changes(client):
    api, _ = client
    api.put("/api/settings", json={"theme": {"primary": "#00AA00"}})
    event = api.get("/api/event").json()
    assert not event["team_look"] and event["offer_team_theme"]  # the editor offers the team theme
    assert api.post("/api/theme/keep").status_code == 200
    assert not api.get("/api/event").json()["offer_team_theme"]
    api.put("/api/settings", json={"team": "Riverside"})  # a change that isn't the team theme
    assert not api.get("/api/event").json()["offer_team_theme"]
    api.put("/api/settings", json={"theme": {"primary": "#0000AA"}})  # a new team theme: offered again
    assert api.get("/api/event").json()["offer_team_theme"]
    api.post("/api/theme/keep")
    api.post("/api/undo")
    assert api.get("/api/event").json()["offer_team_theme"]
    api.put("/api/theme", json={"theme": {"accent": "#00FF00"}})  # colours of its own: kept on purpose
    assert not api.get("/api/event").json()["offer_team_theme"]
    api.post("/api/theme/reset")
    event = api.get("/api/event").json()
    assert event["team_look"] and not event["offer_team_theme"]


def test_saving_settings_keeps_the_open_event_undo_history(client, tmp_path):
    api, _ = client
    body = loop_body(api.get("/api/event").json(), 2)
    body["hold"] = 7
    api.put("/api/loops/2", json=body)
    api.put("/api/settings", json={"team": "Riverside", "templates": ""})  # templates unchanged: sent as before
    assert api.get("/api/event").json()["can_undo"]
    folder = tmp_path / "Templates"
    folder.mkdir()
    api.put("/api/settings", json={"templates": str(folder)})  # a new folder: boards redrawn, undo kept
    event = api.get("/api/event").json()
    assert event["can_undo"] and event["templates_folder"] == str(folder)


def test_settings_preview_draws_a_sample_card(client):
    api, _ = client
    res = api.post("/api/settings/preview", json={"theme": {"primary": "#00AA00"}})
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert api.post("/api/settings/preview", json={"theme": {"text": "nope"}}).status_code == 422


def test_export_is_refused_while_a_loop_has_errors(client, tmp_path):
    api, _ = client
    body = loop_body(api.get("/api/event").json(), 2)
    body["slides"].append({"qr": {"url": "https://"}})
    api.put("/api/loops/2", json=body)
    res = api.post("/api/export", json={"loops": [2], "out_dir": str(tmp_path / "out")})
    assert res.status_code == 422 and "full web address" in res.json()["detail"]
    assert not (tmp_path / "out").exists()


def test_a_second_export_waits_for_the_first(client, tmp_path, monkeypatch):
    api, _ = client
    release = threading.Event()

    def slow_export(*_args):
        release.wait(10)  # the first export is still writing its files
        return []

    monkeypatch.setattr("app.server.export_loop", slow_export)
    body = {"loops": [2], "out_dir": str(tmp_path / "out"), "formats": ["wmv"]}
    first = api.post("/api/export", json=body).json()
    second = api.post("/api/export", json=body)
    assert second.status_code == 409 and "still running" in second.json()["detail"]
    release.set()
    while api.get(f"/api/jobs/{first['id']}").json()["state"] == "running":
        time.sleep(0.02)
    assert api.post("/api/export", json=body).status_code == 200  # free again once it's done


def test_qr_links_keep_their_case_and_bare_domains_pass(client):
    api, _ = client
    for url in ("https://example.org", "HTTPS://EXAMPLE.ORG", "https://bit.ly/AbC12"):
        slide = {"qr": {"url": url, "heading": ["MEET", "PROGRAM"]}}
        assert api.put("/api/slide", json={"loop": 2, "n": 0, "slide": slide}).status_code == 200
        assert api.get("/api/event").json()["loops"][2]["slides"][0]["raw"]["qr"]["url"] == url
        assert not [i for i in api.get("/api/checks").json() if i["loop"] == "Raffle" and i["level"] == "error"]


def test_preview_warnings_with_dashes_and_quotes_still_draw(client):
    """Warnings ride in a header, which only takes latin-1: one with “–” used to fail the whole preview."""
    api, _ = client
    card = {"card": {"layout": "banner", "lines": [{"text": f"Line {n}"} for n in range(1, 5)]}}
    res = api.post("/api/render", json={"loop": 2, "n": 0, "slide": card})
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert "kept but hidden" in unquote(res.headers["x-issues"])


def test_an_event_can_have_its_own_template_folder(client, tmp_path):
    api, path = client
    folder = tmp_path / "DisplayLink"
    folder.mkdir()
    (folder / "Welcome.tpl").write_bytes(b"not a real template; enough for the folder check")
    assert api.put("/api/event/templates", json={"folder": str(tmp_path / "missing")}).status_code == 422
    assert api.put("/api/event/templates", json={"folder": str(tmp_path)}).status_code == 200  # .tpl found below it
    res = api.put("/api/event/templates", json={"folder": str(folder), "make_default": False})
    assert res.status_code == 200 and res.json()["templates"] == 1
    event = api.get("/api/event").json()
    assert event["templates_folder"] == str(folder) and event["templates_source"] == "event"
    assert f"templates: {folder}" in path.read_text(encoding="utf-8")


def test_events_opened_from_home_use_their_own_template_folder(tmp_path):
    """Regression: an endpoint function named `templates` once shadowed create_app's `templates` argument,
    so every event opened from the home page looked for its boards in a folder named after a function."""
    lib = Library(tmp_path / "Loop Builder")
    folder = tmp_path / "DisplayLink"
    folder.mkdir()
    (folder / "Welcome.tpl").write_bytes(b"placeholder")
    lib.update_settings(templates=str(folder))
    api = TestClient(create_app(library=lib))
    slug = api.post("/api/events", json={"name": "Home test", "starter": "blank"}).json()["slug"]
    assert api.post(f"/api/events/{slug}/open").status_code == 200
    event = api.get("/api/event").json()
    assert (
        event["templates_folder"] == str(folder)
        and event["templates_found"]
        and event["templates_source"] == "settings"
    )
    assert api.get("/api/templates").json()["templates"] == ["Welcome.tpl"]


def test_the_event_says_whether_a_template_folder_is_set_at_all(client, tmp_path):
    api, _ = client
    event = api.get("/api/event").json()
    assert not event["templates_set"] and not event["templates_found"]  # a fresh install: nothing chosen yet
    folder = tmp_path / "Templates"
    folder.mkdir()
    (folder / "Welcome.tpl").write_bytes(b"enough for the folder check")
    assert api.put("/api/event/templates", json={"folder": str(folder), "make_default": False}).status_code == 200
    event = api.get("/api/event").json()
    assert event["templates_set"] and event["templates_found"]
    shutil.rmtree(folder)  # set, but not on this computer (an event made on another machine)
    event = api.get("/api/event").json()
    assert event["templates_set"] and not event["templates_found"]


def test_about_has_the_version_links_and_notices(client):
    api, _ = client
    about = api.get("/api/about").json()
    assert about["version"] and about["project"].startswith("https://github.com/")
    assert "Apache" in about["notices"] and "x264" in about["notices"]


def test_rename_and_redate_the_open_event_and_undo_it(client):
    api, path = client
    res = api.put("/api/event/details", json={"name": "  Dual meet   (copy) ", "date": "2026-11-07"})
    assert res.status_code == 200
    event = api.get("/api/event").json()
    assert event["name"] == "Dual meet (copy)" and event["date"] == "2026-11-07" and event["can_undo"]
    assert event["slug"] == "event"  # the folder keeps its name
    api.post("/api/undo")
    assert api.get("/api/event").json()["name"] != "Dual meet (copy)"
    assert api.put("/api/event/details", json={"name": "Sections", "date": ""}).status_code == 200
    assert api.get("/api/event").json()["date"] is None and "date:" not in path.read_text(encoding="utf-8")


def test_an_event_needs_a_name_and_a_real_date(client):
    api, path = client
    before = path.read_text(encoding="utf-8")
    assert api.put("/api/event/details", json={"name": "   ", "date": "2026-11-07"}).status_code == 422
    assert api.put("/api/event/details", json={"name": "Sections", "date": "next Friday"}).status_code == 422
    assert api.put("/api/event/details", json={"name": "Sections", "date": "2026-02-30"}).status_code == 422
    assert path.read_text(encoding="utf-8") == before


def test_a_duplicate_can_be_renamed_and_any_event_deleted(tmp_path):
    lib = Library(tmp_path / "Loop Builder")
    api = TestClient(create_app(library=lib))
    first = api.post("/api/events", json={"name": "Dual", "date": "2026-10-01", "starter": "blank"}).json()["slug"]
    copy = api.post(f"/api/events/{first}/duplicate", json={"name": "Dual (copy)", "date": "2026-10-24"}).json()
    api.post(f"/api/events/{copy['slug']}/open")
    api.put("/api/event/details", json={"name": "Dual: Lakeview", "date": "2026-11-07"})
    found = {e["slug"]: (e["name"], e["date"]) for e in api.get("/api/home").json()["events"]}
    assert found == {first: ("Dual", "2026-10-01"), copy["slug"]: ("Dual: Lakeview", "2026-11-07")}
    assert api.delete(f"/api/events/{first}").status_code == 200
    assert not (lib.events_dir / first).exists()
    assert api.delete(f"/api/events/{copy['slug']}").status_code == 200  # the open one: the editor closes it
    assert api.get("/api/home").json()["events"] == [] and api.get("/api/home").json()["open"] is None
    assert api.get("/api/event").status_code == 409
    assert api.delete(f"/api/events/{first}").status_code == 422  # already gone
    assert api.delete("/api/events/..").status_code in (404, 422) and lib.events_dir.exists()


def test_the_home_team_name_and_logo_in_lanes_follow_use_team_theme(client):
    api, path = client
    logos = sorted((path.parent / "assets").glob("*.png"))
    with logos[0].open("rb") as fh:
        api.post("/api/settings/logo", files={"file": ("team.png", fh)})
    api.put("/api/settings", json={"team": "Riverside Otters"})
    api.post("/api/theme/reset")
    home = api.post("/api/teams/_home/use").json()
    body = loop_body(api.get("/api/event").json(), 0)
    lanes = [{"name": "RIVERSIDE|OTTERS", "logo": home["logo"]}, {}]
    body["slides"].append({"lanes": {"title": "Lanes", "lanes": lanes}})
    api.put("/api/loops/0", json=body)
    event = api.get("/api/event").json()
    assert event["team_look"]  # the lane shows the team's name, with a line break of its own
    api.put("/api/settings", json={"team": "Riverside Swim Club"})
    event = api.get("/api/event").json()
    assert not event["team_look"] and event["offer_team_theme"]  # a new name is offered, like a new logo
    api.post("/api/theme/keep")
    assert not api.get("/api/event").json()["offer_team_theme"]
    with logos[1].open("rb") as fh:
        api.post("/api/settings/logo", files={"file": ("team.png", fh)})
    assert api.get("/api/event").json()["offer_team_theme"]
    api.post("/api/theme/reset")
    event = api.get("/api/event").json()
    lane = event["loops"][0]["slides"][-1]["raw"]["lanes"]["lanes"][0]
    assert event["team_look"] and lane["name"] == "Riverside Swim Club"  # team_look: the lane has the new logo too


def test_import_a_package_picked_with_the_open_dialog(tmp_path):
    lib = Library(tmp_path / "Loop Builder")
    api = TestClient(create_app(library=lib))
    slug = api.post("/api/events", json={"name": "Sections", "date": "2026-10-01", "starter": "blank"}).json()["slug"]
    package = tmp_path / "Sections.loopevent"
    assert api.post(f"/api/events/{slug}/package", json={"path": str(package)}).status_code == 200
    copy = api.post("/api/events/import-file", json={"path": str(package)}).json()["slug"]
    names = sorted(e["name"] for e in api.get("/api/home").json()["events"])
    assert copy != slug and names == ["Sections", "Sections (2)"]
    assert api.post("/api/events/import-file", json={"path": str(tmp_path / "nope.loopevent")}).status_code == 422
