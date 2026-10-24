"""The update check: compares versions and never raises; no network (urlopen is replaced)."""

import io
import json
import urllib.error

import pytest

from app import updates

URL = "https://api.example.invalid/releases/latest"


def stub(monkeypatch, payload=None, error=None):
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, request.get_method(), request.data, timeout))
        if error:
            raise error
        return io.BytesIO(json.dumps(payload).encode() if not isinstance(payload, bytes) else payload)

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_newer_release_is_offered(monkeypatch):
    seen = stub(monkeypatch, {"tag_name": "v0.2.0", "html_url": "https://example.invalid/r/v0.2.0"})
    assert updates.check_for_update("0.1.0", URL) == {"version": "0.2.0", "url": "https://example.invalid/r/v0.2.0"}
    assert seen == [(URL, "GET", None, 3)]  # one GET, nothing sent


@pytest.mark.parametrize("tag", ["v0.1.0", "v0.0.9", "nightly", None])
def test_same_older_or_odd_versions_are_ignored(monkeypatch, tag):
    stub(monkeypatch, {"tag_name": tag, "html_url": "x"})
    assert updates.check_for_update("0.1.0", URL) is None


def test_drafts_and_prereleases_are_ignored(monkeypatch):
    stub(monkeypatch, {"tag_name": "v9.0.0", "prerelease": True})
    assert updates.check_for_update("0.1.0", URL) is None


@pytest.mark.parametrize("error", [urllib.error.URLError("offline"), TimeoutError(), OSError("reset")])
def test_network_problems_mean_no_update(monkeypatch, error):
    stub(monkeypatch, error=error)
    assert updates.check_for_update("0.1.0", URL) is None


def test_bad_json_means_no_update(monkeypatch):
    stub(monkeypatch, b"<html>not json</html>")
    assert updates.check_for_update("0.1.0", URL) is None


def test_no_url_means_checking_is_off(monkeypatch):
    seen = stub(monkeypatch, {"tag_name": "v9.9.9"})
    assert updates.check_for_update("0.1.0", None) is None and not seen


def test_version_parsing():
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("1.10.0") > updates.parse_version("1.9.9")
    assert updates.parse_version("1.2") is None
