"""Shared test setup: no test reaches the network."""

import pytest


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """Every create_app starts the update check, which asks GitHub's releases API: about 30 calls a run, against a
    limit of 60 an hour for the whole CI machine. The apps under test get no update instead; test_updates.py tests
    the check itself with its download stubbed."""
    monkeypatch.setattr("app.server.check_for_update", lambda *args: None)
