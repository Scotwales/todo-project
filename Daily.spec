# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from datetime import datetime

from PyInstaller.utils.hooks import collect_all, collect_submodules


root = Path(SPECPATH)
build_date_file = root / "build" / "release" / "build_date.txt"
build_date_file.parent.mkdir(parents=True, exist_ok=True)
build_date_file.write_text(datetime.now().astimezone().date().isoformat(), encoding="utf-8")
datas = [
    (str(root / "templates"), "templates"),
    (str(root / "static"), "static"),
    (str(build_date_file), "."),
]
binaries = []
hiddenimports = []

for package in ("django", "apscheduler", "webview", "plyer", "openpyxl", "tzdata"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

hiddenimports += collect_submodules("config")
hiddenimports += collect_submodules("tasks")

a = Analysis(
    [str(root / "start_app.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Daily",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=str(root / "version.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Daily",
)
