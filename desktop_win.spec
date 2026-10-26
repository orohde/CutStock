# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec für die CutStock Desktop-App (Windows, pywebview/WebView2)."""

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Python-DLLs explizit einbinden (pywebview/EdgeChromium braucht python3XX.dll)
_binaries = []
if sys.platform == "win32":
    for _dll in [f"python{sys.version_info.major}{sys.version_info.minor}.dll", "python3.dll"]:
        _path = os.path.join(sys.prefix, _dll)
        if os.path.exists(_path):
            _binaries.append((_path, "."))

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("webview")
    + collect_submodules("pythonnet")
    + collect_submodules("clr_loader")
    + [
        "core", "core.db", "core.models", "core.optimize", "core.pdf",
        "core.lock", "core.settings",
        "web", "web.app", "ui", "ui.i18n",
        "anyio", "click", "h11", "httptools", "websockets",
        "reportlab", "clr",
    ]
)

datas = [
    ("web/static", "web/static"),
    ("assets/icon.jpg", "assets"),
    ("VERSION", "."),
]
datas += collect_data_files("webview")
datas += collect_data_files("clr_loader")
datas += collect_data_files("pythonnet")

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=_binaries,
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
