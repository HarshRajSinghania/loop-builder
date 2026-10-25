"""The app version (the one place it is set; CI tags releases as v<VERSION>) and where to look for updates."""

VERSION = "0.1.7"

# Where the app asks, once at each start, whether a newer release exists (GitHub's "latest release" API).
# None turns the update check off.
RELEASES_URL = "https://api.github.com/repos/mhuot/loop-builder/releases/latest"

PROJECT_URL = "https://github.com/mhuot/loop-builder"
COPYRIGHT = "© 2026 Mike Huot"
