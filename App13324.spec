# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller 打包配置文件 - 实况照片播放器
版本: 3.21.0
作者: XAF
日期: 2026-05-02
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct, FixedFileInfo
)

APP_NAME = 'App13324'
APP_VERSION = '3.21.0'
APP_COPYRIGHT = 'Copyright © XAF 2026.4'
APP_DESCRIPTION = '实况照片播放器 - 支持 OPPO 实况照片、视频播放、文件管理'
APP_ICON = 'app.ico'

# 数据文件：vlc 运行时库、封面图片、应用图标
datas = [
    ('vlc', 'vlc'),
    ('cover', 'cover'),
    ('app.ico', '.'),
]

# 隐藏导入（解决模块遗漏）
hiddenimports = [
    'PIL._tkinter_finder',
    'PIL._webp',
    'PIL._imagingft',
    'PIL._imagingtk',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],          # 可按需排除不需要的模块以减小体积
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Windows 版本资源
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(3, 21, 0, 0),
        prodvers=(3, 21, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0)
    ),
    kids=[
        StringFileInfo(
            [StringTable('040904B0', [
                StringStruct('CompanyName', 'XAF Studio'),
                StringStruct('FileDescription', APP_DESCRIPTION),
                StringStruct('FileVersion', APP_VERSION),
                StringStruct('InternalName', APP_NAME),
                StringStruct('LegalCopyright', APP_COPYRIGHT),
                StringStruct('OriginalFilename', f'{APP_NAME}.exe'),
                StringStruct('ProductName', APP_NAME),
                StringStruct('ProductVersion', APP_VERSION),
            ])]
        ),
        VarFileInfo([VarStruct('Translation', [0x0409, 0x04B0])])
    ]
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                     # 启用 UPX 压缩（需安装 UPX）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[APP_ICON],
    version=version_info,         # 嵌入版本资源
)