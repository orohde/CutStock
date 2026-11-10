# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec für die CutStock Druckbrücke (macOS, Symbol in der Menüleiste)."""

from pathlib import Path

VERSION = (Path(SPECPATH) / "VERSION").read_text().strip()

# libusb für den USB-Zugriff auf den P-touch (core/drucker.py lädt sie per ctypes)
LIBUSB = Path("/opt/homebrew/opt/libusb/lib/libusb-1.0.0.dylib")
binaries = [(str(LIBUSB), ".")] if LIBUSB.is_file() else []

a = Analysis(
    ["bruecke/app.py"],
    pathex=["."],
    binaries=binaries,
    datas=[("VERSION", "."), ("LICENSE", "."), ("THIRD_PARTY_NOTICES.txt", ".")],
    hiddenimports=["bruecke", "bruecke.verbindung", "core", "core.drucker", "core.ptouch",
                   "certifi"],
    excludes=["PySide6", "PyQt5", "PyQt6", "tkinter", "matplotlib", "reportlab", "PIL",
              "fastapi", "uvicorn", "webview", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CutStock Druckbruecke",
          debug=False, strip=False, upx=False, console=False)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="CutStock Druckbruecke")

app = BUNDLE(
    coll,
    name="CutStock Druckbrücke.app",
    icon="assets/icon.icns",
    bundle_identifier="one.rohde.cutstock-druckbruecke",
    info_plist={
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundleName": "CutStock Druckbrücke",
        "LSUIElement": True,             # kein Dock-Symbol, nur Menüleiste
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "PolyForm Noncommercial 1.0.0 – siehe LICENSE",
    },
)
