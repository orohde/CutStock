# -*- mode: python ; coding: utf-8 -*-

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

app = BUNDLE(
    coll,
    name='CutStock.app',
    icon='assets/icon.icns',
    bundle_identifier='one.rohde.cutstock',
    info_plist={
        'CFBundleShortVersionString': '2026.06.01',
        'CFBundleName': 'CutStock',
        'NSHighResolutionCapable': True,
    },
)
