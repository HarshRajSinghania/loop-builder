"""Check for a newer Loop Builder release at launch.

The only thing sent is one HTTP GET to the releases URL (a GitHub "latest release" API URL, set in the
app's build). With no URL, checking is off. Network or format problems mean "no update", never an error."""

import json
import re
import urllib.error
import urllib.request

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def parse_version(text):
    """'v1.2.3' or '1.2.3' -> (1, 2, 3); anything else -> None."""
    match = _VERSION.fullmatch(str(text or "").strip())
    return tuple(int(n) for n in match.groups()) if match else None


def check_for_update(current_version, releases_url=None, timeout=3):
    """{"version", "url"} for a release newer than `current_version`, else None."""
    current = parse_version(current_version)
    if not releases_url or current is None:
        return None
    request = urllib.request.Request(releases_url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec: fixed https URL from the build
            release = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    latest = parse_version(release.get("tag_name"))
    if latest is None or latest <= current:
        return None
    return {"version": ".".join(map(str, latest)), "url": release.get("html_url")}
