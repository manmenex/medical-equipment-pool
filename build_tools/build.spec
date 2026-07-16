# -----------------------------------------------------------------------
# PyInstaller spec for Medical Device Recall Monitor.
#
# Build with:
#     pyinstaller build_tools/build.spec --noconfirm
# (or simply: python build_tools/build.py)
#
# Notes:
#   - app/database/schema.sql and .env.example are bundled as data files
#     so a fresh install can initialize its database and configuration.
#   - Playwright's browser binaries are NOT bundled here (they are large,
#     versioned, platform-specific downloads). After installing the
#     built app, run `python -m playwright install chromium` once, or
#     ship the browsers separately and point PLAYWRIGHT_BROWSERS_PATH at
#     them - see docs/INSTALL.md.
# -----------------------------------------------------------------------

# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# SPECPATH is injected by PyInstaller into the spec file's exec globals and
# points at the directory containing this .spec file, so the build works
# regardless of the caller's current working directory.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821

datas = [
    (os.path.join(REPO_ROOT, "app", "database", "schema.sql"), "app/database"),
    (os.path.join(REPO_ROOT, ".env.example"), "."),
    (os.path.join(REPO_ROOT, "resources"), "resources"),
]
datas += collect_data_files("PySide6", subdir="Qt/plugins")

hiddenimports = (
    collect_submodules("app")
    + collect_submodules("apscheduler")
    + ["keyring.backends", "playwright.sync_api"]
)

a = Analysis(
    [os.path.join(REPO_ROOT, "app", "main.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MedicalDeviceRecallMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MedicalDeviceRecallMonitor",
)
