# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TorProxy Manager.

Собирает main.py в один exe (--onefile).
Папку tools/ нужно положить рядом с exe вручную — она содержит
бинарники proxychains, которые не встраиваются в exe.
"""

import os
import sys

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('translations', 'translations'),
    ],
    hiddenimports=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.sip',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pydoc',
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TorProxyManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI-приложение, без консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=None,
)
