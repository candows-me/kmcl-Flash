# -*- mode: python ; coding: utf-8 -*-
import shutil
import os
import json


# 资源说明：
# - ico.png / 字体包 / img / imgpng / blockicons / obsidian_engine
#   均打进 onedir 的 _internal（开发模式与打包后均以 _internal 为 BASE_DIR）
# - img = 启动画面/图标/头像等素材；imgpng = 界面壁纸（设置页背景缩略图扫描此目录）
# - blockicons = 下载游戏页版本类型图标（官方方块材质，从客户端 jar 提取）
# - launcher_config.json 不打包旧配置（含开发机绝对路径），改为构建后生成干净默认配置
# - 皮肤 / 曜音音乐 / 好友功能已移除，不再打包 skins / skin_config.json / yaoyin_data / friends_data
# - 联机工具（Kmcl MC联机器）与内置 JDK（runtime）在构建后复制到 exe 同级目录
def _data_if_exists(src, dst):
    return (src, dst) if os.path.exists(src) else None

_datas = [
    d for d in [
        _data_if_exists('ico.png', '.'),
        _data_if_exists('Kmcl Minecraft!Launcher Fonts.ttf', '.'),
        _data_if_exists('Kmcl Pixel Font.ttf', '.'),
        _data_if_exists('Kmcl Pixel Font-OFL.txt', '.'),
        _data_if_exists('assets/wallpapers', 'assets/wallpapers'),      # 界面壁纸（缺失则背景消失）
        _data_if_exists('assets/icons', 'assets/icons'),                # 版本类型图标（release/snapshot/old_alpha/old_beta）
        _data_if_exists('assets/bg_wallpaper.png', 'assets/bg_wallpaper.png'),  # 兜底壁纸
        _data_if_exists('_internal/plants-vs', 'plants-vs'),  # 离线小游戏（实验室启动）
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
    # 注意：psutil / requests 是「实验室」页面（内存优化器 / 下载器 / 垃圾清理）
    # 的必需依赖，绝不能排除！其余大件（numpy/PIL/tkinter 等）与本项目无关，
    # 排除以减小体积。
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
    [],
    exclude_binaries=True,
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
    version='kmcl_version_info.txt',  # exe 属性 → 详细信息（简介/开发者/版权）
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Kmcl Minecraft！Launcher',
)

# ============================================================
# 构建后处理
# ============================================================
# DISTPATH 是 PyInstaller 注入的 --distpath 绝对路径；用它而非硬编码 'dist'，
# 这样用 --distpath 把产物指到桌面时后处理（配置/runtime/联机工具复制）也能落到位。
_dist_root = os.path.join(DISTPATH, 'Kmcl Minecraft！Launcher')
_dist_internal = os.path.join(_dist_root, '_internal')

# 1) 生成干净的默认配置（不含任何开发机绝对路径）：
#    - mc_root / java_path 留空 → 运行时自动使用 _internal/.minecraft 与内置 runtime JDK
_default_config = {
    "player_name": "Kmcl Player",
    "game_version": "",
    "java_path": "",
    "mc_root": "",
    "current_page": "home",
    "background_image": "",
    "blur_radius": 30,
    "wallpaper": "01_nature",
    "font_style": "default",
    "grass_engine": {
        "enabled": False,
        "auto_optimize": False,
        "preset": "balanced",
        "taa": False,
        "blur": False,
    },
    "version_isolation": False,
    "launcher_visibility": "visible",
    "compat_opengl": False,
    "compat_vulkan": False,
    "custom_jvm_args": "",
    "custom_game_args": "",
    "default_mem_mb": 4049,
    "ui_lang": "zh_CN",
    "download_threads": 8,
    "win_w": 1280,
    "win_h": 800,
    "game_lang": "zh_cn",
}
try:
    with open(os.path.join(_dist_internal, 'launcher_config.json'), 'w', encoding='utf-8') as f:
        json.dump(_default_config, f, indent=2, ensure_ascii=False)
    print('[spec] 已生成干净默认配置 launcher_config.json')
except Exception as e:
    print('[spec] 生成默认配置失败: %s' % e)

# 2) 把内置 JDK（runtime/）复制到 exe 同级目录。
#    体积取舍：只带 JDK8 / JDK17 / JDK21（覆盖所有已发布 MC 版本），
#    JDK25 目前没有游戏版本需要，不复制以减小体积。
import stat

def _force_rmtree(path):
    """删除目录，遇到只读文件自动去掉属性重试（JDK 自带只读 classes.jsa）。"""
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    if os.path.isdir(path):
        shutil.rmtree(path, onerror=_onerror)

_dist_runtime = os.path.join(_dist_root, 'runtime')
_BUNDLED_JDKS = ['JDK8', 'JDK17', 'JDK21']

# JDK 瘦身：运行 Minecraft 只需 java.exe + 运行库，以下文件对游戏运行
# 完全无用，复制后删除可让分发包减小约 330MB：
#   lib/src.zip  — Java 源码（约 50MB/套）
#   jmods/       — 仅 jlink 定制运行时时才用（JDK9+，约 75MB/套）
#   include/     — JNI 开发头文件（约 0.2MB/套）
#   classes.jsa  — AppCDS 类加载缓存，缺失时 JVM 静默跳过，不影响运行
# 注意：legal/（许可证）必须保留；不要删 modules 镜像（java 运行依赖）。
def _slim_jdk(path):
    removed = 0
    for root, dirs, files in os.walk(path):
        for fn in files:
            if fn in ('src.zip', 'classes.jsa'):
                try:
                    os.remove(os.path.join(root, fn))
                    removed += 1
                except OSError:
                    pass
        for dn in ('jmods', 'include'):
            if dn in dirs:
                _force_rmtree(os.path.join(root, dn))
                dirs.remove(dn)
    return removed

if os.path.isdir('runtime'):
    _force_rmtree(_dist_runtime)
    os.makedirs(_dist_runtime, exist_ok=True)
    for _jdk in _BUNDLED_JDKS:
        _src = os.path.join('runtime', _jdk)
        if os.path.isdir(_src):
            _dst = os.path.join(_dist_runtime, _jdk)
            shutil.copytree(_src, _dst)
            _n = _slim_jdk(_dst)
            print('[spec] 已复制并瘦身 %s（删除 %d 个冗余文件/目录）' % (_jdk, _n))
        else:
            print('[spec] 警告：未找到 ' + _src)
else:
    print('[spec] 警告：未找到 runtime/ 源目录，内置 Java 未复制！')

# 3) 复制外部联机工具到 exe 同级目录（启动器在
#    <exe目录>/Kmcl MC联机器/ 下查找联机工具主程序）
# 复制时剔除解包分析残留（代码只扫描 .exe，不引用该目录，约 19MB）
_MP_RESIDUE = '闪通MC联机器.exe_extracted'
_mp_src = '联机工具'
_dist_mp = os.path.join(_dist_root, _mp_src)
if os.path.isdir(_mp_src):
    _force_rmtree(_dist_mp)
    shutil.copytree(_mp_src, _dist_mp,
                    ignore=shutil.ignore_patterns(_MP_RESIDUE))
    print('[spec] 联机工具已复制到 ' + _dist_mp)
else:
    print('[spec] 警告：未找到 %s 源目录，联机工具未复制！' % _mp_src)

# 5) plants-vs（Electron 离线小游戏）语言包瘦身：只保留英文回退与简体中文，
#    删除其余 53 个 Chromium 语言包（约 25MB），缺失时 Electron 自动回退英文。
_PV_LOC = os.path.join(_dist_internal, 'plants-vs', 'locales')
_PV_KEEP = ('en-US.pak', 'zh-CN.pak')
if os.path.isdir(_PV_LOC):
    _pn = 0
    for _f in os.listdir(_PV_LOC):
        if _f.endswith('.pak') and _f not in _PV_KEEP:
            try:
                os.remove(os.path.join(_PV_LOC, _f))
                _pn += 1
            except OSError:
                pass
    print('[spec] plants-vs 语言包瘦身：删除 %d 个非中英语言包' % _pn)
