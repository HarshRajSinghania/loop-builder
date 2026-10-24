"""The app version (the one place it is set; CI tags releases as v<VERSION>) and where to look for updates."""

VERSION = "0.1.4"

# The GitHub "latest release" API address for the public repo, e.g.
# https://api.github.com/repos/<owner>/<repo>/releases/latest. None until the repo exists: no update check.
RELEASES_URL = None
