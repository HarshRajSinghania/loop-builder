# Third-party notices

Loop Builder's own code is licensed under the Apache License 2.0 (see `LICENSE`).

The packaged app (the Windows installer and portable zip, and the Mac .dmg) also contains the software
below, each under its own license.

## GPL components in the packaged app

PyAV's binary wheels include **FFmpeg** built with **x264** (the H.264 encoder Loop Builder uses for review
MP4s). x264 is licensed under the GNU General Public License, so FFmpeg in that build is GPL as well, and
**the packaged app as a whole is distributed under the terms of the GNU GPL version 3**. Loop Builder's
Apache-2.0 code may be combined with GPLv3 software this way. Its complete source code is at
https://github.com/mhuot/loop-builder, and the source of FFmpeg, x264 and the other libraries is at the
addresses below.

| Component | License | Source |
|---|---|---|
| FFmpeg (in PyAV) | GPL v3 in this build (LGPL v2.1+ on its own) | https://ffmpeg.org |
| x264 (in PyAV) | GPL v2 or later | https://www.videolan.org/developers/x264.html |

## Other libraries

| Component | License | Source |
|---|---|---|
| PyAV | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| Pillow | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| NumPy | BSD-3-Clause (with 0BSD, MIT, Zlib, CC0 parts) | https://numpy.org |
| pywebview | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| FastAPI | MIT | https://github.com/fastapi/fastapi |
| Starlette | BSD-3-Clause | https://github.com/Kludex/starlette |
| Uvicorn | BSD-3-Clause | https://uvicorn.dev |
| Pydantic, pydantic-core | MIT | https://github.com/pydantic/pydantic |
| python-multipart | Apache-2.0 | https://github.com/Kludex/python-multipart |
| PyYAML | MIT | https://github.com/yaml/pyyaml |
| qrcode | BSD-3-Clause | https://github.com/lincolnloop/python-qrcode |
| zxing-cpp | Apache-2.0 | https://github.com/zxing-cpp/zxing-cpp |
| AnyIO | MIT | https://github.com/agronholm/anyio |
| h11 | MIT | https://github.com/python-hyper/h11 |
| Click | BSD-3-Clause | https://github.com/pallets/click |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| typing-extensions | PSF-2.0 | https://github.com/python/typing_extensions |
| annotated-types, typing-inspection, annotated-doc | MIT | https://github.com/pydantic |
| bottle, proxy-tools (pywebview) | MIT | https://bottlepy.org, https://github.com/jtushman/proxy_tools |
| PyObjC (Mac only) | MIT | https://github.com/ronaldoussoren/pyobjc |
| Python | PSF License | https://www.python.org |
| Microsoft Edge WebView2 bootstrapper (Windows installer only) | Microsoft software license | https://developer.microsoft.com/microsoft-edge/webview2/ |

Each library's full license text is in its source repository. Loop Builder draws slides with the system's
Arial or a compatible font (Arimo or Liberation Sans) already on the computer; no font is bundled.
