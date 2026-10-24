# Zip the PyInstaller folder app as "Loop Builder-<version>-portable.zip".
#   pwsh packaging/windows/make_portable.ps1 [-Dist dist] [-Out dist]
param(
    [string]$Dist = "dist",
    [string]$Out = "dist"
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$version = (& python (Join-Path $root "packaging\version.py")).Trim()
$app = Join-Path $Dist "Loop Builder"
if (-not (Test-Path (Join-Path $app "Loop Builder.exe"))) { throw "not found: $app (run pyinstaller first)" }
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$zip = Join-Path $Out "Loop Builder-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $app -DestinationPath $zip
Write-Output $zip
