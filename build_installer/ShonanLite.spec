# -*- mode: python ; coding: utf-8 -*-
import os

# このspecファイル自身の場所(build_installer/)を基準にパスを解決する。
# どのフォルダにcloneしても、またどのカレントディレクトリから実行しても動くよう、
# 絶対パスは使わない(SPECPATHはPyInstallerがspec実行時に定義する)。
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
APP_DIR = os.path.join(REPO_ROOT, 'app')


a = Analysis(
    [os.path.join(APP_DIR, 'gui', 'main.py')],
    pathex=[os.path.join(APP_DIR, 'gui')],
    binaries=[],
    datas=[
        (os.path.join(APP_DIR, 'docs', 'images'), 'docs/images'),
        (os.path.join(APP_DIR, 'assets'), 'assets'),
        (os.path.join(APP_DIR, 'gui', 'qml'), 'gui/qml'),
        (os.path.join(APP_DIR, 'rx'), 'rx'),
    ],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='ShonanLite',
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
    icon=[os.path.join(REPO_ROOT, 'windows', 'shonan_lite_icon.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ShonanLite',
)
