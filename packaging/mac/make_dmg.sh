#!/usr/bin/env bash
# Build "Loop Builder-<version>.dmg" from the PyInstaller app, with a drag-to-Applications layout.
#   packaging/mac/make_dmg.sh [DIST_DIR] [OUT_DIR]      (defaults: dist, dist)
# Signing and notarization run only when these are set (CI secrets):
#   APPLE_SIGN_IDENTITY   e.g. "Developer ID Application: <Name> (<TEAMID>)"
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD   for notarytool
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="${1:-$ROOT/dist}"
OUT="${2:-$DIST}"
APP="$DIST/Loop Builder.app"
VERSION="$(python3 "$ROOT/packaging/version.py")"
DMG="$OUT/Loop Builder-$VERSION.dmg"

[ -d "$APP" ] || { echo "not found: $APP (run pyinstaller first)" >&2; exit 1; }
mkdir -p "$OUT"

if [ -n "${APPLE_SIGN_IDENTITY:-}" ]; then
  echo "Signing the app"
  codesign --force --deep --options runtime --timestamp \
    --entitlements "$ROOT/packaging/mac/entitlements.plist" --sign "$APPLE_SIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict "$APP"
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "Loop Builder" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

if [ -n "${APPLE_SIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp --sign "$APPLE_SIGN_IDENTITY" "$DMG"
fi
if [ -n "${APPLE_SIGN_IDENTITY:-}" ] && [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
  echo "Notarizing"
  xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$DMG"
fi
echo "$DMG"
