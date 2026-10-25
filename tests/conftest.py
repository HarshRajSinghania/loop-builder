"""Shared test setup: no test reaches the network, and every test client talks to the app as its own window does."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """Every create_app starts the update check, which asks GitHub's releases API: about 30 calls a run, against a
    limit of 60 an hour for the whole CI machine. The apps under test get no update instead; test_updates.py tests
    the check itself with its download stubbed."""
    monkeypatch.setattr("app.server.check_for_update", lambda *args: None)


@pytest.fixture(autouse=True)
def as_this_computer(monkeypatch):
    """The app answers only requests addressed to this computer (app.server.from_this_app), and a TestClient's
    default host is "testserver". Every client here starts at http://127.0.0.1 instead, so no test has to say so."""
    init = TestClient.__init__

    def local(self, app, base_url="http://127.0.0.1", **kwargs):
        init(self, app, base_url=base_url, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", local)
