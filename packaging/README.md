# Packaging

Loop Builder ships as a folder app built by PyInstaller, wrapped for each platform:

| Platform | Download | Made by |
| --- | --- | --- |
| Mac | `Loop Builder-<version>.dmg` (drag the app to Applications) | `packaging/mac/make_dmg.sh` |
| Windows | `LoopBuilder-Setup-<version>.exe` (per-user, no administrator rights) | `packaging/windows/loopbuilder.iss` (Inno Setup 6) |
| Windows | `Loop Builder-<version>-portable.zip` (runs from any folder or USB stick) | `packaging/windows/make_portable.ps1` |

The version is set in `app/version.py`; `packaging/version.py` reads it for the build scripts. A release is a git tag
`v<version>` that matches it.

## Build locally

Mac:

```sh
.venv/bin/pyinstaller packaging/loopbuilder.spec --noconfirm
packaging/mac/make_dmg.sh dist dist
```

Windows (PowerShell, Python 3.13 and Inno Setup 6 installed):

```powershell
.venv\Scripts\pyinstaller packaging\loopbuilder.spec --noconfirm
# optional: Microsoft's WebView2 bootstrapper, run by the installer only when WebView2 is missing
Invoke-WebRequest https://go.microsoft.com/fwlink/p/?LinkId=2124703 -OutFile packaging\windows\MicrosoftEdgeWebview2Setup.exe
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=0.1.0 /DDistDir=$PWD\dist /DOutDir=$PWD\dist packaging\windows\loopbuilder.iss
packaging\windows\make_portable.ps1 -Dist dist -Out dist
```

Without the bootstrapper file the installer still builds; it just can't add WebView2 on a PC that lacks it.

## CI

`.github/workflows/build.yml` runs on tags `v*` and by hand. On macOS and Windows runners it installs
`requirements-dev.txt`, runs the tests, builds with PyInstaller and makes the downloads above. Each run
uploads them as artifacts; a tag also publishes them on a GitHub Release.

## Signing (optional)

Unsigned builds work, but Macs block unsigned apps and Windows SmartScreen warns about them. Each platform signs
only when its settings exist, so a fork without them still builds.

**Mac**: repository secrets. Signing needs a paid Apple Developer Program membership.

| Secret | Used for |
| --- | --- |
| `MAC_CERT_P12`, `MAC_CERT_PASSWORD` | the Developer ID Application certificate (base64 .p12) imported on the Mac runner |
| `APPLE_SIGN_IDENTITY` | the codesign identity, e.g. `Developer ID Application: <Name> (<TEAMID>)` |
| `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` | notarizing with `notarytool` (an app-specific password) |

**Windows**: Azure Artifact Signing, through
`azure/artifact-signing-action`. The build signs `Loop Builder.exe` before Inno Setup packs it and the finished
installer after. It signs in to Azure with GitHub's OIDC token, so no password or key is stored: the settings are
plain variables (not secrets) of the `release` environment, which only `v*` tags and `main` may use.

| Variable (`release` environment) | Used for |
| --- | --- |
| `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | the Azure app registration the build signs in as (its federated credential trusts this repository's `release` environment) |
| `AZURE_SIGNING_ENDPOINT` | the Artifact Signing account's regional endpoint, e.g. `https://eus.codesigning.azure.net/` |
| `AZURE_SIGNING_ACCOUNT`, `AZURE_CERT_PROFILE` | the Artifact Signing account and its certificate profile |

`loopbuilder.iss` has a `Sign` define (`iscc /DSign ...`) for signing locally with a `signtool` set up in Inno
Setup; CI doesn't use it.

## Updates

`app/updates.py` checks a GitHub "latest release" URL for a newer version. It sends one GET and nothing
else, and is off unless the app is built with a releases URL.
