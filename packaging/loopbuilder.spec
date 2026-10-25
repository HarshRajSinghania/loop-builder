# PyInstaller spec: a folder app (not one self-contained .exe, which would unpack itself on every launch).
#   pyinstaller packaging/loopbuilder.spec --noconfirm
# Windows: dist/Loop Builder/Loop Builder.exe   Mac: dist/Loop Builder.app
# pylint: skip-file
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "packaging"))
from version import VERSION  # noqa: E402

version_file = None
if sys.platform == "win32":
    nums = tuple(int(p) for p in VERSION.split(".")[:3]) + (0,)
    version_file = Path(workpath) / "version_info.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Mike Huot'),
      StringStruct('LegalCopyright', '© 2026 Mike Huot. Apache License 2.0.'),
      StringStruct('FileDescription', 'Loop Builder'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('ProductName', 'Loop Builder'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "app" / "static"), "app/static"),
        (str(ROOT / "loopgen" / "templates.yaml"), "loopgen"),
        *[(str(ROOT / name), "app/legal") for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")],
    ],
    hiddenimports=collect_submodules("uvicorn") + ["zxingcpp", "webview"],
    excludes=["tkinter", "matplotlib", "numpy.testing"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Loop Builder", console=False,
          codesign_identity=None, entitlements_file=None,
          version=str(version_file) if version_file else None,
          icon=str(ROOT / "packaging" / "icons" / ("loop-builder.ico" if sys.platform == "win32" else "loop-builder.icns")))
coll = COLLECT(exe, a.binaries, a.datas, name="Loop Builder")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Loop Builder.app", bundle_identifier="io.github.mhuot.loopbuilder",
                 icon=str(ROOT / "packaging" / "icons" / "loop-builder.icns"),
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": VERSION,
                             "CFBundleVersion": VERSION,
                             "NSHumanReadableCopyright": "© 2026 Mike Huot. Apache License 2.0.",
                             # macOS asks before an app uses these folders; this is what it says why. Loop Builder
                             # keeps its own files in Application Support, so it asks only for a folder you name.
                             "NSDocumentsFolderUsageDescription":
                                 "Loop Builder opens the template, picture and export folders you choose here.",
                             "NSDownloadsFolderUsageDescription":
                                 "Loop Builder opens the template, picture and export folders you choose here.",
                             "NSDesktopFolderUsageDescription":
                                 "Loop Builder opens the template, picture and export folders you choose here."})
