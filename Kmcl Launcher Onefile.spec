# -*- mode: python ; coding: utf-8 -*-
"""KMCL 单文件打包配置（onefile）：全部资源内嵌进单个 exe，无任何外部文件。

- 资源：ico.png / 字体×2 / assets/wallpapers / assets/icons / assets/bg_wallpaper
- 联机工具整目录内嵌（运行时从 _MEIPASS 释放启动）
- 可写数据（launcher_config.json / .icon_cache）由 mica_window.resolve_data_dir
  重定向到 exe 同级目录，配置可持久化
"""
import os


def _data_if_exists(src, dst):
    return (src, dst) if os.path.exists(src) else None


_datas = [
    d for d in [
        _data_if_exists('ico.png', '.'),
        _data_if_exists('Kmcl Minecraft!Launcher Fonts.ttf', '.'),
        _data_if_exists('Kmcl Pixel Font.ttf', '.'),
        _data_if_exists('Kmcl Pixel Font-OFL.txt', '.'),
        _data_if_exists('assets/wallpapers', 'assets/wallpapers'),
        _data_if_exists('assets/icons', 'assets/icons'),
        _data_if_exists('assets/bg_wallpaper.png', 'assets/bg_wallpaper.png'),
        _data_if_exists('联机工具', '联机工具'),
    ] if d
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=['java_manager', 'microsoft_auth'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy', 'PIL', 'gevent', 'pythonnet', 'cryptography',
        'tkinter', 'scipy', 'matplotlib', 'pandas', 'IPython',
        'jupyter', 'notebook', 'pytest', 'setuptools', 'pydoc_data',
    ],
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
    name='Kmcl Minecraft！Launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ico.ico',
    version='kmcl_version_info.txt',
)
