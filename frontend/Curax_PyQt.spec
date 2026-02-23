# -*- mode: python ; coding: utf-8 -*-
# Build single .exe: from project root run: pyinstaller pyqt/Curax_PyQt.spec
# Output: dist/Curax_PyQt.exe (one file with all functions)

import os

# pyqt folder (where this spec lives)
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ENTRY = os.path.join(SPEC_DIR, 'main_pyqt.py')

a = Analysis(
    [ENTRY],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=[],
    hiddenimports=[
        'db',
        'core',
        'core.controller',
        'core.alert_scheduler',
        'ui',
        'ui.main_window',
        'ui.styles',
        'auth.pin_dialog',
        'auth.verify_esp32',
        'connection.serial_connection',
        'theme',
        'theme.tokens',
        'theme.dark',
        'theme.light',
        'theme.cards',
        'ui.tabs.main_panel_tab',
        'ui.tabs.add_medicine_tab',
        'ui.tabs.dose_tracking_tab',
        'ui.tabs.medical_reminders_tab',
        'ui.tabs.alerts_tab',
        'ui.tabs.temp_adjustment_tab',
        'ui.tabs.settings_tab',
        'ui.widgets.circular_progress',
        'ui.widgets.clickable_card',
        'serial',
        'serial.tools.list_ports',
        'schedule',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Curax_PyQt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,
)
