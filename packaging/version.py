"""Build scripts read the app version from app/version.py, so it's set in one place. CI tags releases as v<VERSION>."""

import runpy
from pathlib import Path

VERSION = runpy.run_path(str(Path(__file__).resolve().parent.parent / "app" / "version.py"))["VERSION"]

if __name__ == "__main__":
    print(VERSION)
