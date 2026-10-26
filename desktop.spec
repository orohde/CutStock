# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec für die CutStock Desktop-App (macOS)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

VERSION = (Path(SPECPATH) / "VERSION").read_text().strip()

hiddenimports = (
    collect_submodules("uvicorn")
    + [
        "core", "core.db", "core.models", "core.optimize", "core.pdf",
        "core.lock", "core.settings",
        "web", "web.app", "ui", "ui.i18n",
        "anyio", "click", "h11", "httptools", "websockets",
        "reportlab",
    ]
)

datas = [
    ("web/static", "web/static"),
    ("assets/icon.jpg", "assets"),
    ("VERSION", "."),
]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PyQt6", "tkinter", "matplotlib", "numpy", "scipy",
              "pywebview", "webview", "pythonnet", "clr", "clr_loader"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CutStock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CutStock",
)

app = BUNDLE(
    coll,
    name="CutStock.app",
    icon="assets/icon.icns",
    bundle_identifier="one.rohde.cutstock",
    info_plist={
        "CFBundleShortVersionString": VERSION,
        "CFBundleName": "CutStock",
        "NSHighResolutionCapable": True,
    },
)
