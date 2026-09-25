# PyInstaller spec for TechRadar.
# Ported from Prospector's installer\prospector.spec -- same one-folder
# reasoning applies unchanged (see the comments kept below).
#
# NOT YET BUILD-VERIFIED. TechRadar depends on crawl4ai, which hasn't been
# frozen with PyInstaller anywhere in this portfolio before -- run
# build_installer.ps1's "does every module import cleanly" check first,
# before assuming this spec is correct as written. faster-whisper (the
# optional local-transcription extra) is deliberately NOT bundled here --
# it's an opt-in extra in pyproject.toml, not part of the base install, and
# it drags in a heavy model-download story that doesn't belong in a
# double-click installer.
#
# Built by build_installer.ps1, which then wraps the folder in an Inno Setup
# installer. Run it from the project root:
#     pyinstaller installer\techradar.spec --noconfirm

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

block_cipher = None

hidden = []
for package in ("flask", "jinja2", "werkzeug", "click", "itsdangerous",
                "blinker", "httpx", "httpcore", "h11", "certifi", "anyio",
                "dotenv", "typer", "feedparser", "yaml", "crawl4ai",
                "youtube_transcript_api", "yt_dlp"):
    try:
        hidden += collect_submodules(package)
    except Exception:
        hidden.append(package)

# TechRadar's own modules are collected, never listed -- a hand-written list
# silently rots every time a module is renamed.
hidden += ["techradar"] + collect_submodules("techradar")
hidden += ["encodings.idna"]

a = Analysis(
    [str(ROOT / "installer" / "techradar_launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=sorted(set(hidden)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # faster-whisper and its torch/onnx dependency chain are excluded on
    # purpose -- it's the optional [transcribe] extra, not installed here.
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy", "PIL",
              "PySide6", "PyQt5", "notebook", "IPython", "pytest",
              "faster_whisper", "torch", "onnxruntime"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TechRadar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX compression is a common antivirus trigger
    console=False,           # windowed: the UI is the browser, not a terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "installer" / "techradar.ico")
        if (ROOT / "installer" / "techradar.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TechRadar",
)
