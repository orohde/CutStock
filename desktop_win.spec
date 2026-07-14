# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec für die CutStock Desktop-App (Windows, pywebview/WebView2)."""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("webview")
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
datas += collect_data_files("webview")

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PyQt6", "tkinter", "matplotlib", "numpy", "scipy"],
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
    icon="assets/icon.ico",
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
