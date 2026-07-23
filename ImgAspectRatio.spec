# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# 只收集 Playwright 驱动与数据，避免 collect_all 把无关内容打进包导致启动异常
playwright_datas = collect_data_files("playwright")
playwright_binaries = collect_dynamic_libs("playwright")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=playwright_binaries,
    datas=playwright_datas + [("draw.ico", ".")],
    hiddenimports=["playwright", "playwright.sync_api"],
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
    name="alexcard_tools-3.3.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 易损坏 python*.dll / 原生库，导致 Failed to start embedded python interpreter
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="draw.ico",
)
