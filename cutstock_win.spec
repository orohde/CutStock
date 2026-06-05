# -*- mode: python ; coding: utf-8 -*-
# Windows-Build-Konfiguration

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/icon.jpg', 'assets')],
    hiddenimports=['core', 'core.db', 'core.models', 'core.optimize', 'core.pdf',
                   'ui', 'ui.main_window', 'ui.tab_material', 'ui.tab_material_lager',
                   'ui.tab_saegeblatt', 'ui.tab_projekt', 'ui.tab_optimierung',
                   'ui.tab_einstellungen', 'ui.units', 'ui.i18n'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CutStock',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CutStock',
)
