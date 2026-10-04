# -*- coding: utf-8 -*-
"""KMCL 社区维护版 - 主窗口（Mica 风格玻璃拟态 UI）。

main.py 引用本模块的 MicaMainWindow(BASE_DIR, icon_path=None)。
包含：自定义标题栏 / 左侧导航 / 首页 / 游戏库 / 联机大厅 / 游戏修复 / 设置 / 关于。
底层逻辑全部来自 kmcl-main 根目录的 java_manager / repair_game / multiplayer_manager / microsoft_auth。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QTimer, QSize, QPoint, QEvent,
                          QPropertyAnimation, QEasingCurve, QObject, QRectF)
from PyQt5.QtGui import QIcon, QPixmap, QFont, QPainterPath, QRegion, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QLabel, QPushButton, QFrame, QLineEdit, QComboBox, QListWidget,
    QListWidgetItem, QProgressBar, QPlainTextEdit, QCheckBox, QSlider, QSpinBox,
    QFileDialog, QInputDialog, QMessageBox, QScrollArea, QSizePolicy, QTabWidget,
    QDialog, QApplication, QRadioButton, QGraphicsOpacityEffect, QTextEdit,
)

from ui import theme

# ============================================================
# 配置读写
# ============================================================
CONFIG_FILE = "launcher_config.json"
DEFAULT_CONFIG = {
    "player_name": "KMCL Player",
    "game_version": "1.20.1",
    "java_path": "",
    "mc_root": "",
    "current_page": "home",
    "background_image": "",
    "blur_radius": 30,
    "wallpaper": "01_nature",   # 壁纸：01_nature/02_hell/03_battle/04_craft
    "font_style": "default",    # 字体风格：default（随包字体）/ pixel（Minecraft 像素风）
    "grass_engine": {           # 草方块引擎
        "enabled": False,       # 启用草方块引擎
        "auto_optimize": False, # 自动优化（启动前清理内存 + 应用优化参数）
        "preset": "balanced",   # 画质预设：performance/balanced/quality/low_end
        "taa": False,           # TAA 抗锯齿减少闪烁
        "blur": False,          # 动态模糊（需对应光影/模组支持）
    },
    "version_isolation": True,
    "launcher_visibility": "visible",
}


def load_config(base_dir):
    cfg = dict(DEFAULT_CONFIG)
    p = os.path.join(base_dir, CONFIG_FILE)
    try:
        with open(p, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    cfg["version_isolation"] = True  # 强制版本隔离（KMCL 社区维护版不支持共享目录）
    return cfg


def save_config(base_dir, cfg):
    p = os.path.join(base_dir, CONFIG_FILE)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def default_mc_root():
    return os.path.expanduser("~/.minecraft")


def app_data_root():
    """打包版所有可写数据（配置/缓存/日志）统一放系统应用数据目录，
    用户默认看不到，避免在 exe 旁边（如桌面）生成任何文件。"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "KMCL")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def resolve_data_dir(base_dir):
    """打包版（onefile/onedir）数据目录=系统应用数据目录（持久且不可见）；
    开发模式沿用 base_dir。"""
    if getattr(sys, "frozen", False):
        return app_data_root()
    return base_dir


def resolve_cache_dir(base_dir):
    """图标缓存位置：打包版（frozen）放数据目录（exe 同级 / _internal），
    开发模式放系统临时目录，避免把缓存生成进源代码目录。"""
    if getattr(sys, "frozen", False):
        return os.path.join(resolve_data_dir(base_dir), ".icon_cache")
    import tempfile
    return os.path.join(tempfile.gettempdir(), "kmcl_icon_cache")


def scan_versions(mc_root):
    """扫描 versions 目录，返回可显示的版本 id 列表（按目录名倒序）。

    参考 HMCL：被加载器版本继承的纯原版核心合并隐藏，避免"装一个 Fabric/Forge
    后列表里多出一个原版"。两条隐藏规则：
      1) inheritsFrom 继承（Fabric/新版 Forge/NeoForge 的老格式 json）；
      2) 老 Forge（1.6.4 及更早）版本 json 自足、无 inheritsFrom，靠命名前缀
         "<mc>-Forge…/forge…/fabric…/neoforge…" 识别并隐藏对应纯原版 "<mc>"。
    未被任何版本继承/引用的原版仍正常显示。
    """
    vdir = os.path.join(mc_root, "versions")
    if not os.path.isdir(vdir):
        return []
    ids = []
    for name in os.listdir(vdir):
        d = os.path.join(vdir, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, name + ".json")):
            ids.append(name)
    parents = set()
    for name in ids:
        try:
            with open(os.path.join(vdir, name, name + ".json"), encoding="utf-8") as f:
                p = json.load(f).get("inheritsFrom")
            if p:
                parents.add(p)
        except Exception:
            pass
    out = [v for v in ids if v not in parents]
    # 老 Forge 自足 json：加载器版本名 "<mc>-Forge…" 存在时隐藏纯原版 "<mc>"
    loader_bases = set()
    for name in ids:
        m = re.match(r"^(.+?)-(?:Forge|forge|fabric|neoforge|fabric-loader|optifine|fabric|ModLoader|modloader|LiteLoader|liteloader|Cleanroom|cleanroom|Rift|rift)", name)
        if m and m.group(1) in ids:
            loader_bases.add(m.group(1))
    out = [v for v in out if v not in loader_bases]
    out.sort(reverse=True)
    return out


# ============================================================
# 启动线程
# ============================================================
class LaunchThread(QThread):
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, cmd, cwd):
        super().__init__()
        self.cmd = cmd
        self.cwd = cwd
        self._proc = None
        self._proc_lock = threading.Lock()

    def run(self):
        try:
            proc = subprocess.Popen(
                self.cmd, cwd=self.cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            with self._proc_lock:
                self._proc = proc
            self.finished_ok.emit(proc.pid)
            for line in iter(proc.stdout.readline, b""):
                try:
                    self.log.emit(line.decode("utf-8", errors="replace").rstrip())
                except Exception:
                    pass
            proc.wait()
        except Exception as e:
            self.failed.emit(str(e))

    def stop(self):
        with self._proc_lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass


# ============================================================
# 修复线程
# ============================================================
class RepairThread(QThread):
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(str)

    def __init__(self, tasks, base_dir, natives_target=None):
        super().__init__()
        self.tasks = tasks
        self.base_dir = base_dir
        # natives_target：落在 .../natives/ 下的 jar 下载后同步解压到此目录
        self.natives_target = natives_target

    def run(self):
        from repair_game import dl_task, extract_natives
        from concurrent.futures import ThreadPoolExecutor, as_completed
        total = len(self.tasks)
        ok = 0
        extracted = 0
        if not self.tasks:
            self.done.emit("完成 0 / 0 个文件")
            return
        lock = __import__("threading").Lock()
        done_n = [0]
        ok_n = [0]

        def _do(task):
            try:
                r = dl_task(task)
                good, path, msg = (r if r else (False, task[1], "无结果"))
                with lock:
                    done_n[0] += 1
                    n = done_n[0]
                    if good:
                        ok_n[0] += 1
                if good:
                    self.progress.emit(n, total, "OK %s" % os.path.basename(str(path)))
                else:
                    self.progress.emit(n, total, "失败 %s: %s" % (
                        os.path.basename(str(path)), msg[:60]))
                if self.natives_target and str(path).endswith(".jar") and os.path.basename(
                        os.path.dirname(str(path))) == "natives":
                    try:
                        os.makedirs(self.natives_target, exist_ok=True)
                        extract_natives(str(path), self.natives_target)
                    except Exception:
                        pass
            except Exception as e:
                with lock:
                    done_n[0] += 1
                self.progress.emit(done_n[0], total, "失败: %s" % e)

        with ThreadPoolExecutor(max_workers=64) as ex:
            futs = [ex.submit(_do, t) for t in self.tasks]
            for _ in as_completed(futs):
                pass
        tail = ("，原生库已解压 %d 个" % extracted) if self.natives_target else ""
        self.done.emit("完成 %d / %d 个文件%s" % (ok_n[0], total, tail))


# ============================================================
# 百宝箱工具
# ============================================================
def auto_heap_mb():
    """自动内存优化：按物理内存取 1/4（1G~8G 区间）。"""
    try:
        import ctypes
        class _M(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = _M(); st.dwLength = ctypes.sizeof(st)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        total_mb = st.ullTotalPhys // (1024 * 1024)
        return int(max(1024, min(total_mb // 4, 8192)))
    except Exception:
        return 4096


def detect_ssd():
    """检测系统是否存在固态硬盘。True=有SSD, False=纯机械, None=未知。"""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-PhysicalDisk | Where-Object {$_.MediaType -in 'SSD','Unspecified'} | Measure-Object).Count"],
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        n = int(out.decode().strip() or 0)
        return n > 0
    except Exception:
        return None


def perf_jvm_args(mem_mb):
    """性能优化 JVM 参数模板（配合推荐堆内存）。"""
    return [
        "-Xmx%dm" % mem_mb,
        "-Xms%dm" % min(mem_mb, 1024),
        "-XX:+UseG1GC",
        "-XX:MaxGCPauseMillis=50",
        "-XX:+ParallelRefProcEnabled",
        "-Dfile.encoding=UTF-8",
    ]


class BtnState:
    """按钮记忆缓存：记录按钮是否被开启/使用过，重启后仍显示「已开启」。

    配置结构：button_states = { 键名: {"on": bool, "t": 时间戳} }
    """
    KEY = "button_states"

    @staticmethod
    def is_on(cfg, key):
        return bool((cfg.get(BtnState.KEY) or {}).get(key, {}).get("on", False))

    @staticmethod
    def mark(cfg, key, on=True, save=None):
        st = cfg.setdefault(BtnState.KEY, {})
        st[key] = {"on": bool(on), "t": time.time()}
        if save:
            save()

    @staticmethod
    def clear(cfg, key=None, save=None):
        st = cfg.get(BtnState.KEY)
        if not isinstance(st, dict):
            return
        if key is None:
            cfg.pop(BtnState.KEY, None)
        else:
            st.pop(key, None)
        if save:
            save()


def clean_mc_junk(mc_root):
    """清理游戏垃圾与缓存：logs / crash-reports / *.tmp / *.part / *.log / lastoutput。
    返回 (删除文件数, 释放字节数)。"""
    removed = 0
    freed = 0
    for d in ("logs", "crash-reports"):
        p = os.path.join(mc_root, d)
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for fn in files:
                    fp = os.path.join(root, fn)
                    try:
                        freed += os.path.getsize(fp)
                        os.remove(fp)
                        removed += 1
                    except OSError:
                        pass
    if os.path.isdir(mc_root):
        for fn in os.listdir(mc_root):
            if fn.endswith((".tmp", ".part", ".log")) or fn == "lastoutput.txt":
                fp = os.path.join(mc_root, fn)
                try:
                    freed += os.path.getsize(fp)
                    os.remove(fp)
                    removed += 1
                except OSError:
                    pass
    return removed, freed


# ---- 百宝箱实用工具：快捷打开 / 世界备份 / 模组管理 / 版本校验 / 残留进程 ----
def quick_dirs(mc_root):
    """常用子目录清单（存在性由调用方检查）。"""
    return {
        "模组": os.path.join(mc_root, "mods"),
        "世界存档": os.path.join(mc_root, "saves"),
        "资源包": os.path.join(mc_root, "resourcepacks"),
        "光影": os.path.join(mc_root, "shaderpacks"),
        "截图": os.path.join(mc_root, "screenshots"),
        "日志": os.path.join(mc_root, "logs"),
    }


def backup_worlds_zip(mc_root, dest_dir=None):
    """把 saves（全部世界存档）打包成 zip 到 dest_dir（默认 <mc>/backups）。
    返回 zip 路径；saves 不存在时返回 None。"""
    saves = os.path.join(mc_root, "saves")
    if not os.path.isdir(saves):
        return None
    dest_dir = dest_dir or os.path.join(mc_root, "backups")
    os.makedirs(dest_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(dest_dir, "世界备份_%s.zip" % stamp)
    import zipfile
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(saves):
            for fn in files:
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, saves)
                zf.write(fp, os.path.join("saves", rel))
    return dest


def restore_world_zip(zip_path, mc_root):
    """把备份 zip 解压回 saves（同名世界将被覆盖）。返回解压文件数。"""
    import zipfile
    saves = os.path.join(mc_root, "saves")
    os.makedirs(saves, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for m in zf.infolist():
            if m.filename.endswith("/"):
                continue
            target = os.path.normpath(os.path.join(saves, m.filename))
            # 防 zip 路径穿越
            if not target.startswith(saves + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(m) as src, open(target, "wb") as dst:
                dst.write(src.read())
            n += 1
    return n


def list_world_backups(mc_root):
    """返回 backups 目录下的世界备份 zip 列表（按时间倒序）。"""
    bdir = os.path.join(mc_root, "backups")
    if not os.path.isdir(bdir):
        return []
    zips = [f for f in os.listdir(bdir) if f.endswith(".zip")]
    zips.sort(key=lambda f: os.path.getmtime(os.path.join(bdir, f)), reverse=True)
    return zips


def mods_status(mc_root, version_id=None):
    """返回某版本 mods 目录（强制版本隔离）的 (已启用数, 已禁用数)。"""
    mods = os.path.join(mc_root, "versions", version_id, "mods") if version_id else os.path.join(mc_root, "mods")
    if not os.path.isdir(mods):
        return 0, 0
    en = dis = 0
    for fn in os.listdir(mods):
        if fn.endswith(".jar"):
            en += 1
        elif fn.endswith(".jar.disabled"):
            dis += 1
    return en, dis


def set_all_mods(mc_root, enable, version_id=None):
    """一键全部启用/禁用某版本 mods（.jar <-> .jar.disabled）。返回处理数量。"""
    mods = os.path.join(mc_root, "versions", version_id, "mods") if version_id else os.path.join(mc_root, "mods")
    if not os.path.isdir(mods):
        return 0
    n = 0
    for fn in os.listdir(mods):
        src = os.path.join(mods, fn)
        if enable and fn.endswith(".jar.disabled"):
            os.rename(src, src[:-len(".disabled")])
            n += 1
        elif not enable and fn.endswith(".jar") and not fn.endswith(".disabled"):
            os.rename(src, src + ".disabled")
            n += 1
    return n


# ============================================================
# Alpha 3.0 · 交互动画（果冻按钮回弹 / 窗口渐显）
# ============================================================
# ============================================================
# 搜索索引（侧边栏搜索框：匹配页面与功能关键词）
# ============================================================
SEARCH_INDEX = [
    ("home", "首页", "一键启动 / 功能入口 / 启动日志 / 快捷启动"),
    ("account", "账号中心", "微软登录 / 离线账号 / 皮肤 / 正版 / 登出"),
    ("games", "游戏库", "版本选定 / 模组 / 光影 / 数据包 / 资源包 / 地图 / 整合包 / 下载游戏 / 加载器"),
    ("multiplayer", "联机大厅", "创建房间 / 联机码加入 / 局域网开房"),
    ("toolbox", "百宝箱", "内存优化 / 清理缓存 / Java状态 / 自定义下载 / 诊断信息 / JVM模板 / 快捷文件夹 / 世界备份 / 版本校验 / 游玩统计 / 模组管理 / 残留进程 / 性能监控 / 空间扫描 / 内存急救 / 启动优化 / GC日志 / 视频建议 / 删除资料 / 网络测速 / 剪贴板 / 系统信息 / 电源计划 / 运行时长 / 崩溃报告 / DNS / 临时文件 / 截图 / Java自测"),
    ("settings", "设置", "玩家名 / 默认版本 / Java / 游戏目录 / 版本隔离 / 壁纸 / 全局游戏设置 / 清理图标缓存 / JVM参数 / 游戏参数 / 游戏修复 / 默认内存 / 界面语言 / 下载线程 / 窗口大小 / 游戏语言 / 开机自启 / 清空日志 / 备份配置 / 恢复配置 / 重置 / 草方块引擎 / 画质预设 / 性能优先 / 均衡 / 画质优先 / 低端设备 / TAA / 抗锯齿 / 动态模糊 / 自动优化 / 高级选项"),
    ("about", "关于", "版本信息 / 开源声明 / 完整版声明 / 文档"),
]


class JellyFilter(QObject):
    """全局按钮果冻反馈：按下微微下压，释放时从下方回弹（OutBack 过冲）。

    用法：app.installEventFilter(JellyFilter())，所有 QPushButton 自动生效。

    实现说明：
    - 动画不缓存、不挂到按钮上（旧实现缓存动画并以按钮为 parent，
      页面切换/刷新重建按钮后 id() 复用会拿到悬垂动画，导致点击效果静默丢失）。
    - 每次点击创建一次性动画（parent 为过滤器自身），结束即销毁，无悬垂风险。
    - 防抖：同一按钮的回弹动画未结束时再次点击，不再排队新动画（只保留按压
      位移），避免连点/重复触发造成动画堆积、渲染队列变长导致的卡顿感。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = set()      # 正在回弹中的按钮 id（防抖）
        self._orig_pos = {}       # id(obj) -> 按下前位置（回弹终点，防按钮累计下移）

    def eventFilter(self, obj, ev):
        if isinstance(obj, QPushButton) and ev.type() in (QEvent.MouseButtonPress,
                                                          QEvent.MouseButtonRelease):
            try:
                oid = id(obj)
                if ev.type() == QEvent.MouseButtonPress:
                    # 记录按下前位置（回弹必须回到这里，否则每次点击按钮下移 1px）
                    self._orig_pos[oid] = QPoint(obj.x(), obj.y())
                    obj.move(obj.x(), obj.y() + 1)   # 按下：位置微压（配合 QSS :pressed）
                else:
                    if oid in self._active:
                        return super().eventFilter(obj, ev)  # 防抖：动画未结束，忽略本次
                    base = self._orig_pos.pop(oid, QPoint(obj.x(), obj.y() - 1))
                    self._active.add(oid)
                    # 延迟到事件处理栈外启动动画（QTimer.singleShot(0)）：
                    # 事件过滤器内直接 start() 在部分平台/离屏环境下会被事件派发
                    # 时序干扰而中途停止，延迟一帧启动则稳定可靠；动画一次性，
                    # parent 为按钮自身，结束 deleteLater，无悬垂。
                    QTimer.singleShot(0, lambda o=obj, b=base, i=oid: self._bounce(o, b, i))
            except Exception:
                pass
        return super().eventFilter(obj, ev)

    def _bounce(self, obj, base, oid):
        """回弹动画本体（延迟一帧执行，避免事件过滤栈内启动被时序干扰）。"""
        try:
            anim = QPropertyAnimation(obj, b"pos", obj)
            anim.setDuration(340)
            anim.setEasingCurve(QEasingCurve.OutBack)
            anim.setStartValue(QPoint(base.x(), base.y() + 3))
            anim.setEndValue(base)

            def _done(oid=oid):
                self._active.discard(oid)

            anim.finished.connect(_done)
            anim.finished.connect(anim.deleteLater)
            anim.start()
        except Exception:
            self._active.discard(oid)


def fade_in_window(win, duration=520):
    """窗口渐显动画（首次显示时从透明淡入）。"""
    eff = QGraphicsOpacityEffect(win)
    win.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", win)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.start(QPropertyAnimation.DeleteWhenStopped)
    return anim


# ============================================================
# Alpha 3.0 · 账号 / 皮肤工具
# ============================================================
def current_account(cfg):
    """返回当前账号 dict（accounts 列表 + current_account 索引），无则 None。"""
    accs = cfg.get("accounts") or []
    if not accs:
        return None
    i = cfg.get("current_account", 0)
    try:
        i = int(i)
    except Exception:
        i = 0
    if not (0 <= i < len(accs)):
        i = 0
    return accs[i]


def set_account_skin(cfg, skin):
    """记录皮肤偏好（random/steve/alex/custom）。"""
    cfg["skin"] = skin


def fetch_skin_file(url, dest):
    """下载皮肤文件到 dest；失败返回 False。"""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KMCL/3.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read()
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def make_random_skin(dest):
    """生成一张随机像素风 64x64 皮肤 PNG。"""
    from PyQt5.QtGui import QImage, QColor
    import random as _r
    img = QImage(64, 64, QImage.Format_RGB32)
    body = QColor(210, 170, 130)
    for y in range(64):
        for x in range(64):
            base = (y < 32 and x < 16) or (y >= 32 and x < 8)
            if base:
                c = QColor(_r.randint(40, 240), _r.randint(30, 230), _r.randint(30, 230))
            elif y < 20 or y >= 52:
                c = body.lighter(100 + _r.randint(-15, 25))
            else:
                c = QColor(_r.randint(20, 90), _r.randint(40, 130), _r.randint(60, 160))
            img.setPixelColor(x, y, c)
    img.save(dest, "PNG")
    return dest


def ensure_skin_file(base_dir, cfg, mc_root):
    """按皮肤偏好生成/下载皮肤文件，返回皮肤绝对路径或 None。
    steve/alex 从皮肤站下载（失败时随机生成兜底），random 本地随机生成，
    custom 用已导入文件。"""
    skin = cfg.get("skin", "steve")
    skins_dir = os.path.join(mc_root, "skins")
    os.makedirs(skins_dir, exist_ok=True)
    if skin in ("steve", "alex"):
        dest = os.path.join(skins_dir, "%s.png" % skin)
        url = "https://crafatar.com/skins/%s" % skin
        if not fetch_skin_file(url, dest):
            # 换官方源再试一次；仍失败则本地随机生成兜底，保证有皮肤可用
            url2 = "http://assets.mojang.com/Skins/%s.png" % skin
            if not fetch_skin_file(url2, dest):
                make_random_skin(dest)
        return dest if os.path.exists(dest) else None
    if skin == "random":
        dest = os.path.join(skins_dir, "random.png")
        make_random_skin(dest)
        return dest
    if skin == "custom":
        # 自定义：用户在账号中心导入的文件
        for fn in ("custom.png", "custom_skin.png"):
            p = os.path.join(skins_dir, fn)
            if os.path.exists(p):
                return p
        return None
    # 默认 steve
    return ensure_skin_file(base_dir, {"skin": "steve"}, mc_root)


# ============================================================
# Alpha 3.0 · 本地模组扫描 / 解析
# ============================================================
def parse_mod_meta(jar_path):
    """从 mod jar 内解析元数据，返回 {name, version, mc, deps, source}。
    支持 fabric.mod.json / META-INF/mods.toml(Forge/NeoForge) / mcmod.info(老Forge)。"""
    import zipfile
    meta = {"name": None, "version": None, "mc": [], "deps": [], "source": "未知"}
    try:
        with zipfile.ZipFile(jar_path, "r") as z:
            names = z.namelist()
            if "fabric.mod.json" in names:
                data = json.loads(z.read("fabric.mod.json").decode("utf-8", "ignore"))
                meta["name"] = data.get("name") or data.get("id") or os.path.basename(jar_path)
                meta["version"] = data.get("version", "")
                meta["source"] = "Fabric"
                meta["mc"] = [data.get("depends", {}).get("minecraft", "")] if isinstance(data.get("depends"), dict) else []
                if isinstance(data.get("depends"), dict):
                    meta["deps"] = [{"id": k, "version": v} for k, v in data["depends"].items() if k != "minecraft"]
            elif "META-INF/mods.toml" in names:
                txt = z.read("META-INF/mods.toml").decode("utf-8", "ignore")
                import re as _re
                m = _re.search(r'modId\s*=\s*"([^"]+)"', txt)
                m2 = _re.search(r'version\s*=\s*"([^"]+)"', txt)
                meta["name"] = m.group(1) if m else os.path.basename(jar_path)
                meta["version"] = m2.group(1) if m2 else ""
                meta["source"] = "Forge/NeoForge"
                for dep in _re.finditer(r'\[\[dependencies\.(\w+)\]\]', txt):
                    meta["mc"].append(dep.group(1))
            elif "mcmod.info" in names:
                try:
                    arr = json.loads(z.read("mcmod.info").decode("utf-8", "ignore"))
                    if arr:
                        meta["name"] = arr[0].get("name") or os.path.basename(jar_path)
                        meta["version"] = arr[0].get("version", "")
                        meta["mc"] = arr[0].get("mcversion", [])
                        meta["source"] = "Forge"
                except Exception:
                    pass
    except Exception:
        pass
    return meta


def scan_local_mods(mc_root, version_id=None):
    """扫描 mods 目录（强制版本隔离：只扫指定版本的隔离目录，不混入共享 mods）。

    返回 [{file, enabled, meta}]。"""
    dirs = [os.path.join(mc_root, "versions", version_id, "mods")] if version_id else []
    rows = []
    seen = set()
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            full = os.path.join(d, fn)
            key = fn.lower()
            if key in seen:
                continue
            seen.add(key)
            if not (fn.endswith(".jar") or fn.endswith(".jar.disabled")):
                continue
            enabled = not fn.endswith(".disabled")
            meta = parse_mod_meta(full) if enabled else {}
            rows.append({"file": full, "name": fn, "enabled": enabled, "meta": meta})
    return rows


def mod_issues(rows):
    """模组体检：返回 (缺失依赖, 冲突列表)。"""
    installed = {}
    for r in rows:
        if not r["enabled"]:
            continue
        nm = (r["meta"].get("name") or r["name"]).lower()
        installed.setdefault(nm, []).append(r)
    missing = []
    # 加载器/框架类依赖不算缺失（fabricloader/forge/neoforge 是加载器本身）
    framework_deps = {"fabricloader", "forge", "neoforge", "minecraft"}
    for r in rows:
        if not r["enabled"]:
            continue
        for dep in (r["meta"].get("deps") or []):
            key = dep.get("id", "").lower()
            if key in framework_deps:
                continue
            if key and not any(key in k for k in installed):
                missing.append((r["name"], dep.get("id")))
    conflicts = []
    for k, v in installed.items():
        if len(v) > 1 and k != v[0]["file"].lower():
            conflicts.append((k, [x["file"] for x in v]))
    return missing, conflicts


def check_versions_integrity(mc_root):
    """校验已安装版本的核心文件（<id>/<id>.jar 与 <id>/<id>.json）。
    返回 [(版本, 是否正常, 问题描述)]。"""
    vdir = os.path.join(mc_root, "versions")
    if not os.path.isdir(vdir):
        return []
    out = []
    for vid in sorted(os.listdir(vdir)):
        sub = os.path.join(vdir, vid)
        if not os.path.isdir(sub):
            continue
        problems = []
        if not os.path.isfile(os.path.join(sub, vid + ".json")):
            problems.append("缺少版本清单 %s.json" % vid)
        if not os.path.isfile(os.path.join(sub, vid + ".jar")):
            problems.append("缺少核心 %s.jar" % vid)
        # 加载器版本（fabric/forge 等）不带同名 jar，核心以 json 内 mainClass 判定
        if not problems:
            try:
                with open(os.path.join(sub, vid + ".json"), "r", encoding="utf-8") as f:
                    data = json.load(f)
                main_cls = (data.get("mainClass") or "").strip()
                if main_cls and main_cls.startswith("net.minecraft"):
                    if not os.path.isfile(os.path.join(sub, vid + ".jar")):
                        problems.append("缺少核心 %s.jar" % vid)
            except Exception:
                problems.append("版本清单无法解析")
        out.append((vid, not problems, "；".join(problems) if problems else "正常"))
    return out


def kill_stray_java():
    """结束系统中残留的 java/javaw 进程（不含当前启动器，它由 python 运行）。
    返回被杀进程数；异常时抛出。"""
    out = subprocess.check_output(
        ["tasklist", "/FI", "IMAGENAME eq javaw.exe", "/FO", "CSV", "/NH"],
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    lines = [ln for ln in out.decode("gbk", "ignore").splitlines() if ln.strip()]
    if lines:
        subprocess.run(["taskkill", "/F", "/IM", "javaw.exe"],
                       creationflags=subprocess.CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return len(lines)


# ---- 老电脑优化工具 ----
def get_mem_status():
    """返回 (总内存MB, 可用内存MB, 使用率%)。"""
    import ctypes
    class _M(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = _M()
    st.dwLength = ctypes.sizeof(st)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return st.ullTotalPhys // 1048576, st.ullAvailPhys // 1048576, int(st.dwMemoryLoad)


def get_cpu_times():
    """返回 (idle, kernel, user) 累计时间，供两次采样计算 CPU 使用率。"""
    import ctypes
    class _FT(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]
    idle, kernel, user = _FT(), _FT(), _FT()
    ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))

    def to64(ft):
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return to64(idle), to64(kernel), to64(user)


def disk_usage_mb(path):
    """返回 (已用MB, 总MB)。"""
    u = shutil.disk_usage(path)
    return u.used // 1048576, u.total // 1048576


def clear_system_memory():
    """通过 EmptyWorkingSet 清理所有进程工作集（老电脑内存急救）。
    跳过当前进程；返回处理进程数。"""
    import ctypes
    from ctypes import wintypes
    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_SET_QUOTA = 0x0100
    procs = (wintypes.DWORD * 2048)()
    cb = wintypes.DWORD(ctypes.sizeof(procs))
    needed = wintypes.DWORD(0)
    psapi.EnumProcesses(ctypes.byref(procs), cb, ctypes.byref(needed))
    n = needed.value // ctypes.sizeof(wintypes.DWORD)
    me = os.getpid()
    done = 0
    for i in range(min(n, 2048)):
        pid = procs[i]
        if pid == me:
            continue
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
        if h:
            try:
                if psapi.EmptyWorkingSet(h):
                    done += 1
            except Exception:
                pass
            finally:
                kernel32.CloseHandle(h)
    return done


# ============================================================
# 草方块引擎：画质预设 / TAA 写入游戏 options.txt
# ============================================================
# 画质预设（语义值；写入时按版本转成对应键名与取值）
GRASS_PRESETS = {
    "performance": {"renderDistance": 6, "particles": 0, "ao": 0, "clouds": 0,
                    "graphics": 1, "mipmap": 0, "gamma": 0.5},
    "balanced": {"renderDistance": 10, "particles": 1, "ao": 1, "clouds": 1,
                 "graphics": 2, "mipmap": 2, "gamma": 0.75},
    "quality": {"renderDistance": 18, "particles": 2, "ao": 2, "clouds": 2,
                "graphics": 2, "mipmap": 4, "gamma": 1.0},
    "low_end": {"renderDistance": 4, "particles": 0, "ao": 0, "clouds": 0,
                "graphics": 1, "mipmap": 0, "gamma": 0.5},
}
GRASS_PRESET_NAMES = {
    "performance": "性能优先",
    "balanced": "均衡",
    "quality": "画质优先",
    "low_end": "低端设备专属",
}


def _mc_ge_113(version_id):
    """判断版本号是否 >= 1.13（options.txt 键名分水岭）。

    版本 id 可能是 fabric-loader-0.15.11-1.20.1 / 1.21.1-neoforge-21.1.x 等，
    取所有 x.y 里主版本为 1 的最小那组（MC 主版本永远是 1.x）。
    """
    import re as _re
    best = None
    for m in _re.finditer(r"(\d+)\.(\d+)", version_id or ""):
        p = (int(m.group(1)), int(m.group(2)))
        if p[0] == 1 and (best is None or p < best):
            best = p
    if best is None:
        return None
    return best >= (1, 13)


def apply_grass_engine_options(game_dir, version_id, ge):
    """把草方块引擎的画质预设 + TAA 写进游戏 options.txt。

    - 1.13+ 用 graphics / mipmap_levels / clouds(0~2)；
      老版本（<1.13）用 fancyGraphics / mipmapLevels / clouds(true|false)
    - TAA（减少闪烁）开启时强制 mipmap=4 并开启垂直同步
    - 动态模糊原版无对应键位，只由启动参数注入，不在此处理
    返回 True 表示已写入/更新。
    """
    preset = ge.get("preset", "balanced")
    taa = bool(ge.get("taa"))
    vals = dict(GRASS_PRESETS.get(preset, GRASS_PRESETS["balanced"]))
    if taa:
        vals["mipmap"] = 4
        vals["vsync"] = True
    new_keys = _mc_ge_113(version_id)
    opt = os.path.join(game_dir, "options.txt")
    lines = []
    if os.path.isfile(opt):
        try:
            with open(opt, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
    have = set()
    for k, v in vals.items():
        if k == "graphics":
            key = "graphics" if new_keys else "fancyGraphics"
            val = str(v) if new_keys else ("true" if v == 2 else "false")
        elif k == "clouds":
            key = "clouds"
            val = str(v) if new_keys else ("true" if v else "false")
        elif k == "mipmap":
            key = "mipmap_levels" if new_keys else "mipmapLevels"
            val = str(v)
        elif k == "vsync":
            key, val = "vsync", ("true" if v else "false")
        else:
            key, val = k, str(v)
        if key in have:
            continue
        hit = -1
        for i, l in enumerate(lines):
            if l.startswith(key + ":"):
                hit = i
                break
        if hit >= 0:
            lines[hit] = key + ":" + val
        else:
            lines.append(key + ":" + val)
        have.add(key)
    try:
        with open(opt, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except OSError:
        return False


def top_memory_procs(topn=8):
    """返回按内存占用排序的前 N 个进程 [(PID, 名称, 内存MB)]。"""
    out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"],
                                  creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
    rows = []
    for ln in out.decode("gbk", "ignore").splitlines():
        parts = ln.strip().strip('"').split('","')
        if len(parts) >= 5:
            try:
                mem_kb = int(parts[4].replace(",", "").replace(" K", "").strip())
                rows.append((parts[1], parts[0], mem_kb // 1024))
            except Exception:
                pass
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:topn]


def video_settings_advice():
    """按内存给出游戏内视频设置建议（渲染距离/粒子/云/画质）。"""
    total, _, _ = get_mem_status()
    if total <= 4096:
        return ("渲染距离 6~8，粒子：减少，云：关闭，画质：流畅，平滑光照：关闭，"
                "建议同时启用低配模式并关闭光影"),
    if total <= 8192:
        return ("渲染距离 8~12，粒子：少量，云：关闭，画质：流畅/均衡，"
                "平滑光照：最小"),
    return ("渲染距离 12~16，粒子：全部，云：开启，画质：均衡/高品质，"
            "可配合高配模式使用")


def version_icon_path(base_dir, vid):
    """按版本名判断类型并返回图标路径（借鉴增强版 blockicons 设计：方块图标）。
    release 正式版 / snapshot 快照 / old_alpha 远古 α / old_beta 远古 β。"""
    low = (vid or "").lower()
    icons = os.path.join(base_dir, "assets", "icons")
    if low.startswith(("rd-", "inf")) or re.match(r"^a\d", low):
        return os.path.join(icons, "old_alpha.png")
    if re.match(r"^b\d", low):
        return os.path.join(icons, "old_beta.png")
    if "snapshot" in low or re.search(r"\d{2}w\d{2}", low) \
            or re.match(r"^\d+\.\d+\.\d+-w", low) or re.match(r"^\d+\.\d+\.\d+-pre", low):
        return os.path.join(icons, "snapshot.png")
    return os.path.join(icons, "release.png")


def version_icon(base_dir, vid):
    """返回版本 QIcon；图标缺失时返回空 QIcon。"""
    p = version_icon_path(base_dir, vid)
    if os.path.exists(p):
        return QIcon(p)
    return QIcon()


def festival_banner():
    """按当前日期返回节日横幅 (标题, 副标题)；无节日返回 None。"""
    md = time.strftime("%m-%d")
    table = {
        "01-01": ("🎆 元旦快乐", "新年的第一天，开一局 MC 庆祝一下吧"),
        "04-01": ("🤡 愚人节快乐", "今天 MC 里的一切可能都在骗你"),
        "05-01": ("🎊 劳动节快乐", "辛苦了一整年，放个假好好玩 MC"),
        "06-01": ("🧒 儿童节快乐", "永远保持童心，方块世界欢迎你"),
        "10-01": ("🎉 国庆节快乐", "七天长假，正是肝整合包的好时候"),
        "12-25": ("🎄 圣诞节快乐", "冬日的方块世界也有节日气氛"),
    }
    return table.get(md)


def collect_diag(app):
    """收集诊断信息文本。"""
    import platform
    lines = ["KMCL 社区维护版 · 诊断信息", "=" * 44]
    lines.append("时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("系统: %s %s" % (platform.system(), platform.release()))
    lines.append("程序目录: %s" % app.base_dir)
    lines.append("游戏目录: %s" % app.mc_root())
    lines.append("玩家名: %s" % app.config.get("player_name", ""))
    lines.append("界面风格: 深色透明玻璃（唯一默认）")
    javas = app.detect_javas()
    if javas:
        lines.append("")
        lines.append("可用 Java（系统/按需下载）:")
        for k in sorted(javas):
            lines.append("  Java %s -> %s" % (k, javas[k]))
    vs = scan_versions(app.mc_root())
    lines.append("")
    lines.append("已安装版本 (%d):" % len(vs))
    for v in vs:
        lines.append("  " + v)
    return "\n".join(lines)


class ToolboxDownloadThread(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, dest):
        super().__init__()
        self.url = url
        self.dest = dest

    def run(self):
        import urllib.request
        try:
            os.makedirs(os.path.dirname(self.dest) or ".", exist_ok=True)
            tmp = self.dest + ".part"
            req = urllib.request.Request(self.url, headers={"User-Agent": "KMCL-Community/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        c = r.read(65536)
                        if not c:
                            break
                        f.write(c)
                        done += len(c)
                        self.progress.emit(done, total)
            os.replace(tmp, self.dest)
            self.done.emit(self.dest)
        except Exception as e:
            self.failed.emit(str(e))


class BackupWorldsThread(QThread):
    """世界存档一键备份（打包 zip）。"""
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, mc_root):
        super().__init__()
        self.mc_root = mc_root

    def run(self):
        try:
            dest = backup_worlds_zip(self.mc_root)
            if not dest:
                self.failed.emit("未找到 saves（世界存档）目录")
            else:
                self.done.emit(dest)
        except Exception as e:
            self.failed.emit(str(e))


class RestoreWorldThread(QThread):
    """从备份 zip 恢复世界存档。"""
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, zip_path, mc_root):
        super().__init__()
        self.zip_path = zip_path
        self.mc_root = mc_root

    def run(self):
        try:
            n = restore_world_zip(self.zip_path, self.mc_root)
            self.done.emit("已恢复 %d 个文件（同名世界已覆盖）" % n)
        except Exception as e:
            self.failed.emit(str(e))


class ScanSpaceThread(QThread):
    """扫描游戏目录各子目录体积，返回占用最大的若干项。"""
    done = pyqtSignal(list)

    def __init__(self, mc_root):
        super().__init__()
        self.mc_root = mc_root

    def run(self):
        rows = []
        try:
            for name in os.listdir(self.mc_root):
                p = os.path.join(self.mc_root, name)
                if os.path.isdir(p):
                    total = 0
                    for root, _, files in os.walk(p):
                        for fn in files:
                            try:
                                total += os.path.getsize(os.path.join(root, fn))
                            except OSError:
                                pass
                    rows.append((name, total))
        except Exception:
            pass
        rows.sort(key=lambda r: r[2], reverse=True)
        self.done.emit(rows[:8])


class VanillaRepairThread(QThread):
    """自动补齐缺失的原版核心（json + jar + 依赖 + 资源）。"""
    stage = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, vid, mc_root):
        super().__init__()
        self.vid = vid
        self.mc_root = mc_root

    def run(self):
        try:
            from game_download import download_vanilla
            download_vanilla(self.vid, self.mc_root,
                             progress=lambda i, t: self.stage.emit("下载原版核心 %d / %d" % (i, t)),
                             status=self.stage.emit)
            self.done.emit(True, "ok")
        except Exception as e:
            self.done.emit(False, str(e))


class MissingLibsThread(QThread):
    """启动前自动补齐缺失的依赖（库 + 原生库 + 原版 jar + 资源），完成后自动继续启动。"""
    stage = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    done = pyqtSignal(bool, str)

    def __init__(self, vid, mc_root):
        super().__init__()
        self.vid, self.mc_root = vid, mc_root

    def run(self):
        try:
            import repair_game
            from concurrent.futures import ThreadPoolExecutor, as_completed
            tasks, native_jars, base_vdir = repair_game.collect_tasks(self.vid, self.mc_root)
            missing = [t for t in tasks if repair_game.need_download(t[1], t[2], t[3])]
            total = len(missing)
            done_n = 0
            fail_libs = 0  # 库/原生库失败数（assets 失败不阻断启动）

            def _download_task(t):
                # dl_task 统一入口：大文件（>=8MB，通常为原版核心 jar）走 Range
                # 多线程分块（官方源优先、镜像兜底），失败自动回退整包；小文件走 dl_one
                return repair_game.dl_task(t)

            if missing:
                with ThreadPoolExecutor(max_workers=64) as ex:
                    futs = {ex.submit(_download_task, t): t for t in missing}
                    for fut in as_completed(futs):
                        try:
                            ok, dest, msg = fut.result()
                            done_n += 1
                            self.stage.emit("补齐 %d / %d: %s %s" % (
                                done_n, total, os.path.basename(dest),
                                "OK" if ok else "失败(%s)" % msg[:80]))
                            self.progress.emit(done_n, total)
                            if not ok and (os.sep + "libraries" + os.sep in dest
                                           or "natives" in dest):
                                fail_libs += 1
                        except Exception:
                            done_n += 1
                            self.progress.emit(done_n, total)
            ndir = os.path.join(base_vdir, "natives")
            os.makedirs(ndir, exist_ok=True)
            for t in native_jars:
                if not os.path.exists(t[1]):
                    ok, dest, msg = repair_game.dl_one(t)
                    if not ok:
                        fail_libs += 1
                try:
                    repair_game.extract_natives(t[1], ndir)
                except Exception:
                    pass
            if fail_libs:
                self.done.emit(False, "依赖补齐完成，但有 %d 个库文件下载失败。\n"
                                    "游戏缺少这些库无法启动，请检查网络后重试。\n"
                                    "详情见日志。" % fail_libs)
            else:
                self.done.emit(True, "依赖补齐完成，共处理 %d 个文件" % total)
        except Exception as e:
            self.done.emit(False, str(e))


class DeleteAllThread(QThread):
    """删除游戏目录下全部内容（保留目录本身）。"""
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(str)

    def __init__(self, mc_root):
        super().__init__()
        self.mc_root = mc_root

    def run(self):
        try:
            entries = list(os.scandir(self.mc_root)) if os.path.isdir(self.mc_root) else []
            total = len(entries)
            done_n = 0
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        shutil.rmtree(e.path, ignore_errors=True)
                    else:
                        os.remove(e.path)
                    done_n += 1
                    self.progress.emit(done_n, total, e.name)
                except Exception:
                    pass
            self.done.emit("已删除 %d 个项目（游戏资料已清空）" % done_n)
        except Exception as e:
            self.done.emit("删除出错: %s" % e)


# ============================================================
# 通用控件
# ============================================================
def glass_card():
    card = QFrame()
    card.setObjectName("GlassCard")
    return card


def section_title(text):
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    return lbl


def primary_btn(text):
    b = QPushButton(text)
    b.setObjectName("PrimaryBtn")
    b.setCursor(Qt.PointingHandCursor)
    return b


def ghost_btn(text):
    b = QPushButton(text)
    b.setObjectName("GhostBtn")
    b.setCursor(Qt.PointingHandCursor)
    return b


def divider():
    d = QFrame()
    d.setObjectName("Divider")
    return d


class Page(QWidget):
    """页面基类：滚动容器 + 内边距。"""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(28, 24, 28, 28)
        self.body_layout.setSpacing(14)
        self.scroll.setWidget(self.body)
        self.outer.addWidget(self.scroll)

    def refresh(self):
        pass


# ============================================================
# 首页（Dashboard：一键启动 + 全部分支入口）
# ============================================================
class HomePage(Page):
    ENTRIES = [
        ("games", "🎮", "游戏库", "已安装的版本与加载器"),
        ("multiplayer", "🌐", "联机大厅", "局域网开房 / 联机码加入"),
        ("settings", "🛠", "游戏修复", "校验并补全缺失的游戏文件（设置内）"),
        ("settings", "⚙", "设置", "启动器与游戏参数"),
        ("about", "ℹ", "关于", "版本信息与开源声明"),
        ("log", "📜", "启动日志", "查看最近一次启动输出"),
    ]

    def __init__(self, app):
        super().__init__(app)
        self.launcher = None

        # 品牌区
        head = QHBoxLayout()
        self.brand_icon = QLabel()
        icon_path = self.app.icon_path
        if icon_path and os.path.exists(icon_path):
            pm = QPixmap(icon_path).scaled(54, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.brand_icon.setPixmap(pm)
        self.brand_icon.setFixedSize(54, 54)
        brand_box = QVBoxLayout()
        title = QLabel("KMCL 社区维护版")
        title.setObjectName("SideBrand")
        sub = QLabel("简洁轻便 · 专注 Minecraft 启动")
        sub.setObjectName("SideBrandSub")
        brand_box.addWidget(title)
        brand_box.addWidget(sub)
        head.addWidget(self.brand_icon)
        head.addSpacing(10)
        head.addLayout(brand_box)
        head.addStretch(1)
        self.env_label = QLabel("环境检测中…")
        self.env_label.setObjectName("SideBrandSub")
        head.addWidget(self.env_label)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        # 节日横幅（无节日时自动隐藏）
        fb = festival_banner()
        if fb:
            banner = QFrame()
            banner.setObjectName("FestivalBanner")
            banner.setStyleSheet(
                "QFrame#FestivalBanner { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 rgba(190,60,90,0.85), stop:0.5 rgba(120,80,200,0.85), stop:1 rgba(60,130,220,0.85));"
                "border-radius: 14px; }")
            bl = QHBoxLayout(banner)
            bl.setContentsMargins(20, 12, 20, 12)
            bt = QLabel(fb[0])
            bt.setStyleSheet("font-size:15px; font-weight:700; color:#FFFFFF; background:transparent;")
            bs = QLabel(fb[1])
            bs.setStyleSheet("font-size:11.5px; color:rgba(255,255,255,0.85); background:transparent;")
            bl.addWidget(bt)
            bl.addSpacing(12)
            bl.addWidget(bs)
            bl.addStretch(1)
            self.body_layout.addWidget(banner)

        # 一键启动卡
        launch_card = glass_card()
        lc = QVBoxLayout(launch_card)
        lc.setContentsMargins(24, 20, 24, 20)
        lc.setSpacing(12)
        lc.addWidget(section_title("一键启动"))

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        form.addWidget(QLabel("版本"), 0, 0)
        self.cmb_version = QComboBox()
        form.addWidget(self.cmb_version, 0, 1)
        form.addWidget(QLabel("玩家名"), 1, 0)
        self.lbl_name = QLabel()
        self.lbl_name.setObjectName("SideBrandSub")
        form.addWidget(self.lbl_name, 1, 1)
        form.addWidget(QLabel("Java"), 2, 0)
        self.lbl_java = QLabel()
        self.lbl_java.setObjectName("SideBrandSub")
        form.addWidget(self.lbl_java, 2, 1)
        form.addWidget(QLabel("内存"), 3, 0)
        self.cmb_mem = QComboBox()
        for m in ("512", "1024", "2048", "4096", "8192"):
            self.cmb_mem.addItem(m + " MB", int(m))
        self.cmb_mem.setCurrentIndex(2)  # 默认 2048
        form.addWidget(self.cmb_mem, 3, 1)
        form.setColumnStretch(1, 1)
        lc.addLayout(form)

        self.lbl_empty = QLabel("⚠ 当前无任何版本，请先安装游戏版本（游戏库 / 修复页可安装引导）。")
        self.lbl_empty.setStyleSheet("color: #FFB84D; font-size: 12px;")
        self.lbl_empty.setVisible(False)
        lc.addWidget(self.lbl_empty)

        row = QHBoxLayout()
        self.btn_launch = primary_btn("🚀 启动游戏")
        self.btn_launch.setMinimumHeight(46)
        self.btn_launch.clicked.connect(self._safe_launch)
        self.btn_stop = ghost_btn("停止")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_launch, 1)
        self.app._attach_memory(self.btn_launch, "launch_game", row)
        row.addWidget(self.btn_stop)
        self.app._attach_memory(self.btn_stop, "stop_game", row)
        lc.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lc.addWidget(self.progress)
        self.body_layout.addWidget(launch_card)

        # 分支入口网格
        entry_card = glass_card()
        el = QVBoxLayout(entry_card)
        el.setContentsMargins(24, 16, 24, 20)
        el.setSpacing(10)
        el.addWidget(section_title("功能入口"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self._entry_btns = {}
        for i, (key, icon, name, desc) in enumerate(self.ENTRIES):
            b = QPushButton("%s  %s\n%s" % (icon, name, desc))
            b.setObjectName("EntryCard")
            b.setCursor(Qt.PointingHandCursor)
            if key == "log":
                b.clicked.connect(self._toggle_log)
            else:
                b.clicked.connect(lambda _, k=key: self.app.goto(k))
            grid.addWidget(b, i // 3, i % 3)
            self._entry_btns[key] = b
        for col in range(3):
            grid.setColumnStretch(col, 1)
        el.addLayout(grid)
        self.body_layout.addWidget(entry_card)

        # 启动日志（默认展开，可折叠）
        self.log_card = glass_card()
        ll = QVBoxLayout(self.log_card)
        ll.setContentsMargins(20, 12, 20, 12)
        ll.setSpacing(8)
        self._log_head = QHBoxLayout()
        self._log_title = section_title("启动日志")
        self._log_head.addWidget(self._log_title)
        self._log_head.addStretch(1)
        self._log_btn = ghost_btn("收起")
        self._log_btn.clicked.connect(self._toggle_log)
        self._log_head.addWidget(self._log_btn)
        ll.addLayout(self._log_head)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setFixedHeight(150)
        ll.addWidget(self.log_view)
        self.body_layout.addWidget(self.log_card, 1)
        self._log_collapsed = False

        # 定时刷新环境状态
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()

    def _toggle_log(self):
        self._log_collapsed = not self._log_collapsed
        if self._log_collapsed:
            self.log_view.setVisible(False)
            self._log_btn.setText("展开")
            self._log_title.setText("启动日志（已折叠）")
        else:
            self.log_view.setVisible(True)
            self._log_btn.setText("收起")
            self._log_title.setText("启动日志")

    def refresh(self):
        cfg = self.app.config
        acc = current_account(cfg)
        if acc:
            self.lbl_name.setText("%s（%s）" % (acc.get("name", "?"),
                                               "微软正版" if acc.get("type") == "microsoft" else "离线"))
        else:
            self.lbl_name.setText("%s（设置页可修改）" % cfg.get("player_name", "KMCL Player"))
        javas = self.app.detect_javas()
        java_list = [str(k) for k in sorted(javas.keys(), key=int)] if javas else []
        if javas:
            self.lbl_java.setText("自动匹配：Java %s（缺失时自动下载）" % " / ".join(java_list))
        else:
            self.lbl_java.setText("未检测到系统 Java，启动时自动下载所需版本")
        # 版本列表（仅在变化时重建，避免覆盖用户选择）
        vers = scan_versions(self.app.mc_root())
        cur_items = [self.cmb_version.itemText(i) for i in range(self.cmb_version.count())]
        if vers:
            if cur_items != vers:
                cur = self.cmb_version.currentText()
                self.cmb_version.blockSignals(True)
                self.cmb_version.clear()
                for v in vers:
                    self.cmb_version.addItem(version_icon(self.app.base_dir, v), v)
                if cur and cur in vers:
                    self.cmb_version.setCurrentText(cur)
                elif vers:
                    self.cmb_version.setCurrentText(vers[0])
                self.cmb_version.blockSignals(False)
            self.cmb_version.setEnabled(True)
            self.btn_launch.setEnabled(True)
            self.lbl_empty.setVisible(False)
        else:
            if cur_items != ["当前无任何版本"]:
                self.cmb_version.blockSignals(True)
                self.cmb_version.clear()
                self.cmb_version.addItem("当前无任何版本")
                self.cmb_version.blockSignals(False)
            self.cmb_version.setEnabled(False)
            self.btn_launch.setEnabled(False)
            self.lbl_empty.setVisible(True)
        # 环境状态
        py_ok = os.path.exists(os.path.join(self.app.base_dir, "python", "python.exe"))
        java_txt = "内置 Python ✓" if py_ok else "内置 Python 缺失"
        java_txt += " · Java 8/17/21 ✓" if len(javas) >= 3 else (" · Java %s" % ("/".join(java_list) if java_list else "无"))
        self.env_label.setText(java_txt)

    def _safe_launch(self):
        """启动兜底：任何异常写入日志并弹窗，不再静默消失。"""
        try:
            self._launch()
        except Exception as e:
            import traceback
            try:
                log_dir = os.path.join(self.app.data_dir, "logs")
                os.makedirs(log_dir, exist_ok=True)
                with open(os.path.join(log_dir, "kmcl-error.log"), "a", encoding="utf-8") as f:
                    f.write("\n[%s] 启动异常\n%s\n" % (
                        time.strftime("%Y-%m-%d %H:%M:%S"), traceback.format_exc()))
            except Exception:
                pass
            QMessageBox.critical(self, "KMCL 启动错误",
                                 "启动过程中发生错误：\n%s\n\n详情已写入 logs/kmcl-error.log" % e)
            self.btn_launch.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.progress.setVisible(False)

    def _launch(self, check_deps=True):
        cfg = self.app.config
        version_id = self.cmb_version.currentText().strip()
        if version_id in ("", "当前无任何版本"):
            QMessageBox.warning(self, "KMCL", "当前没有已安装的游戏版本，无法启动。")
            return
        player_name = cfg.get("player_name", "") or "KMCL Player"
        # Alpha 3.0 · 账号系统：从当前账号取 uuid / access_token / 类型
        acc = current_account(cfg)
        acc_uuid = acc.get("uuid") if acc else None
        acc_token = acc.get("access_token") if acc else None
        acc_type = "msa" if (acc and acc.get("type") == "microsoft") else "legacy"
        mem_mb = self.cmb_mem.currentData() or 2048
        if cfg.get("auto_memory"):
            try:
                mem_mb = auto_heap_mb()
            except Exception:
                pass
        if cfg.get("preset_mem"):  # 性能预设指定堆内存时优先
            mem_mb = int(cfg.get("preset_mem") or 0) or mem_mb
        jvm_extra = ["-Xmx%dm" % mem_mb, "-Xms%dm" % min(mem_mb, 1024)]
        if cfg.get("perf_optimized"):
            for a in (cfg.get("perf_jvm_args") or []):
                if a not in jvm_extra:
                    jvm_extra.append(a)
        # 草方块引擎：画质预设 → 堆内存与 GC / 兼容参数；自动优化 → 启动前清内存
        ge = cfg.get("grass_engine") or {}
        if ge.get("enabled"):
            _preset = ge.get("preset", "balanced")
            if _preset == "low_end":  # 低端设备专属：小堆 + SerialGC + 允许软件 OpenGL
                mem_mb = max(1024, min(mem_mb, 2048))
                jvm_extra[0:2] = ["-Xmx%dm" % mem_mb, "-Xms%dm" % min(mem_mb, 1024)]
                for a in ("-XX:+UseSerialGC", "-XX:MaxGCPauseMillis=100",
                          "-Dorg.lwjgl.opengl.Display.allowSoftwareOpenGL=true"):
                    if a not in jvm_extra:
                        jvm_extra.append(a)
            elif _preset == "performance":  # 性能优先：压小堆上限保帧率
                mem_mb = max(1024, min(mem_mb, 3072))
                jvm_extra[0:2] = ["-Xmx%dm" % mem_mb, "-Xms%dm" % min(mem_mb, 1024)]
            elif _preset == "quality":  # 画质优先：给足堆内存
                mem_mb = min(max(mem_mb, 4096), 12288)
                jvm_extra[0:2] = ["-Xmx%dm" % mem_mb, "-Xms%dm" % min(mem_mb, 1024)]
            if ge.get("auto_optimize"):
                try:
                    clear_system_memory()
                except Exception:
                    pass
            if ge.get("blur"):  # 动态模糊（原版无键位，注入系统属性；需光影/模组支持）
                if "-Dkmcl.grass.dynamicBlur=true" not in jvm_extra:
                    jvm_extra.append("-Dkmcl.grass.dynamicBlur=true")
        # 兼容性：旧 OpenGL → 新 OpenGL（软件兼容，老 Intel 核显）
        if cfg.get("compat_opengl"):
            for a in ("-Dorg.lwjgl.opengl.Display.allowSoftwareOpenGL=true",
                      "-Dsun.java2d.opengl=false"):
                if a not in jvm_extra:
                    jvm_extra.append(a)
        # 兼容性：旧 OpenGL → Vulkan（实验性，性能损耗大）
        if cfg.get("compat_vulkan"):
            for a in ("-Dorg.lwjgl.opengl.Display.allowSoftwareOpenGL=true",
                      "-Dorg.lwjgl.opengl.Display.disableOverlayCheck=true"):
                if a not in jvm_extra:
                    jvm_extra.append(a)
        # 自定义 JVM 参数（每行一个）
        for ln in (cfg.get("custom_jvm_args") or "").splitlines():
            a = ln.strip()
            if a and a not in jvm_extra:
                jvm_extra.append(a)
        # 自定义游戏参数（每行一个）
        game_extra = []
        for ln in (cfg.get("custom_game_args") or "").splitlines():
            a = ln.strip()
            if a:
                game_extra.append(a)
        cfg["game_version"] = version_id
        cfg["player_name"] = player_name
        self.app.save_config()

        mc_root = self.app.mc_root()
        from java_manager import load_version_chain, resolve_java_major, ensure_java, build_launch_command

        # 选 Java：优先系统已安装，没有则按需自动下载（不内置）
        java_exe = ""
        java_err = ""
        need_repair = None  # 在 try 外初始化，防止 UnboundLocalError
        req = 17
        try:
            merged, base = load_version_chain(mc_root, version_id)
            # 综合版本 json 要求 + 版本 jar 主类编译版本（新版 Cleanroom 等需 Java 21/25）
            req = resolve_java_major(mc_root, version_id, merged, base)
            if cfg.get("gc_log"):  # GC 日志诊断：按 Java 主版本选参数
                if req and req <= 8:
                    jvm_extra += ["-Xloggc:logs/gc.log", "-verbose:gc"]
                else:
                    jvm_extra += ["-Xlog:gc*:file=logs/gc_%t.log:filemax=5m"]
        except Exception as e:
            java_err = "读取版本信息失败：%s" % e
            try:
                need_repair = self._missing_parent(version_id, mc_root, e)
            except Exception:
                need_repair = None
        if java_exe == "" and not java_err:
            try:
                java_exe = ensure_java(req, self.app.base_dir,
                                       progress=self.app._jdk_progress,
                                       cancel=self.app._jdk_cancel)
                self.app._jdk_done()
            except Exception as e:
                java_err = "未找到可用的 Java %d：%s" % (req, e)
        if need_repair:
            self._auto_repair(need_repair, version_id)
            return
        # 老电脑优化：启动前自动清内存 / 结束指定进程（用户主动开启）
        if cfg.get("prelaunch_mem"):
            try:
                clear_system_memory()
            except Exception:
                pass
        for exe in (cfg.get("prelaunch_kill") or []):
            try:
                subprocess.run(["taskkill", "/F", "/IM", exe],
                               creationflags=subprocess.CREATE_NO_WINDOW,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        # 依赖自检：缺失则后台自动补齐，完成后自动继续启动
        # （check_deps=False 时跳过，防止补齐后再次进入自检形成死循环）
        # 注意：必须把 native_jars 一并计入，否则只缺原生库时不会触发补齐，
        #       游戏会因 no lwjgl64 in java.library.path 直接崩溃。
        if check_deps and java_exe and os.path.exists(java_exe):
            try:
                import repair_game
                _t, _nj, _ = repair_game.collect_tasks(version_id, mc_root)
                _miss = sum(1 for t in _t if repair_game.need_download(t[1], t[2], t[3]))
                _miss += sum(1 for t in (_nj or [])
                             if repair_game.need_download(t[1], t[2], t[3]))
                if _miss:
                    self._auto_fetch_libs(_miss, version_id)
                    return
            except Exception:
                pass
        if not java_exe or not os.path.exists(java_exe):
            QMessageBox.warning(self, "KMCL", "无法启动：\n%s" % (java_err or "未找到可用的 Java"))
            return

        try:
            # 版本隔离（强制，不再支持共享目录）：每个版本独立游戏目录
            # versions/<版本名>，存档/模组/光影/配置都放这里，互不干扰
            game_dir = os.path.join(mc_root, "versions", version_id)
            os.makedirs(game_dir, exist_ok=True)
            # 草方块引擎：画质预设 + TAA 写入游戏 options.txt（版本隔离时写入隔离目录）
            if ge.get("enabled"):
                try:
                    apply_grass_engine_options(game_dir or mc_root, version_id, ge)
                except Exception:
                    pass
            cmd = build_launch_command(
                java_exe, version_id, mc_root, player_name,
                jvm_extra=jvm_extra, game_extra=game_extra,
                game_dir=game_dir,
                access_token=acc_token, uuid=acc_uuid, user_type=acc_type,
            )
        except Exception as e:
            QMessageBox.critical(self, "KMCL", "组装启动命令失败：\n%s" % e)
            return

        self.log_view.clear()
        self.log_view.appendPlainText("> %s" % " ".join(cmd[:8]) + " ...")
        self.btn_launch.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.launcher = LaunchThread(cmd, mc_root)
        self.app._track_thread(self.launcher)
        self.launcher.log.connect(self.log_view.appendPlainText)
        self.launcher.finished_ok.connect(self._on_started)
        self.launcher.failed.connect(lambda e: self._append_err("启动失败: " + e))
        # 游戏进程结束时（线程 run 结束）恢复界面状态
        self.launcher.finished.connect(self._on_game_exited)
        self.launcher.start()

    def _missing_parent(self, version_id, mc_root, err):
        """从异常中推断缺失的原版父版本 id。"""
        m = re.search(r"versions[\\/]+([^\\/]+?)[\\/]+([^\\/]+?)\.json", str(err))
        if m:
            vid = m.group(1)
            if vid != version_id:
                return vid
        m2 = re.match(r"(\d+\.\d+(?:\.\d+)?)", version_id)
        if m2:
            cand = m2.group(1)
            if not os.path.exists(os.path.join(mc_root, "versions", cand, cand + ".json")):
                return cand
        return None

    def _auto_fetch_libs(self, miss_n, version_id):
        self.log_view.appendPlainText("检测到 %d 个缺失依赖，自动补齐（首次可能较慢）…" % miss_n)
        self.progress.setVisible(True)
        self.progress.setRange(0, miss_n)
        self.progress.setValue(0)
        self.btn_launch.setEnabled(False)
        self.libs_thread = MissingLibsThread(version_id, self.app.mc_root())
        self.app._track_thread(self.libs_thread)
        self.libs_thread.stage.connect(self.log_view.appendPlainText)
        self.libs_thread.progress.connect(lambda i, n: self.progress.setValue(i))
        self.libs_thread.done.connect(lambda ok, msg: self._on_libs_done(ok, msg, version_id))
        self.libs_thread.start()

    def _on_libs_done(self, ok, msg, version_id):
        self.progress.setVisible(False)
        if ok:
            self.log_view.appendPlainText(msg + "，正在启动…")
            self._launch(check_deps=False)
        else:
            QMessageBox.warning(self, "KMCL", "依赖补齐失败：\n%s" % msg)
            self.btn_launch.setEnabled(True)

    def _auto_repair(self, vid, version_id):
        self.log_view.appendPlainText("检测到缺少原版核心 %s，正在自动下载…" % vid)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.btn_launch.setEnabled(False)
        self.repair_thread = VanillaRepairThread(vid, self.app.mc_root())
        self.app._track_thread(self.repair_thread)
        self.repair_thread.stage.connect(self.log_view.appendPlainText)
        self.repair_thread.done.connect(lambda ok, msg: self._on_repair_done(ok, msg, version_id))
        self.repair_thread.start()

    def _on_repair_done(self, ok, msg, version_id):
        self.progress.setVisible(False)
        if ok:
            self.log_view.appendPlainText("原版核心补齐完成，正在重新启动…")
            self._launch()
        else:
            QMessageBox.warning(self, "KMCL", "自动修复失败：\n%s" % msg)
            self.btn_launch.setEnabled(True)

    def _on_started(self, pid):
        self._append_err("游戏进程已启动 (PID %d)" % pid)
        self.progress.setVisible(False)
        # 游玩统计：记录启动次数与本次启动时间点
        c = self.app.config
        c["launch_count"] = int(c.get("launch_count", 0)) + 1
        self._play_start_ts = time.time()
        self.app.save_config()
        # 全局游戏设置：启动器可见性
        mode = self.app.config.get("launcher_visibility", "visible")
        if mode == "exit":
            # 游戏启动后结束启动器（延迟 2 秒等游戏窗口出现；游戏是独立进程不受影响）
            QTimer.singleShot(2000, self.app.close)
        elif mode == "hide":
            self.app.hide()
        elif mode == "hide_restore":
            self.app.hide()

    def _on_game_exited(self):
        """游戏进程已结束：恢复界面状态；hide_restore 模式重新显示启动器。"""
        self._append_err("游戏进程已退出")
        # 游玩统计：累计本次游玩时长
        c = self.app.config
        if getattr(self, "_play_start_ts", None):
            c["play_seconds"] = int(c.get("play_seconds", 0)) + int(time.time() - self._play_start_ts)
            self._play_start_ts = None
            self.app.save_config()
        self.btn_launch.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        if self.app.config.get("launcher_visibility") == "hide_restore":
            self.app.show()
            self.app.raise_()
            self.app.activateWindow()

    def _append_err(self, text):
        self.log_view.appendPlainText(text)

    def _stop(self):
        if self.launcher:
            self.launcher.stop()
            self._append_err("已请求停止游戏进程")
            self.btn_launch.setEnabled(True)
            self.btn_stop.setEnabled(False)


# ============================================================
# Modrinth 在线资源（线程）
# ============================================================
class ModrinthListThread(QThread):
    done = pyqtSignal(object)
    fail = pyqtSignal(str)

    def __init__(self, ptype, query, mc_version, offset=0):
        super().__init__()
        self.ptype, self.query, self.mc_version = ptype, query, mc_version
        self.offset = offset

    def run(self):
        try:
            from modrinth_api import modrinth_search
            hits, total = modrinth_search(self.ptype, self.query, self.mc_version, limit=20, offset=self.offset)
            self.done.emit((hits, total))
        except Exception as e:
            self.fail.emit(str(e))


class ModrinthVersionsThread(QThread):
    got = pyqtSignal(object, list)
    fail = pyqtSignal(str)

    def __init__(self, project, mc_version, loaders=None):
        super().__init__()
        self.project = project
        self.mc_version = mc_version
        self.loaders = loaders or []

    def run(self):
        try:
            from modrinth_api import project_versions, pick_versions
            vs = project_versions(self.project["project_id"], self.mc_version)
            # 按当前筛选的加载器过滤：只保留加载器一致的版本（如筛选 Fabric 就不混 NeoForge/Forge）
            if self.loaders:
                want = set(self.loaders)
                ok = []
                for v in vs:
                    ls = v.get("loaders") or []
                    if not isinstance(ls, list):
                        ls = [ls]
                    if want & set(ls):
                        ok.append(v)
                vs = ok
            # 精简展示：1 个最新版 + 3 个稳定版，避免一次列太多卡顿
            vs = pick_versions(vs)
            self.got.emit(self.project, vs)
        except Exception as e:
            self.fail.emit(str(e))


class ModrinthSizesThread(QThread):
    """并行拉取一批项目最新版的文件大小（镜像优先），逐条回填列表。"""
    size_ready = pyqtSignal(int, str)   # (列表索引, 大小文本)

    def __init__(self, items, workers=6):
        # items: [(index, project_id, mc_version, loader), ...]
        super().__init__()
        self.items = items
        self.workers = workers
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        from modrinth_api import project_versions
        from mod_zh import fmt_size

        def one(it):
            i, pid, mc, loader = it
            try:
                vs = project_versions(pid, mc)   # 镜像优先、官方兜底
                if loader:
                    want = loader
                    vs = [v for v in vs
                          if want in (v.get("loaders") or [])]
                for v in vs[:3]:
                    if v.get("size"):
                        return i, fmt_size(v["size"])
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            for res in ex.map(one, self.items):
                if self._cancel:
                    break
                if res and res[1]:
                    self.size_ready.emit(res[0], res[1])


class ModrinthDownloadThread(QThread):
    progress = pyqtSignal(int, int)
    dep_notice = pyqtSignal(str)     # 依赖补齐提示（如「发现 2 个依赖，自动补齐…」）
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, dest, version_id="", mc_version="", dep_dir=None,
                 loaders=None):
        super().__init__()
        self.url, self.dest = url, dest
        self.version_id, self.mc_version = version_id, mc_version
        self.dep_dir = dep_dir
        self.loaders = loaders or []
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            from modrinth_api import download_file, collect_deps, dep_installed
            download_file(self.url, self.dest,
                          progress=lambda d, t: self.progress.emit(d, t),
                          cancel=lambda: self._cancel)
            # ---- 依赖自动补齐：required 依赖（含嵌套）直接下载到同类型目录 ----
            if self.dep_dir and self.version_id:
                try:
                    files, unresolved = collect_deps(
                        {"version_id": self.version_id},
                        self.mc_version or "", self.loaders)
                    real = [f for f in files if f.get("url")]
                    if real:
                        self.dep_notice.emit("检查 %d 个依赖：已安装的自动跳过…" % len(real))
                        total = len(real)
                        installed, fetched = 0, 0
                        for i, f in enumerate(real, 1):
                            if self._cancel:
                                break
                            fn = f.get("filename") or "dep_%s.jar" % (f.get("version_id") or "?")
                            dp = os.path.join(self.dep_dir, fn)
                            hit, hit_name = dep_installed(f, self.dep_dir)
                            if hit:
                                installed += 1  # 已安装（同名或同项目），跳过
                                continue
                            try:
                                download_file(f["url"], dp,
                                              cancel=lambda: self._cancel)
                                fetched += 1
                            except Exception:
                                continue  # 单个依赖失败不阻塞整体
                        self.dep_notice.emit(
                            "依赖检查完成：已装 %d 个（跳过）· 新装 %d 个%s" % (
                                installed, fetched,
                                "；%d 个未能解析" % len(unresolved) if unresolved else ""))
                except Exception:
                    pass  # 依赖解析失败不影响主文件下载
            self.finished_ok.emit(self.dest)
        except Exception as e:
            self.failed.emit(str(e))


class ResourceListThread(QThread):
    """拉取在线资源列表（Modrinth，镜像优先官方兜底）。"""
    done = pyqtSignal(object, int)   # (hits, total)
    fail = pyqtSignal(str)

    def __init__(self, ptype, query, mc_version, loader, offset=0):
        super().__init__()
        self.ptype, self.query = ptype, query
        self.mc_version, self.loader = mc_version, loader
        self.offset = offset

    def run(self):
        try:
            from modrinth_api import modrinth_search
            hits, total = modrinth_search(self.ptype, self.query, self.mc_version,
                                          limit=20, offset=self.offset, loaders=self.loader)
            hits.sort(key=lambda x: x.get("downloads", 0), reverse=True)
            self.done.emit(hits, total)
        except Exception as e:
            self.fail.emit(str(e))


class IconLoader(QThread):
    """异步下载 Modrinth 项目图标（本地缓存，md5 文件名）。"""
    done = pyqtSignal(object, QPixmap)

    def __init__(self, label, url, cache_dir):
        super().__init__()
        self._label, self._url, self._cache = label, url, cache_dir

    def run(self):
        try:
            import hashlib
            import urllib.request as _ur
            key = hashlib.md5(self._url.encode("utf-8")).hexdigest()[:16]
            path = os.path.join(self._cache, key + ".png")
            if not os.path.exists(path):
                req = _ur.Request(self._url, headers={"User-Agent": "KMCL-Community/1.0"})
                data = _ur.urlopen(req, timeout=15).read()
                os.makedirs(self._cache, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
                # 缓存超限自动瘦身（防止随浏览无限膨胀）
                trim_icon_cache(self._cache)
            pix = QPixmap(path)
            if not pix.isNull():
                pix = pix.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.done.emit(self._label, pix)
        except Exception:
            pass


def trim_icon_cache(cache_dir, limit_mb=50):
    """图标缓存自动瘦身：总大小超过 limit_mb MB 时清空目录内所有文件（保留目录本身）。

    .icon_cache 随浏览在线资源（模组/光影/数据包等）不断累积图标文件，
    达到阈值即清空，下次需要时重新下载，避免无限膨胀占用磁盘。
    """
    try:
        if not os.path.isdir(cache_dir):
            return
        total = 0
        for dp, _, fns in os.walk(cache_dir):
            for fn in fns:
                try:
                    total += os.path.getsize(os.path.join(dp, fn))
                except OSError:
                    pass
        if total <= limit_mb * 1024 * 1024:
            return
        for n in os.listdir(cache_dir):
            p = os.path.join(cache_dir, n)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError:
                pass
    except Exception:
        pass


class ModpackInstallThread(QThread):
    """安装 .mrpack 整合包（Modrinth 格式）到游戏根目录。"""
    stage = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    fail = pyqtSignal(str)

    def __init__(self, mrpack_path, game_root):
        super().__init__()
        self.mrpack_path, self.game_root = mrpack_path, game_root
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            from modrinth_api import install_mrpack
            self.stage.emit("解析整合包索引…")
            info = install_mrpack(
                self.mrpack_path, self.game_root,
                progress=lambda d, t: self.progress.emit(d, t),
                cancel=lambda: self._cancel)
            self.done.emit(info.get("name", "整合包"))
        except Exception as e:
            self.fail.emit(str(e))


class VersionPicker(QDialog):
    """版本选择弹窗：列出项目全部适配版本供用户选择。"""

    def __init__(self, project, versions=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(project.get("title", "选择版本"))
        self.setModal(True)
        self.resize(560, 420)
        self._chosen = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        title = QLabel(project.get("title", ""))
        title.setObjectName("PageTitle")
        lay.addWidget(title)
        self.sub = QLabel("正在加载版本列表，请稍候…")
        self.sub.setObjectName("SideBrandSub")
        lay.addWidget(self.sub)
        self.list = QListWidget()
        self.list.setObjectName("VersionList")
        self.list.setEnabled(False)
        lay.addWidget(self.list, 1)
        if versions is not None:
            self.populate(versions)
        btns = QHBoxLayout()
        ok = primary_btn("下载此版本")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self._ok)
        cancel = ghost_btn("取消")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

    def populate(self, versions):
        """线程返回后填充版本列表。"""
        self.sub.setText("已列出 %d 个版本：1 个最新版 + 稳定版（加载器已过滤）" % len(versions))
        self.list.setEnabled(True)
        self.list.clear()
        for v in versions:
            loaders = ",".join(v.get("loaders", [])) or "vanilla"
            info = "%s  [%s]  [%s]  %s" % (
                v.get("version_number") or v.get("name", "?"),
                ",".join(v.get("game_versions", [])[:2]) or "?",
                loaders,
                v.get("filename", ""),
            )
            item = QListWidgetItem(info)
            item.setData(Qt.UserRole, v)
            item.setToolTip("加载器: %s" % (",".join(v.get("loaders", [])) or "vanilla"))
            self.list.addItem(item)
        # 默认选中第一项（最新版），且始终按最新->最旧展示
        if self.list.count():
            self.list.setCurrentRow(0)

    def _ok(self):
        item = self.list.currentItem()
        if item:
            self._chosen = item.data(Qt.UserRole)
            self.accept()

    def chosen(self):
        return self._chosen


# ============================================================
# 资源分区（在线 Modrinth + 本地已安装）
# ============================================================
def fmt_size(n):
    if n >= 1048576:
        return "%.1f MB" % (n / 1048576)
    if n >= 1024:
        return "%.1f KB" % (n / 1024)
    return "%d B" % n


class ResourcePane(QWidget):
    """在线资源（Modrinth）：版本过滤 / 显示默认 / 搜索 / 图标列表 / 分页 / 下载。"""

    PAGE_SIZE = 20

    def __init__(self, app, rel, label, ptype, install_after=False):
        super().__init__()
        self.app = app
        self.rel = rel
        self.label = label
        self.ptype = ptype
        self.install_after = install_after
        self._list_thread = None
        self._ver_thread = None
        self._dl_thread = None
        self._mp_thread = None
        self._sizes_thread = None
        self._icon_loaders = []
        self._hits = []
        self._query = ""
        self._offset = 0
        self._total = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        top = QHBoxLayout()
        tl = QLabel("🌐 在线资源")
        tl.setObjectName("SectionTitle")
        top.addWidget(tl)
        # 安装目标实例：模组/光影/数据包/资源包/整合包下载后装到哪个游戏版本。
        # KMCL 强制版本隔离（不再支持共享目录）：资源全部写入 versions/<版本>/，
        # 各版本互不干扰；以哪个版本启动就读取哪个版本的资源。
        top.addWidget(QLabel("安装到"))
        self.cmb_inst = QComboBox()
        self.cmb_inst.setFixedWidth(180)
        self.cmb_inst.setCursor(Qt.PointingHandCursor)
        self.cmb_inst.setToolTip(
            "选择下载资源的安装目标版本（强制版本隔离）：\n"
            "资源会下载到 versions/该版本/ 对应的文件夹，各版本完全隔离\n"
            "以哪个版本启动游戏，就读取哪个版本的模组/光影/数据包等")
        self.cmb_inst.currentIndexChanged.connect(self._on_inst_changed)
        top.addWidget(self.cmb_inst)
        top.addStretch(1)
        # 模组 / 整合包 / 数据包需要加载器筛选，光影与资源包不需要
        self.cmb_loader = None
        if self.ptype in ("mod", "modpack", "datapack"):
            top.addWidget(QLabel("加载器"))
            self.cmb_loader = QComboBox()
            # 全部加载器（含远古/小众）：value 为 Modrinth 分类 slug，与 loaders_for_version 映射
            self._loader_choices = (
                ("", "全部"), ("vanilla", "原版"), ("fabric", "Fabric"),
                ("forge", "Forge"), ("neoforge", "NeoForge"), ("quilt", "Quilt"),
                ("modloader", "ModLoader"), ("liteloader", "LiteLoader"),
                ("rift", "Rift"), ("legacy-fabric", "Legacy Fabric"),
                ("cleanroom", "Cleanroom"),
            )
            for lk, ln in self._loader_choices:
                self.cmb_loader.addItem(ln, lk)
            self.cmb_loader.currentIndexChanged.connect(lambda: self._search(self.edt_q.text()))
            top.addWidget(self.cmb_loader)
        top.addWidget(QLabel("版本"))
        self.edt_ver = QLineEdit()
        self.edt_ver.setPlaceholderText("输入版本号，如 1.20.1（留空=全部）")
        self.edt_ver.setFixedWidth(130)
        self.edt_ver.editingFinished.connect(self._refill_loaders)
        self.edt_ver.returnPressed.connect(self._refill_loaders)
        self.edt_ver.returnPressed.connect(lambda: self._search(self.edt_q.text()))
        top.addWidget(self.edt_ver)
        lay.addLayout(top)

        sr = QHBoxLayout()
        self.edt_q = QLineEdit()
        self.edt_q.setPlaceholderText("搜索 %s…" % self.label)
        self.edt_q.returnPressed.connect(lambda: self._search(self.edt_q.text()))
        sr.addWidget(self.edt_q, 1)
        self.btn_search = ghost_btn("搜索")
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.clicked.connect(lambda: self._search(self.edt_q.text()))
        sr.addWidget(self.btn_search)
        lay.addLayout(sr)

        self.result_list = QListWidget()
        self.result_list.setObjectName("VersionList")
        self.result_list.setIconSize(QSize(32, 32))
        self.result_list.itemDoubleClicked.connect(lambda _: self._download())
        lay.addWidget(self.result_list, 1)

        pg = QHBoxLayout()
        self.btn_prev = ghost_btn("◀ 上一页")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_prev.setEnabled(False)
        self.btn_next = ghost_btn("下一页 ▶")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self._next_page)
        self.btn_next.setEnabled(False)
        self.lbl_page = QLabel("")
        self.lbl_page.setObjectName("SideBrandSub")
        pg.addWidget(self.btn_prev)
        pg.addWidget(self.lbl_page)
        pg.addWidget(self.btn_next)
        pg.addStretch(1)
        lay.addLayout(pg)

        dr = QHBoxLayout()
        self.btn_dl = primary_btn("下载选中")
        self.btn_dl.setCursor(Qt.PointingHandCursor)
        self.btn_dl.clicked.connect(self._download)
        self.btn_cancel = ghost_btn("取消")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._cancel_dl)
        self.btn_cancel.setEnabled(False)
        self.lbl_online = QLabel("")
        self.lbl_online.setObjectName("SideBrandSub")
        dr.addWidget(self.btn_dl)
        dr.addWidget(self.btn_cancel)
        dr.addStretch(1)
        dr.addWidget(self.lbl_online)
        lay.addLayout(dr)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        # 懒加载：构造时不发网络请求，首次可见（ensure_loaded）才拉取默认列表，
        # 避免 6 个资源分区一次性并发请求 Modrinth 拖慢启动/退出
        self._loaded = False
        self.lbl_online.setText("")
        self._fill_instances()

    def _fill_instances(self):
        """填充"安装到"下拉框：全部已安装版本（强制版本隔离，无共享目录）。

        自动默认选中最新版本；没有任何已安装版本时禁用下载。
        """
        self.cmb_inst.blockSignals(True)
        try:
            self.cmb_inst.clear()
            for vid in scan_versions(self.app.mc_root()):
                self.cmb_inst.addItem(vid, vid)
        finally:
            self.cmb_inst.blockSignals(False)
        if self.cmb_inst.count():
            self.cmb_inst.setCurrentIndex(0)
        self._update_dl_enabled()

    def _update_dl_enabled(self):
        has = self.cmb_inst.count() > 0
        self.btn_dl.setEnabled(has)
        if not has:
            self.lbl_online.setText("请先在「下载游戏」中安装至少一个版本")
        self.refresh()

    def _on_inst_changed(self):
        """切换安装目标后确保目标目录存在。"""
        self.refresh()

    def ensure_loaded(self):
        """首次显示时加载默认列表；已加载过则不重复请求。"""
        if self._loaded:
            return
        self._loaded = True
        self.lbl_online.setText("加载中…")
        self._search("")

    # ---- 在线搜索/默认 ----
    def _inst_root(self):
        """当前安装目标版本的游戏根：mc_root/versions/<版本>（强制版本隔离）。"""
        vid = self.cmb_inst.currentData() if self.cmb_inst else None
        if vid:
            return os.path.join(self.app.mc_root(), "versions", vid)
        return None

    def path(self):
        inst = self._inst_root()
        if inst:
            return os.path.join(inst, self.rel)
        return os.path.join(self.app.mc_root(), self.rel)  # 无版本时的兜底（正常不会走到）

    def refresh(self):
        """确保下载目标目录存在（本地列表已移除）。"""
        p = self.path()
        try:
            if not os.path.isdir(p):
                os.makedirs(p, exist_ok=True)
        except OSError:
            pass

    def _mc_version(self):
        return self.edt_ver.text().strip() or ""

    def _current_loaders(self):
        """当前筛选的加载器列表（搜索/版本过滤/依赖解析共用）。
        非模组/整合包（无加载器栏）返回 None；Cleanroom 兼容 Forge 生态。"""
        if not self.cmb_loader:
            return None
        lk = self.cmb_loader.currentData() or ""
        if lk == "cleanroom":
            return ["cleanroom", "forge"]
        return [lk] if lk else None

    def _refill_loaders(self):
        """按输入的 MC 版本过滤加载器选项（如 1.12.2 下不提供 Fabric/NeoForge）。
        版本留空则显示全部加载器。"""
        if not self.cmb_loader:
            return  # 无加载器栏的资源类型（光影/数据包/资源包）无需过滤
        ver = self._mc_version()
        try:
            from game_download import loaders_for_version
            supported = None
            if ver:
                supported = set(loaders_for_version(ver))
                # loaders_for_version 返回 legacyfabric（无连字符），选项 key 用 Modrinth slug legacy-fabric
                if "legacyfabric" in supported:
                    supported.discard("legacyfabric")
                    supported.add("legacy-fabric")
        except Exception:
            supported = None
        cur = self.cmb_loader.currentData() or ""
        self.cmb_loader.blockSignals(True)
        try:
            self.cmb_loader.clear()
            for lk, ln in self._loader_choices:
                if supported is not None and lk and lk not in supported:
                    continue
                self.cmb_loader.addItem(ln, lk)
        finally:
            self.cmb_loader.blockSignals(False)
        # 恢复选择：原选择仍可用则保留，否则回退「全部」
        idx = self.cmb_loader.findData(cur)
        self.cmb_loader.setCurrentIndex(idx if idx >= 0 else 0)

    def _icon_cache(self):
        return self.app.cache_dir

    def _search(self, query):
        self._query = query
        self._offset = 0
        self._load_page()

    def _load_page(self):
        self._hits = []
        self.result_list.clear()
        self.lbl_online.setText("加载中…")
        self.btn_search.setEnabled(False)
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)
        if self._sizes_thread is not None:
            try:
                self._sizes_thread.cancel()
            except Exception:
                pass
            self._sizes_thread = None
        lk = (self.cmb_loader.currentData() or "") if self.cmb_loader else ""
        # Cleanroom 基于 Forge：Modrinth 无 cleanroom 分类，映射为 forge 分类搜索
        if lk == "cleanroom":
            lk = "forge"
        # 中文关键词 -> 英文 slug（mod_zh 映射表），让中文筛选也能搜出结果
        from mod_zh import zh_to_search_query
        sq = zh_to_search_query(self._query)
        self._list_thread = ResourceListThread(
            self.ptype, sq, self._mc_version(), lk, self._offset)
        self.app._track_thread(self._list_thread)
        self._list_thread.done.connect(self._on_list)
        self._list_thread.fail.connect(lambda e: (self.lbl_online.setText("失败：%s" % e),
                                                  self.btn_search.setEnabled(True)))
        self._list_thread.start()

    def _item_text(self, h, size_text=""):
        """条目文本：英文名 + 大小 + 中文名（第二行为简介，中文优先）。"""
        from mod_zh import zh_name, zh_desc
        en = h.get("title") or h.get("slug") or "?"
        slug = h.get("slug") or ""
        zh = zh_name(slug, en)
        parts = [en]
        if size_text:
            parts.append(size_text)
        if zh and zh != en:   # 未命中映射时中文名回退英文，避免重复
            parts.append(zh)
        line1 = "  ".join(parts)
        line2 = zh_desc(slug, h.get("desc") or "")
        return "%s\n%s" % (line1, line2) if line2 else line1

    def _apply_icon(self, item, index, pix):
        """图标回填：item 可能已被列表刷新删除（Qt 侧销毁后访问任何成员都抛
        RuntimeError）。先按索引取当前项，用 Python 引用比对确认仍是同一条目，
        才调用 setIcon——全程不触碰可能已失效的 C++ 对象。"""
        try:
            if pix.isNull():
                return
            if index < 0 or index >= self.result_list.count():
                return
            cur = self.result_list.item(index)
            if cur is item:   # 引用比对（纯 Python，安全）；列表已重建则为 False
                item.setIcon(QIcon(pix))
        except RuntimeError:
            pass  # item 已被 Qt 删除，忽略

    def _on_size(self, index, size_text):
        """大小回填：仅当该条目仍在当前列表中时更新，避免翻页/刷新后写错条目。"""
        try:
            if index < 0 or index >= len(self._hits) or index >= self.result_list.count():
                return
            item = self.result_list.item(index)
            if item is None or item.listWidget() is None:
                return
            item.setText(self._item_text(self._hits[index], size_text))
        except Exception:
            pass

    def _on_list(self, hits, total):
        self.btn_search.setEnabled(True)
        self._hits = hits
        self._total = total
        self.result_list.clear()
        self._icon_loaders = []
        for index, h in enumerate(hits):
            item = QListWidgetItem(self._item_text(h))
            item.setData(Qt.UserRole, h)
            item.setToolTip("作者: %s · 双击下载" % h.get("author", "?"))
            self.result_list.addItem(item)
            if h.get("icon_url"):
                loader = IconLoader(item, h["icon_url"], self._icon_cache())
                # 跨线程回调：item 可能已被列表刷新删除，直接访问任何成员都会抛
                # RuntimeError。这里只做 Python 引用比对，安全后再设图标。
                loader.done.connect(lambda it, pix, i=index: self._apply_icon(it, i, pix))
                self.app._track_thread(loader)
                self._icon_loaders.append(loader)
                loader.start()
        # 异步并行拉取文件大小
        lk = (self.cmb_loader.currentData() or "") if self.cmb_loader else ""
        if lk == "cleanroom":
            lk = "forge"
        mc = self._mc_version()
        items = [(i, h.get("project_id"), mc, lk) for i, h in enumerate(hits)
                 if h.get("project_id")]
        if items:
            self._sizes_thread = ModrinthSizesThread(items)
            self.app._track_thread(self._sizes_thread)
            self._sizes_thread.size_ready.connect(self._on_size)
            self._sizes_thread.start()
        # 分页状态
        per = self.PAGE_SIZE
        cur = self._offset // per + 1
        pages = max(1, (total + per - 1) // per)
        self.lbl_page.setText("第 %d / %d 页 · 共 %d 个" % (cur, pages, total))
        self.btn_prev.setEnabled(self._offset > 0)
        self.btn_next.setEnabled(self._offset + per < total)
        self.lbl_online.setText("已加载 %d 个结果" % len(hits))

    def _next_page(self):
        self._offset += self.PAGE_SIZE
        self._load_page()

    def _prev_page(self):
        self._offset = max(0, self._offset - self.PAGE_SIZE)
        self._load_page()

    # ---- 下载流程 ----
    def _download(self):
        item = self.result_list.currentItem()
        if not item:
            QMessageBox.information(self, "KMCL", "请先在结果列表中选择一个资源。")
            return
        if not self._inst_root():
            QMessageBox.warning(self, "KMCL", "尚未安装任何游戏版本，请先到「下载游戏」安装一个版本。")
            return
        project = item.data(Qt.UserRole)
        # 点击后立即弹出版本窗口（加载中态），避免网络慢时误以为无响应
        picker = VersionPicker(project, None, self)
        picker.show()

        def on_got(prj, versions):
            if not versions:
                picker.sub.setText("该项目没有适配当前版本的下载。")
                return
            picker.populate(versions)

        def on_fail(e):
            picker.sub.setText("加载版本列表失败：%s" % e)

        def _loader_arg():
            return self._current_loaders()

        self._ver_thread = ModrinthVersionsThread(
            project, self._mc_version(), loaders=_loader_arg())
        self.app._track_thread(self._ver_thread)
        self._ver_thread.got.connect(on_got)
        self._ver_thread.fail.connect(on_fail)
        self._ver_thread.start()
        picker.finished.connect(lambda _: self._do_download(project, picker.chosen()))

    def _do_download(self, project, chosen):
        if not chosen:
            self.lbl_online.setText("已取消选择版本")
            return
        inst = self._inst_root()
        if not inst:
            # 强制版本隔离：没有已安装版本时不落到共享目录
            QMessageBox.warning(self, "KMCL", "尚未选择安装目标版本，请先在「下载游戏」中安装一个版本。")
            return
        url = chosen.get("url") or ""
        if not url:
            self.lbl_online.setText("该版本没有可下载的文件（镜像可能未同步，可先选其它版本再试）")
            return
        dest = os.path.join(self.path(), chosen.get("filename") or "download.jar")
        self.lbl_online.setText("下载 %s …" % chosen.get("filename", ""))
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.btn_cancel.setEnabled(True)
        self.btn_dl.setEnabled(False)
        self._dl_thread = ModrinthDownloadThread(
            url, dest,
            version_id=chosen.get("version_id", ""),
            mc_version=self._mc_version(),
            dep_dir=self.path(),
            loaders=self._current_loaders())
        self.app._track_thread(self._dl_thread)
        self._dl_thread.progress.connect(self._on_dl_progress)
        self._dl_thread.dep_notice.connect(lambda s: (setattr(self, "_last_dep_notice", s),
                                                      self.lbl_online.setText(s)))
        self._dl_thread.finished_ok.connect(self._on_dl_done)
        self._dl_thread.failed.connect(lambda e: (self.lbl_online.setText("下载失败：%s" % e),
                                                  self.progress.setVisible(False),
                                                  self.btn_cancel.setEnabled(False),
                                                  self.btn_dl.setEnabled(True)))
        self._dl_thread.start()

    def _on_dl_progress(self, done, total):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    def _on_dl_done(self, dest):
        self.progress.setVisible(False)
        self.btn_cancel.setEnabled(False)
        self.btn_dl.setEnabled(True)
        if self.ptype == "modpack" and self.install_after:
            self._install_modpack(dest)
            return
        dep = getattr(self, "_last_dep_notice", "")
        self.lbl_online.setText("已下载：%s%s" % (
            os.path.basename(dest), "（%s）" % dep if dep else ""))
        self.refresh()

    def _install_modpack(self, mrpack_path):
        """整合包：下载完 .mrpack 后安装到游戏根目录（mods/config/overrides 等）"""
        self.lbl_online.setText("开始安装整合包…")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.btn_dl.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self._mp_thread = ModpackInstallThread(
            mrpack_path, self._inst_root() or self.app.mc_root())
        self.app._track_thread(self._mp_thread)
        self._mp_thread.stage.connect(lambda s: self.lbl_online.setText(s))
        self._mp_thread.progress.connect(self._on_dl_progress)
        self._mp_thread.done.connect(self._on_mp_done)
        self._mp_thread.fail.connect(self._on_mp_fail)
        self._mp_thread.start()

    def _on_mp_done(self, name):
        self.progress.setVisible(False)
        self.btn_cancel.setEnabled(False)
        self.btn_dl.setEnabled(True)
        self.lbl_online.setText("✅ 整合包安装完成：%s" % name)
        self.refresh()
        try:
            gp = self.app.pages.get("games")
            if gp:
                for pane in gp.panes.values():
                    pane.refresh()
        except Exception:
            pass

    def _on_mp_fail(self, msg):
        self.progress.setVisible(False)
        self.btn_cancel.setEnabled(False)
        self.btn_dl.setEnabled(True)
        self.lbl_online.setText("❌ 整合包安装失败：%s" % msg)

    def _cancel_dl(self):
        if self._dl_thread:
            self._dl_thread.cancel()
            self.lbl_online.setText("正在取消…")
        if getattr(self, "_mp_thread", None):
            self._mp_thread.cancel()
            self.lbl_online.setText("正在取消安装…")


# ============================================================
# 游戏版本下载（Mojang 全量版本 + 加载器安装）
# ============================================================
class ManifestThread(QThread):
    got = pyqtSignal(dict)
    fail = pyqtSignal(str)

    def run(self):
        try:
            from game_download import fetch_manifest, classify_versions
            manifest = fetch_manifest()
            cats = classify_versions(manifest)
            self.got.emit(cats)
        except Exception as e:
            self.fail.emit(str(e))


class GameInstallThread(QThread):
    stage = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    fail = pyqtSignal(str)

    def __init__(self, loader, mc_version, mc_root, java_exe=None):
        super().__init__()
        self.loader, self.mc_version = loader, mc_version
        self.mc_root, self.java_exe = mc_root, java_exe
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _prog(self, d, t):
        self.progress.emit(d, t)

    def run(self):
        import game_download as gd
        try:
            if self.loader == "vanilla":
                self.stage.emit("下载原版核心与依赖库（BMCLAPI 国内镜像）…")
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.done.emit(self.mc_version)
            elif self.loader == "modloader":
                self.stage.emit("检查/下载原版核心 %s …" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("下载 ModLoader 并合并进 jar（远古版经典加载器）…")
                vid = gd.install_modloader(self.mc_version, self.mc_root,
                                           progress=self._prog, cancel=lambda: self._cancel)
                self.done.emit(vid)
            elif self.loader == "liteloader":
                self.stage.emit("获取 LiteLoader 版本…")
                lb = gd.liteloader_version(self.mc_version)
                if not lb:
                    raise RuntimeError("该版本没有可用的 LiteLoader")
                self.stage.emit("检查/下载原版核心 %s …" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("安装 LiteLoader %s（轻量客户端加载器）…" % lb["version"])
                vid = gd.install_liteloader(self.mc_version, self.mc_root,
                                            progress=self._prog, cancel=lambda: self._cancel)
                self.done.emit(vid)
            elif self.loader == "cleanroom":
                self.stage.emit("获取 Cleanroom 信息…")
                if self.mc_version != "1.12.2":
                    raise RuntimeError("Cleanroom 仅支持 Minecraft 1.12.2")
                self.stage.emit("检查/下载原版核心 %s …" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("安装 Cleanroom %s（Forge 现代 fork / LWJGL3）…" % gd.CLEANROOM_VERSION)
                vid = gd.install_cleanroom(self.mc_version, self.mc_root,
                                           progress=self._prog, cancel=lambda: self._cancel)
                self.done.emit(vid)
            elif self.loader == "rift":
                self.stage.emit("获取 Rift 信息…")
                if not (1, 13, 0) <= gd.version_tuple(self.mc_version) <= (1, 13, 2):
                    raise RuntimeError("Rift 仅支持 Minecraft 1.13~1.13.2")
                self.stage.emit("检查/下载原版核心 %s …" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("安装 Rift %s（1.13 轻量加载器）…" % gd.RIFT_VERSION)
                vid = gd.install_rift(self.mc_version, self.mc_root,
                                      progress=self._prog, cancel=lambda: self._cancel)
                self.done.emit(vid)
            elif self.loader == "legacyfabric":
                self.stage.emit("获取 Legacy Fabric loader 版本…")
                vers = gd.legacy_fabric_loader_versions()
                if not vers:
                    raise RuntimeError("该版本没有可用的 Legacy Fabric loader")
                self.stage.emit("检查/下载原版核心 %s …" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("安装 Legacy Fabric %s（loader %s，含老 LWJGL2 适配）…"
                                % (self.mc_version, vers[-1]))
                vid = gd.install_legacy_fabric(self.mc_version, vers[-1], self.mc_root,
                                               progress=self._prog, cancel=lambda: self._cancel)
                self.done.emit(vid)
            elif self.loader == "fabric":
                self.stage.emit("获取 Fabric loader 版本…")
                vers = gd.fabric_loader_versions(self.mc_version)
                if not vers:
                    raise RuntimeError("该版本没有可用的 Fabric loader")
                self.stage.emit("检查/下载原版核心 %s …" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("安装 Fabric %s (loader %s)…" % (self.mc_version, vers[0]))
                vid = gd.install_fabric(self.mc_version, vers[0], self.mc_root,
                                        progress=self._prog, cancel=lambda: self._cancel)
                self.done.emit(vid)
            elif self.loader == "quilt":
                self.stage.emit("获取 Quilt loader 版本…")
                vers = gd.quilt_loader_versions(self.mc_version)
                if not vers:
                    raise RuntimeError("该版本没有可用的 Quilt loader")
                self.stage.emit("检查/下载原版核心 %s …" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("安装 Quilt %s（loader %s，社区生态）…"
                                % (self.mc_version, vers[-1]))
                vid = gd.install_quilt(self.mc_version, vers[-1], self.mc_root,
                                       progress=self._prog, cancel=lambda: self._cancel)
                self.done.emit(vid)
            elif self.loader == "forge":
                self.stage.emit("获取 Forge 版本信息…")
                vers = gd.forge_versions(self.mc_version)
                if not vers:
                    raise RuntimeError("该版本没有可用的 Forge 稳定版")
                self.stage.emit("检查/下载原版核心 %s（Forge 安装器强制要求）…" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("下载 Forge 官方安装器并安装…（需要几分钟）")
                vid = gd.install_forge(self.mc_version, vers[0], self.mc_root,
                                       self.java_exe, progress=self._prog,
                                       cancel=lambda: self._cancel)
                self.done.emit(vid)
            elif self.loader == "neoforge":
                self.stage.emit("获取 NeoForge 版本信息…")
                vers = gd.neoforge_versions(self.mc_version)
                if not vers:
                    raise RuntimeError("该版本没有可用的 NeoForge")
                stable = [v for v in vers if "beta" not in v and "alpha" not in v]
                use = stable or vers
                self.stage.emit("检查/下载原版核心 %s（NeoForge 安装器强制要求）…" % self.mc_version)
                gd.download_vanilla(self.mc_version, self.mc_root,
                                    progress=self._prog, cancel=lambda: self._cancel,
                                    status=self.stage.emit)
                self.stage.emit("下载 NeoForge %s 官方安装器并安装…（需要几分钟）" % use[-1])
                vid = gd.install_neoforge(self.mc_version, use[-1], self.mc_root,
                                          self.java_exe, progress=self._prog,
                                          cancel=lambda: self._cancel)
                self.done.emit(vid)
            else:
                raise RuntimeError("未知加载器: %s" % self.loader)
        except Exception as e:
            self.fail.emit(str(e))


class LoaderDialog(QDialog):
    """下载前选择模组加载器（增强版 LOADER_DESC 文案）。"""

    def __init__(self, version_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择加载器 · %s" % version_id)
        self.setModal(True)
        self.resize(520, 440)
        self._chosen = "vanilla"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        t = QLabel("下载 %s" % version_id)
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        sub = QLabel("选择要安装的模组加载器，选好后自动下载并安装到游戏目录")
        sub.setObjectName("SideBrandSub")
        lay.addWidget(sub)
        from game_download import LOADER_DESC, loaders_for_version
        self._btns = []
        loader_defs = {
            "vanilla": ("原版 Vanilla", "🎮"),
            "modloader": ("ModLoader", "🧩"),
            "liteloader": ("LiteLoader", "💡"),
            "cleanroom": ("Cleanroom", "🧪"),
            "legacyfabric": ("Legacy Fabric", "🕸️"),
            "rift": ("Rift", "🌌"),
            "fabric": ("Fabric", "🧵"),
            "quilt": ("Quilt", "🪡"),
            "forge": ("Forge", "⚒️"),
            "neoforge": ("NeoForge", "🔥"),
        }
        for key in loaders_for_version(version_id):
            label, icon = loader_defs[key]
            card = QFrame()
            card.setObjectName("GlassCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(2)
            name = QLabel("%s  %s" % (icon, label))
            name.setObjectName("SectionTitle")
            desc = QLabel(LOADER_DESC.get(key, ""))
            desc.setObjectName("SideBrandSub")
            desc.setWordWrap(True)
            cl.addWidget(name)
            cl.addWidget(desc)
            card.setCursor(Qt.PointingHandCursor)
            card.mousePressEvent = lambda e, k=key: self._pick(k)
            self._btns.append((key, card))
            lay.addWidget(card)
        lay.addStretch(1)
        btns = QHBoxLayout()
        ok = primary_btn("下载并安装")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self.accept)
        cancel = ghost_btn("取消")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)
        self._pick("vanilla")

    def _pick(self, key):
        self._chosen = key
        for k, card in self._btns:
            card.setProperty("selected", "true" if k == key else "false")
            card.style().unpolish(card)
            card.style().polish(card)

    def chosen(self):
        return self._chosen


class GameDownloadPane(QWidget):
    """列出 Mojang 全部版本（正式版/愚人节/快照/远古版）+ 下载 + 加载器安装。"""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._cats = None
        self._current_cat = "release"
        self._man_thread = None
        self._install_thread = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        top = QHBoxLayout()
        tl = QLabel("📥 下载游戏版本")
        tl.setObjectName("SectionTitle")
        top.addWidget(tl)
        top.addStretch(1)
        top.addWidget(QLabel("分类"))
        self.cmb_cat = QComboBox()
        for key, name in (("release", "正式版"), ("april", "愚人节"), ("snapshot", "快照"), ("old", "远古版")):
            self.cmb_cat.addItem(name, key)
        self.cmb_cat.currentIndexChanged.connect(self._reload_list)
        top.addWidget(self.cmb_cat)
        top.addWidget(QLabel(""))
        self.edt_filter = QLineEdit()
        self.edt_filter.setPlaceholderText("过滤版本号…")
        self.edt_filter.setFixedWidth(160)
        self.edt_filter.textChanged.connect(self._reload_list)
        top.addWidget(self.edt_filter)
        lay.addLayout(top)
        self.lbl_status = QLabel("加载版本清单…")
        self.lbl_status.setObjectName("SideBrandSub")
        lay.addWidget(self.lbl_status)
        self.list = QListWidget()
        self.list.setObjectName("VersionList")
        lay.addWidget(self.list, 1)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        btns = QHBoxLayout()
        self.btn_dl = primary_btn("下载所选版本")
        self.btn_dl.setCursor(Qt.PointingHandCursor)
        self.btn_dl.clicked.connect(self._download)
        self.btn_cancel = ghost_btn("取消")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._cancel_install)
        self.btn_cancel.setEnabled(False)
        btns.addWidget(self.btn_dl)
        btns.addWidget(self.btn_cancel)
        btns.addStretch(1)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("SideBrandSub")
        btns.addWidget(self.lbl_progress)
        lay.addLayout(btns)
        self._load_manifest()

    def _load_manifest(self):
        self.lbl_status.setText("正在拉取 Mojang 官方版本清单…")
        self._man_thread = ManifestThread()
        self.app._track_thread(self._man_thread)
        self._man_thread.got.connect(self._on_cats)
        self._man_thread.fail.connect(lambda e: self.lbl_status.setText("拉取失败：%s" % e))
        self._man_thread.start()

    def _on_cats(self, cats):
        self._cats = cats
        total = sum(len(v) for v in cats.values())
        self.lbl_status.setText("已获取 %d 个版本（正式 %d · 愚人节 %d · 快照 %d · 远古 %d）" % (
            total, len(cats["release"]), len(cats["april"]),
            len(cats["snapshot"]), len(cats["old"])))
        self._reload_list()

    def _reload_list(self):
        self.list.clear()
        if not self._cats:
            return
        key = self.cmb_cat.currentData() or "release"
        self._current_cat = key
        flt = self.edt_filter.text().strip().lower()
        for v in self._cats.get(key, []):
            vid = v.get("id", "")
            if flt and flt not in vid.lower():
                continue
            date = (v.get("releaseTime") or "")[:10]
            item = QListWidgetItem("%s   (%s)" % (vid, date))
            item.setData(Qt.UserRole, vid)
            self.list.addItem(item)
        self.lbl_status.setText("分类 %s · 共 %d 个版本" % (
            self.cmb_cat.currentText(), self.list.count()))

    def _download(self):
        item = self.list.currentItem()
        if not item:
            QMessageBox.information(self, "KMCL", "请先在列表中选择一个版本。")
            return
        version_id = item.data(Qt.UserRole)
        dlg = LoaderDialog(version_id, self)
        dlg.exec_()
        loader = dlg.chosen()
        mc_root = self.app.mc_root()
        # 加载器安装需要 Java：优先取该版本要求的 Java，系统没有则按需下载
        java_exe = None
        try:
            from java_manager import ensure_java, required_java_major
            from game_download import fetch_manifest, manifest_url_for
            import json
            manifest = fetch_manifest()
            u = manifest_url_for(manifest, version_id)
            if u:
                import urllib.request as _ur
                req = _ur.Request(u, headers={"User-Agent": "KMCL-Community/1.0"})
                vdata = json.load(_ur.urlopen(req, timeout=20))
                req_major = required_java_major(vdata, version_id)
            else:
                req_major = 17
            java_exe = ensure_java(req_major, self.app.base_dir,
                                   progress=self.app._jdk_progress,
                                   cancel=self.app._jdk_cancel)
            self.app._jdk_done()
        except Exception:
            java_exe = None
        if loader in ("forge", "neoforge") and not java_exe:
            QMessageBox.warning(self, "KMCL", "未找到 Java，且自动下载失败，无法运行官方安装器。")
            return
        self.btn_dl.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.lbl_progress.setText("准备安装 %s（%s）…" % (version_id, loader))
        self._install_thread = GameInstallThread(loader, version_id, mc_root, java_exe)
        self.app._track_thread(self._install_thread)
        self._install_thread.stage.connect(lambda s: self.lbl_progress.setText(s))
        self._install_thread.progress.connect(self._on_prog)
        self._install_thread.done.connect(self._on_done)
        self._install_thread.fail.connect(self._on_fail)
        self._install_thread.start()

    def _on_prog(self, d, t):
        if t > 0:
            self.progress.setRange(0, t)
            self.progress.setValue(d)

    def _on_done(self, vid):
        self.progress.setVisible(False)
        self.btn_dl.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_progress.setText("✅ 安装完成：%s" % vid)
        # 通知游戏库刷新已安装版本
        try:
            self.app.config["game_version"] = vid
            self.app.save_config()
        except Exception:
            pass
        try:
            gp = self.app.pages.get("games")
            if gp:
                gp.refresh()
        except Exception:
            pass

    def _on_fail(self, msg):
        self.progress.setVisible(False)
        self.btn_dl.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_progress.setText("❌ 安装失败：%s" % msg)

    def _cancel_install(self):
        if self._install_thread:
            self._install_thread.cancel()
            self.lbl_progress.setText("正在取消…")


# ============================================================
# 游戏库（版本选定 + 模组 / 光影 / 地图 / 资源包）
# ============================================================
class GamesPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("游戏库")
        t.setObjectName("PageTitle")
        s = QLabel("选定版本，管理模组 / 光影 / 地图 / 资源包")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.btn_refresh = ghost_btn("刷新")
        self.btn_refresh.clicked.connect(self.refresh)
        head.addWidget(self.btn_refresh)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        # ---- 二级导航：游戏库 / 模组管理 / 整合包 ----
        sub_nav = QHBoxLayout()
        sub_nav.setSpacing(6)
        self._sub_btns = {}
        for key, label in (("library", "🎮  游戏库"), ("mods", "📦  模组管理"), ("modpack", "🗃  整合包")):
            b = QPushButton(label)
            b.setObjectName("SubTabBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self._show_sub(k))
            sub_nav.addWidget(b)
            self._sub_btns[key] = b
        sub_nav.addStretch(1)
        self.body_layout.addLayout(sub_nav)

        # 三个子视图容器：0=游戏库 1=模组管理 2=整合包
        self._sub = QStackedWidget()
        v0 = QWidget()
        v0l = QVBoxLayout(v0)
        v0l.setContentsMargins(0, 0, 0, 0)
        v0l.setSpacing(14)

        row = QHBoxLayout()
        row.setSpacing(14)

        # 左侧：版本列表
        vcard = glass_card()
        vl = QVBoxLayout(vcard)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(8)
        vl.addWidget(section_title("已安装版本"))
        self.list = QListWidget()
        self.list.setObjectName("VersionList")
        self.list.itemClicked.connect(self._select)
        self.list.itemDoubleClicked.connect(lambda _: self.app.goto("home"))
        vl.addWidget(self.list, 1)
        tip = QLabel("单击选定启动版本 · 双击返回首页启动")
        tip.setObjectName("SideBrandSub")
        tip.setWordWrap(True)
        vl.addWidget(tip)
        vcard.setFixedWidth(280)
        row.addWidget(vcard)

        # 右侧：资源分区（在线 Modrinth + 本地）
        self.tabs = QTabWidget()
        self.panes = {
            "mods": ResourcePane(app, "mods", "模组", "mod"),
            "shaderpacks": ResourcePane(app, "shaderpacks", "光影", "shader"),
            "datapacks": ResourcePane(app, "datapacks", "数据包", "datapack"),
            "resourcepacks": ResourcePane(app, "resourcepacks", "资源包", "resourcepack"),
            "modpacks": ResourcePane(app, "modpacks", "整合包", "modpack", install_after=True),
        }
        for key, pane in self.panes.items():
            self.tabs.addTab(pane, pane.label)
        self.dl_pane = GameDownloadPane(app)
        self.tabs.addTab(self.dl_pane, "下载游戏")
        # 懒加载：只在切到某个资源分区时才拉取该分区列表（首次），初始仅加载当前 tab
        self.tabs.currentChanged.connect(lambda i: self._ensure_pane(i))
        self._ensure_pane(self.tabs.currentIndex())
        row.addWidget(self.tabs, 1)
        v0l.addLayout(row, 1)
        self._sub.addWidget(v0)

        # 子视图：模组管理 / 整合包（原侧栏独立页并入游戏库）
        self._mods_page = ModsPage(app)
        self._sub.addWidget(self._mods_page)
        self._modpack_page = ModpackPage(app)
        self._sub.addWidget(self._modpack_page)
        self.body_layout.addWidget(self._sub, 1)
        self._show_sub("library")

    def _show_sub(self, key):
        idx = {"library": 0, "mods": 1, "modpack": 2}.get(key, 0)
        self._sub.setCurrentIndex(idx)
        for k, b in self._sub_btns.items():
            b.setChecked(k == key)
        pg = {"library": None, "mods": getattr(self, "_mods_page", None),
              "modpack": getattr(self, "_modpack_page", None)}.get(key)
        if pg is not None:
            try:
                pg.refresh()
            except Exception:
                pass

    def _ensure_pane(self, index):
        """切换资源分区时懒加载该分区列表（仅首次）；下载游戏 tab 无需加载。"""
        pane = self.tabs.widget(index) if index >= 0 else None
        if isinstance(pane, ResourcePane):
            try:
                pane.ensure_loaded()
            except Exception:
                pass

    def _select(self, item):
        v = item.text().strip()
        if v and "←" in v:
            v = v.split("←")[0].strip()
        if v:
            self.app.config["game_version"] = v
            self.app.save_config()

    def refresh(self):
        self.list.clear()
        mc = self.app.mc_root()
        try:
            from java_manager import load_version_chain, resolve_java_major
        except Exception:
            load_version_chain = None
        current = self.app.config.get("game_version", "")
        for v in scan_versions(mc):
            info = v
            if load_version_chain:
                try:
                    merged, base = load_version_chain(mc, v)
                    if base != v:
                        info += "  ← " + base
                    req = resolve_java_major(mc, v, merged, base)
                    info += "   [Java %s]" % req
                except Exception:
                    pass
            item = QListWidgetItem(info)
            item.setIcon(version_icon(self.app.base_dir, v))
            item.setData(Qt.UserRole, v)
            if v == current:
                item.setSelected(True)
            item.setToolTip("双击可在首页启动该版本")
            self.list.addItem(item)
        for pane in self.panes.values():
            # 刷新「安装到」版本下拉（装完新版本后立即出现在可选目标中）
            try:
                if hasattr(pane, "_fill_instances"):
                    pane._fill_instances()
            except Exception:
                pass
            try:
                pane.refresh()
            except Exception:
                pass
        for pg in (getattr(self, "_mods_page", None), getattr(self, "_modpack_page", None)):
            if pg is not None:
                try:
                    pg.refresh()
                except Exception:
                    pass


# ============================================================
# 联机大厅
# ============================================================
class MultiplayerPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("联机大厅")
        t.setObjectName("PageTitle")
        s = QLabel("局域网开房与加入（无需公网）")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        # 增强版联机工具（照搬自增强版，frp 内网穿透联机）
        tool_card = glass_card()
        tl = QHBoxLayout(tool_card)
        tl.setContentsMargins(24, 18, 24, 18)
        tl.setSpacing(14)
        tcol = QVBoxLayout()
        tcol.setSpacing(4)
        t1 = QLabel("KMCL 联机工具官方互通版")
        t1.setObjectName("SectionTitle")
        t2 = QLabel("基于 frp 内网穿透 · 无需公网 IP · 一键开房 / 联机码加入 · 支持加密压缩转发")
        t2.setObjectName("SideBrandSub")
        t2.setWordWrap(True)
        tcol.addWidget(t1)
        tcol.addWidget(t2)
        tl.addLayout(tcol, 1)
        self.btn_tool = primary_btn("打开联机工具")
        self.btn_tool.clicked.connect(self._open_tool)
        tl.addWidget(self.btn_tool)
        self.btn_tool_dir = ghost_btn("所在目录")
        self.btn_tool_dir.clicked.connect(self._open_tool_dir)
        tl.addWidget(self.btn_tool_dir)
        self.body_layout.addWidget(tool_card)
        self.body_layout.addSpacing(6)

        self.room = None
        self.client = None

        # 开房卡
        host_card = glass_card()
        hl = QVBoxLayout(host_card)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(12)
        hl.addWidget(section_title("创建房间（主机）"))
        hf = QGridLayout()
        hf.addWidget(QLabel("游戏端口"), 0, 0)
        self.edt_port = QLineEdit()
        hf.addWidget(self.edt_port, 0, 1)
        hf.addWidget(QLabel("主机昵称"), 1, 0)
        self.edt_host = QLineEdit()
        hf.addWidget(self.edt_host, 1, 1)
        hf.setColumnStretch(1, 1)
        hl.addLayout(hf)
        self.btn_host = primary_btn("开房")
        self.btn_host.clicked.connect(self._host)
        hl.addWidget(self.btn_host)
        self.lbl_room = QLabel("房号：—")
        self.lbl_room.setObjectName("SectionTitle")
        hl.addWidget(self.lbl_room)
        self.lbl_ip = QLabel("本机 IP：检测中…")
        self.lbl_ip.setObjectName("SideBrandSub")
        hl.addWidget(self.lbl_ip)
        self.member_list = QListWidget()
        hl.addWidget(self.member_list, 1)
        self.body_layout.addWidget(host_card, 1)

        # 加入卡
        join_card = glass_card()
        jl = QVBoxLayout(join_card)
        jl.setContentsMargins(24, 20, 24, 20)
        jl.setSpacing(12)
        jl.addWidget(section_title("加入房间（客户端）"))
        jf = QGridLayout()
        jf.addWidget(QLabel("联机码"), 0, 0)
        self.edt_code = QLineEdit()
        self.edt_code.setPlaceholderText("6 位联机码，如 A3F9K2")
        jf.addWidget(self.edt_code, 0, 1)
        jf.addWidget(QLabel("昵称"), 1, 0)
        self.edt_join = QLineEdit()
        jf.addWidget(self.edt_join, 1, 1)
        jf.setColumnStretch(1, 1)
        jl.addLayout(jf)
        self.btn_join = ghost_btn("加入房间")
        self.btn_join.clicked.connect(self._join)
        self.btn_leave = ghost_btn("离开")
        self.btn_leave.clicked.connect(self._leave)
        self.btn_leave.setEnabled(False)
        jr = QHBoxLayout()
        jr.addWidget(self.btn_join)
        jr.addWidget(self.btn_leave)
        jl.addLayout(jr)
        self.lbl_join_status = QLabel("")
        self.lbl_join_status.setObjectName("SideBrandSub")
        jl.addWidget(self.lbl_join_status)
        self.body_layout.addWidget(join_card)

        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(1500)
        self._detect_port()

    def _tool_exe(self):
        return os.path.join(self.app.base_dir, "联机工具", "Kmcl 联机工具 MC联机器.exe")

    def _open_tool(self):
        exe = self._tool_exe()
        if not os.path.exists(exe):
            QMessageBox.warning(self, "KMCL", "未找到联机工具：\n%s\n\n请确认「联机工具」文件夹已随启动器一起分发。" % exe)
            return
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe))
        except Exception as e:
            QMessageBox.warning(self, "KMCL", "启动联机工具失败：%s" % e)

    def _open_tool_dir(self):
        d = os.path.join(self.app.base_dir, "联机工具")
        if os.path.isdir(d):
            try:
                os.startfile(d)
            except Exception:
                pass

    def _detect_port(self):
        try:
            from multiplayer_manager import detect_lan_port, get_lan_ip
            port = detect_lan_port(self.app.mc_root())
            self.edt_port.setText(str(port or 25565))
            self.lbl_ip.setText("本机 IP：%s" % get_lan_ip())
        except Exception as e:
            self.edt_port.setText("25565")
            self.lbl_ip.setText("本机 IP：— (%s)" % e)

    def _host(self):
        from multiplayer_manager import HostRoom, gen_room_code, get_lan_ip
        try:
            port = int(self.edt_port.text().strip() or 25565)
        except ValueError:
            port = 25565
        name = self.edt_host.text().strip() or self.app.config.get("player_name", "Host")
        if self.room and self.room.running:
            self.room.stop()
        self.room = HostRoom()
        try:
            code = gen_room_code()
            self.room.start(port, name, code=code)
        except OSError as e:
            QMessageBox.warning(self, "KMCL", "端口 %d 被占用或不可用：%s" % (port, e))
            return
        self.lbl_room.setText("房号：%s   端口：%d" % (code, port))
        self._tick()

    def _join(self):
        from multiplayer_manager import find_room, RoomClient
        code = self.edt_code.text().strip().upper()
        name = self.edt_join.text().strip() or self.app.config.get("player_name", "Player")
        if not code:
            QMessageBox.warning(self, "KMCL", "请输入联机码。")
            return
        room = find_room(code, timeout=3.0)
        if not room:
            self.lbl_join_status.setText("未找到房间 %s，请确认主机在同一局域网且已开房。" % code)
            return
        self.client = RoomClient()
        self.client.connect(room, name)
        self.btn_join.setEnabled(False)
        self.btn_leave.setEnabled(True)
        self.lbl_join_status.setText("已连接房间 %s（%s）" % (code, room.get("host_name", "?")))

    def _leave(self):
        if self.client:
            try:
                self.client.leave()
            except Exception:
                pass
            self.client = None
        self.btn_join.setEnabled(True)
        self.btn_leave.setEnabled(False)
        self.lbl_join_status.setText("已离开房间")

    def _tick(self):
        if self.room and self.room.running:
            members = self.room.members() or []
            self.member_list.clear()
            for m in members:
                self.member_list.addItem("%s  (%s)" % (m.get("name", "?"), m.get("ip", "?")))
            self.btn_host.setText("停止开房")
        else:
            self.btn_host.setText("开房")

    def refresh(self):
        self._detect_port()


# ============================================================
# 游戏修复
# ============================================================
class RepairPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("游戏修复")
        t.setObjectName("PageTitle")
        s = QLabel("校验并补全缺失的游戏文件（官方源 + BMCLAPI 镜像）")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        card = glass_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(12)
        cl.addWidget(section_title("选择要修复的版本"))
        row = QHBoxLayout()
        self.cmb_version = QComboBox()
        row.addWidget(self.cmb_version, 1)
        self.btn_repair = primary_btn("开始修复")
        self.btn_repair.clicked.connect(self._repair)
        row.addWidget(self.btn_repair)
        cl.addLayout(row)
        self.lbl_tasks = QLabel("尚未收集任务")
        self.lbl_tasks.setObjectName("SideBrandSub")
        cl.addWidget(self.lbl_tasks)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        cl.addWidget(self.progress)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1500)
        cl.addWidget(self.log_view, 1)
        self.body_layout.addWidget(card, 1)
        self.tasks = []
        self.thread = None

    def refresh(self):
        self.cmb_version.clear()
        for v in scan_versions(self.app.mc_root()):
            self.cmb_version.addItem(version_icon(self.app.base_dir, v), v)
        # 打开页面即默认收集任务，状态栏直接显示待校验文件数
        self._collect()

    def _collect(self):
        """收集选中版本的修复任务。成功且有任务返回 True；失败/无版本返回 False 并给出提示。
        无论成败都不禁用「开始修复」按钮——点击时会重新收集，避免出现"点不动"。"""
        vid = self.cmb_version.currentText()
        if not vid:
            self.lbl_tasks.setText("⚠ 当前无任何版本，请先在游戏库安装游戏版本")
            self.log_view.appendPlainText("无可用版本，无法收集任务")
            self.tasks = []
            return False
        try:
            from repair_game import collect_tasks
            tasks, natives, _ = collect_tasks(vid, self.app.mc_root())
        except Exception as e:
            self.tasks = []
            self.lbl_tasks.setText("收集任务失败：%s" % str(e)[:120])
            self.log_view.appendPlainText("收集任务失败（%s）：%s" % (vid, e))
            return False
        self.tasks = list(tasks) + list(natives or [])
        self.lbl_tasks.setText("%s：共 %d 个文件待校验/下载" % (vid, len(self.tasks)))
        self.log_view.appendPlainText("收集到 %d 个任务（%s）" % (len(self.tasks), vid))
        return len(self.tasks) > 0

    def _repair(self):
        # 点「开始修复」自动收集：无需先点「收集任务」，没有任务时直接提示原因
        if not self.tasks and not self._collect():
            QMessageBox.warning(self, "KMCL",
                                "未能开始修复：没有可修复的任务。\n\n"
                                "可能原因：\n"
                                "· 版本下拉框为空 —— 请先到「游戏库」安装游戏版本\n"
                                "· 收集任务失败 —— 详情见下方日志")
            return
        self.btn_repair.setEnabled(False)
        self.progress.setRange(0, len(self.tasks))
        self.progress.setValue(0)
        self.thread = RepairThread(self.tasks, self.app.base_dir)
        self.app._track_thread(self.thread)
        self.thread.progress.connect(lambda i, n, msg: (self.progress.setValue(i), msg and self.log_view.appendPlainText(msg)))
        self.thread.done.connect(lambda s: (self.log_view.appendPlainText(s), self.btn_repair.setEnabled(True)))
        self.thread.start()


# ============================================================
# 百宝箱
# ============================================================
class ToolboxPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("百宝箱")
        t.setObjectName("PageTitle")
        s = QLabel("常用工具与启动器增强功能")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        cols = QHBoxLayout()
        cols.setSpacing(16)

        # ---- 左列 ----
        left = QVBoxLayout()
        left.setSpacing(16)

        c1 = glass_card()
        l1 = QVBoxLayout(c1)
        l1.setContentsMargins(24, 20, 24, 20)
        l1.setSpacing(10)
        l1.addWidget(section_title("⚡ 自动内存优化"))
        self.chk_mem = QCheckBox("启动游戏时自动按物理内存优化堆内存")
        self.chk_mem.setObjectName("ToolboxCheck")
        self.chk_mem.toggled.connect(self._toggle_mem)
        row_mem = QHBoxLayout()
        row_mem.addWidget(self.chk_mem)
        self.app._attach_memory(self.chk_mem, "auto_memory", row_mem,
                            is_on=lambda: self.chk_mem.isChecked())
        l1.addLayout(row_mem)
        self.lbl_mem = QLabel("当前建议堆内存：%d MB" % auto_heap_mb())
        self.lbl_mem.setObjectName("SideBrandSub")
        self.lbl_mem.setWordWrap(True)
        l1.addWidget(self.lbl_mem)
        row1 = QHBoxLayout()
        self.btn_optimize = primary_btn("一键优化")
        self.btn_optimize.clicked.connect(self._optimize)
        row1.addWidget(self.btn_optimize)
        self.app._attach_memory(self.btn_optimize, "perf_optimize", row1)
        self.lbl_opt = QLabel("")
        self.lbl_opt.setObjectName("SideBrandSub")
        self.lbl_opt.setWordWrap(True)
        row1.addWidget(self.lbl_opt, 1)
        l1.addLayout(row1)
        l1.addWidget(QLabel("提示：固态硬盘可尝试；机械硬盘可能导致读写变慢，不建议尝试"))
        left.addWidget(c1)

        c2 = glass_card()
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(24, 20, 24, 20)
        l2.setSpacing(10)
        l2.addWidget(section_title("🧹 清理游戏垃圾与缓存"))
        l2.addWidget(QLabel("清理日志、崩溃报告、临时文件与下载残留（不影响存档与模组）"))
        row = QHBoxLayout()
        self.btn_clean = ghost_btn("一键清理")
        self.btn_clean.clicked.connect(self._clean)
        row.addWidget(self.btn_clean)
        self.app._attach_memory(self.btn_clean, "clean_junk", row)
        self.lbl_clean = QLabel("")
        self.lbl_clean.setObjectName("SideBrandSub")
        row.addWidget(self.lbl_clean, 1)
        l2.addLayout(row)
        left.addWidget(c2)

        c3 = glass_card()
        l3 = QVBoxLayout(c3)
        l3.setContentsMargins(24, 20, 24, 20)
        l3.setSpacing(10)
        l3.addWidget(section_title("☕ Java 运行时（系统优先 · 按需下载）"))
        self.lbl_javas = QLabel("检测中…")
        self.lbl_javas.setObjectName("SideBrandSub")
        self.lbl_javas.setWordWrap(True)
        l3.addWidget(self.lbl_javas)
        left.addWidget(c3)

        cols.addLayout(left, 1)

        # ---- 右列 ----
        right = QVBoxLayout()
        right.setSpacing(16)

        c4 = glass_card()
        l4 = QVBoxLayout(c4)
        l4.setContentsMargins(24, 20, 24, 20)
        l4.setSpacing(10)
        l4.addWidget(section_title("⬇ 自定义文件下载"))
        l4.addWidget(QLabel("使用内置下载引擎下载任意文件（网盘类站点可能受限）"))
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        form.addWidget(QLabel("下载地址"), 0, 0)
        self.edt_url = QLineEdit()
        self.edt_url.setPlaceholderText("https://…")
        form.addWidget(self.edt_url, 0, 1)
        form.addWidget(QLabel("保存目录"), 1, 0)
        self.edt_dir = QLineEdit(os.path.join(app.mc_root(), "downloads"))
        form.addWidget(self.edt_dir, 1, 1)
        form.addWidget(QLabel("文件名"), 2, 0)
        self.edt_fn = QLineEdit()
        self.edt_fn.setPlaceholderText("留空则按服务器文件名")
        form.addWidget(self.edt_fn, 2, 1)
        form.setColumnStretch(1, 1)
        l4.addLayout(form)
        row4 = QHBoxLayout()
        self.btn_dl = primary_btn("开始下载")
        self.btn_dl.clicked.connect(self._download)
        row4.addWidget(self.btn_dl)
        self.app._attach_memory(self.btn_dl, "tool_download", row4)
        self.progress_dl = QProgressBar()
        self.progress_dl.setValue(0)
        row4.addWidget(self.progress_dl, 1)
        l4.addLayout(row4)
        self.lbl_dl = QLabel("")
        self.lbl_dl.setObjectName("SideBrandSub")
        l4.addWidget(self.lbl_dl)
        right.addWidget(c4)

        c5 = glass_card()
        l5 = QVBoxLayout(c5)
        l5.setContentsMargins(24, 20, 24, 20)
        l5.setSpacing(10)
        l5.addWidget(section_title("🔍 诊断信息"))
        l5.addWidget(QLabel("收集系统 Java 与已装版本信息，方便排查问题时粘贴给开发者"))
        row5 = QHBoxLayout()
        self.btn_diag = ghost_btn("复制诊断信息")
        self.btn_diag.clicked.connect(self._diag)
        row5.addWidget(self.btn_diag)
        self.app._attach_memory(self.btn_diag, "diag_copy", row5)
        self.lbl_diag = QLabel("")
        self.lbl_diag.setObjectName("SideBrandSub")
        row5.addWidget(self.lbl_diag, 1)
        l5.addLayout(row5)
        right.addWidget(c5)

        c6 = glass_card()
        l6 = QVBoxLayout(c6)
        l6.setContentsMargins(24, 20, 24, 20)
        l6.setSpacing(10)
        l6.addWidget(section_title("🧾 JVM 参数模板"))
        self.edt_jvm = QPlainTextEdit()
        self.edt_jvm.setReadOnly(True)
        self.edt_jvm.setPlainText(
            "-Xmx4G                    最大堆内存（按需改 2G/6G/8G）\n"
            "-Xms1G                    初始堆内存\n"
            "-XX:+UseG1GC              使用 G1 垃圾回收器（推荐）\n"
            "-XX:MaxGCPauseMillis=50   降低 GC 停顿\n"
            "-Dfile.encoding=UTF-8     中文文件不乱码")
        l6.addWidget(self.edt_jvm)
        row6 = QHBoxLayout()
        self.btn_jvm = ghost_btn("复制模板")
        self.btn_jvm.clicked.connect(self._copy_jvm)
        row6.addWidget(self.btn_jvm)
        self.app._attach_memory(self.btn_jvm, "jvm_copy", row6)
        self.lbl_jvm = QLabel("")
        self.lbl_jvm.setObjectName("SideBrandSub")
        row6.addWidget(self.lbl_jvm, 1)
        l6.addLayout(row6)
        right.addWidget(c6)

        cols.addLayout(right, 1)
        self.body_layout.addLayout(cols)

        # ---- 第二行：玩家实用工具 ----
        cols2 = QHBoxLayout()
        cols2.setSpacing(16)
        left2 = QVBoxLayout()
        left2.setSpacing(16)
        right2 = QVBoxLayout()
        right2.setSpacing(16)

        # 📂 快捷打开常用文件夹
        c7 = glass_card()
        l7 = QVBoxLayout(c7)
        l7.setContentsMargins(24, 20, 24, 20)
        l7.setSpacing(10)
        l7.addWidget(section_title("📂 快捷打开常用文件夹"))
        l7.addWidget(QLabel("一键打开游戏目录下的常用文件夹（不存在会自动创建）"))
        for label, path in quick_dirs(self.app.mc_root()).items():
            rowq = QHBoxLayout()
            rowq.setSpacing(10)
            b = ghost_btn(label)
            b.clicked.connect(lambda _=False, p=path: self._open_dir(p))
            rowq.addWidget(b)
            self.app._attach_memory(b, "open_dir:" + label, rowq)
            rowq.addStretch(1)
            l7.addLayout(rowq)
        left2.addWidget(c7)

        # 💾 世界存档备份与恢复
        c8 = glass_card()
        l8 = QVBoxLayout(c8)
        l8.setContentsMargins(24, 20, 24, 20)
        l8.setSpacing(10)
        l8.addWidget(section_title("💾 世界存档备份与恢复"))
        l8.addWidget(QLabel("把全部世界存档打包为 zip 防止坏档，可一键恢复历史备份"))
        row8 = QHBoxLayout()
        self.btn_backup = primary_btn("立即备份")
        self.btn_backup.clicked.connect(self._backup)
        self.btn_restore = ghost_btn("从备份恢复")
        self.btn_restore.clicked.connect(self._restore)
        row8.addWidget(self.btn_backup)
        self.app._attach_memory(self.btn_backup, "backup_worlds", row8)
        row8.addWidget(self.btn_restore)
        self.app._attach_memory(self.btn_restore, "restore_worlds", row8)
        l8.addLayout(row8)
        self.lbl_backup = QLabel("")
        self.lbl_backup.setObjectName("SideBrandSub")
        self.lbl_backup.setWordWrap(True)
        l8.addWidget(self.lbl_backup)
        left2.addWidget(c8)

        # 🩺 版本完整性校验
        c9 = glass_card()
        l9 = QVBoxLayout(c9)
        l9.setContentsMargins(24, 20, 24, 20)
        l9.setSpacing(10)
        l9.addWidget(section_title("🩺 版本完整性校验"))
        l9.addWidget(QLabel("检查已安装版本的核心文件是否齐全，快速定位启动失败原因"))
        row9 = QHBoxLayout()
        self.btn_checkv = ghost_btn("开始校验")
        self.btn_checkv.clicked.connect(self._check_versions)
        row9.addWidget(self.btn_checkv)
        self.app._attach_memory(self.btn_checkv, "check_versions", row9)
        self.lbl_checkv = QLabel("")
        self.lbl_checkv.setObjectName("SideBrandSub")
        self.lbl_checkv.setWordWrap(True)
        row9.addWidget(self.lbl_checkv, 1)
        l9.addLayout(row9)
        left2.addWidget(c9)

        # 📊 游玩统计
        c10 = glass_card()
        l10 = QVBoxLayout(c10)
        l10.setContentsMargins(24, 20, 24, 20)
        l10.setSpacing(10)
        l10.addWidget(section_title("📊 游玩统计"))
        self.lbl_play = QLabel("")
        self.lbl_play.setObjectName("SideBrandSub")
        self.lbl_play.setWordWrap(True)
        l10.addWidget(self.lbl_play)
        row10 = QHBoxLayout()
        self.btn_play_reset = ghost_btn("重置统计")
        self.btn_play_reset.clicked.connect(self._reset_play)
        row10.addWidget(self.btn_play_reset)
        self.app._attach_memory(self.btn_play_reset, "reset_play", row10)
        l10.addLayout(row10)
        right2.addWidget(c10)

        # 🧩 模组快速管理
        c11 = glass_card()
        l11 = QVBoxLayout(c11)
        l11.setContentsMargins(24, 20, 24, 20)
        l11.setSpacing(10)
        l11.addWidget(section_title("🧩 模组快速管理"))
        row_modver = QHBoxLayout()
        row_modver.addWidget(QLabel("版本"))
        self.cmb_modver = QComboBox()
        self.cmb_modver.setCursor(Qt.PointingHandCursor)
        self.cmb_modver.currentIndexChanged.connect(lambda _: self._update_mods())
        row_modver.addWidget(self.cmb_modver, 1)
        l11.addLayout(row_modver)
        self.lbl_mods = QLabel("")
        self.lbl_mods.setObjectName("SideBrandSub")
        self.lbl_mods.setWordWrap(True)
        l11.addWidget(self.lbl_mods)
        row11 = QHBoxLayout()
        self.btn_mods_on = ghost_btn("全部启用")
        self.btn_mods_on.clicked.connect(lambda: self._toggle_mods(True))
        self.btn_mods_off = ghost_btn("全部禁用")
        self.btn_mods_off.clicked.connect(lambda: self._toggle_mods(False))
        row11.addWidget(self.btn_mods_on)
        self.app._attach_memory(self.btn_mods_on, "mods_all_on", row11)
        row11.addWidget(self.btn_mods_off)
        self.app._attach_memory(self.btn_mods_off, "mods_all_off", row11)
        l11.addLayout(row11)
        right2.addWidget(c11)

        # 🚫 残留 Java 进程清理
        c12 = glass_card()
        l12 = QVBoxLayout(c12)
        l12.setContentsMargins(24, 20, 24, 20)
        l12.setSpacing(10)
        l12.addWidget(section_title("🚫 残留 Java 进程清理"))
        l12.addWidget(QLabel("游戏异常退出后清理残留 javaw 进程（其它正在运行的 Java 程序也会被结束，慎用）"))
        row12 = QHBoxLayout()
        self.btn_kill = ghost_btn("清理残留进程")
        self.btn_kill.clicked.connect(self._kill_java)
        row12.addWidget(self.btn_kill)
        self.app._attach_memory(self.btn_kill, "kill_java", row12)
        self.lbl_kill = QLabel("")
        self.lbl_kill.setObjectName("SideBrandSub")
        row12.addWidget(self.lbl_kill, 1)
        l12.addLayout(row12)
        right2.addWidget(c12)

        cols2.addLayout(left2, 1)
        cols2.addLayout(right2, 1)
        self.body_layout.addLayout(cols2)

        # ---- 第三行：老电脑优化专区 ----
        cols3 = QHBoxLayout()
        cols3.setSpacing(16)
        left3 = QVBoxLayout()
        left3.setSpacing(16)
        right3 = QVBoxLayout()
        right3.setSpacing(16)

        # 🖥 实时性能监控
        c13 = glass_card()
        l13 = QVBoxLayout(c13)
        l13.setContentsMargins(24, 20, 24, 20)
        l13.setSpacing(10)
        l13.addWidget(section_title("🖥 实时性能监控"))
        self.lbl_mon = QLabel("采样中…")
        self.lbl_mon.setObjectName("SideBrandSub")
        self.lbl_mon.setWordWrap(True)
        l13.addWidget(self.lbl_mon)
        left3.addWidget(c13)

        # 🗜 空间占用扫描
        c15 = glass_card()
        l15 = QVBoxLayout(c15)
        l15.setContentsMargins(24, 20, 24, 20)
        l15.setSpacing(10)
        l15.addWidget(section_title("🗜 空间占用扫描"))
        l15.addWidget(QLabel("扫描游戏目录，找出最占磁盘的大户（老电脑磁盘告急必备）"))
        row15 = QHBoxLayout()
        self.btn_scan = ghost_btn("开始扫描")
        self.btn_scan.clicked.connect(self._scan_space)
        row15.addWidget(self.btn_scan)
        self.app._attach_memory(self.btn_scan, "scan_space", row15)
        self.lbl_scan = QLabel("")
        self.lbl_scan.setObjectName("SideBrandSub")
        self.lbl_scan.setWordWrap(True)
        row15.addWidget(self.lbl_scan, 1)
        l15.addLayout(row15)
        left3.addWidget(c15)

        # 🧹 系统内存清理
        c16 = glass_card()
        l16 = QVBoxLayout(c16)
        l16.setContentsMargins(24, 20, 24, 20)
        l16.setSpacing(10)
        l16.addWidget(section_title("🧹 系统内存急救"))
        l16.addWidget(QLabel("清理全部进程的工作集，立即释放内存（老电脑开游戏前救急；所有程序可能短暂卡顿）"))
        row16 = QHBoxLayout()
        self.btn_mem = ghost_btn("立即清理内存")
        self.btn_mem.clicked.connect(self._clear_mem)
        row16.addWidget(self.btn_mem)
        self.app._attach_memory(self.btn_mem, "clear_mem", row16)
        self.lbl_mem2 = QLabel("")
        self.lbl_mem2.setObjectName("SideBrandSub")
        row16.addWidget(self.lbl_mem2, 1)
        l16.addLayout(row16)
        right3.addWidget(c16)

        # 🚀 启动前自动优化
        c17 = glass_card()
        l17 = QVBoxLayout(c17)
        l17.setContentsMargins(24, 20, 24, 20)
        l17.setSpacing(10)
        l17.addWidget(section_title("🚀 启动前自动优化"))
        self.chk_pre_mem = QCheckBox("每次启动游戏前自动清理系统内存")
        self.chk_pre_mem.setObjectName("ToolboxCheck")
        self.chk_pre_mem.toggled.connect(self._toggle_pre_mem)
        row_pre = QHBoxLayout()
        row_pre.addWidget(self.chk_pre_mem)
        self.app._attach_memory(self.chk_pre_mem, "prelaunch_mem", row_pre,
                            is_on=lambda: self.chk_pre_mem.isChecked())
        l17.addLayout(row_pre)
        row17 = QHBoxLayout()
        self.edt_pre_kill = QLineEdit()
        self.edt_pre_kill.setPlaceholderText("启动前自动结束的进程，如: chrome.exe, qq.exe")
        row17.addWidget(self.edt_pre_kill, 1)
        self.btn_pre_kill = ghost_btn("保存名单")
        self.btn_pre_kill.clicked.connect(self._save_pre_kill)
        row17.addWidget(self.btn_pre_kill)
        self.app._attach_memory(self.btn_pre_kill, "pre_kill_save", row17)
        l17.addLayout(row17)
        self.lbl_pre = QLabel("")
        self.lbl_pre.setObjectName("SideBrandSub")
        self.lbl_pre.setWordWrap(True)
        l17.addWidget(self.lbl_pre)
        right3.addWidget(c17)

        # 📉 GC 日志诊断 + 🧠 视频设置建议
        c18 = glass_card()
        l18 = QVBoxLayout(c18)
        l18.setContentsMargins(24, 20, 24, 20)
        l18.setSpacing(10)
        l18.addWidget(section_title("📉 GC 日志诊断"))
        self.chk_gc = QCheckBox("启动时记录 GC 日志（定位内存卡顿，日志存 logs/gc*.log）")
        self.chk_gc.setObjectName("ToolboxCheck")
        self.chk_gc.toggled.connect(self._toggle_gc)
        row_gc = QHBoxLayout()
        row_gc.addWidget(self.chk_gc)
        self.app._attach_memory(self.chk_gc, "gc_log", row_gc,
                            is_on=lambda: self.chk_gc.isChecked())
        l18.addLayout(row_gc)
        l18.addWidget(section_title("🧠 视频设置建议"))
        self.lbl_video = QLabel("")
        self.lbl_video.setObjectName("SideBrandSub")
        self.lbl_video.setWordWrap(True)
        l18.addWidget(self.lbl_video)
        row18 = QHBoxLayout()
        self.btn_video = ghost_btn("复制建议")
        self.btn_video.clicked.connect(self._copy_video)
        row18.addWidget(self.btn_video)
        self.app._attach_memory(self.btn_video, "video_copy", row18)
        l18.addLayout(row18)
        right3.addWidget(c18)

        cols3.addLayout(left3, 1)
        cols3.addLayout(right3, 1)
        self.body_layout.addLayout(cols3)

        danger = glass_card()
        dl = QVBoxLayout(danger)
        dl.setContentsMargins(24, 20, 24, 20)
        dl.setSpacing(10)
        dl.addWidget(section_title("🗑 一键删除所有游戏资料"))
        dl.addWidget(QLabel("将永久删除游戏目录下的全部内容：所有版本、世界存档、模组、光影、资源包、数据包、日志等，不可恢复！"))
        rowd = QHBoxLayout()
        self.btn_delall = QPushButton("⚠ 删除所有游戏资料（不可撤回）")
        self.btn_delall.setCursor(Qt.PointingHandCursor)
        self.btn_delall.setStyleSheet(
            "color:#ff6b6b; background:rgba(255,80,80,0.12); border:1px solid #ff6b6b;"
            "border-radius:10px; padding:9px 18px; font-weight:600;")
        self.btn_delall.clicked.connect(self._del_all)
        rowd.addWidget(self.btn_delall)
        self.app._attach_memory(self.btn_delall, "del_all", rowd)
        self.progress_del = QProgressBar()
        self.progress_del.setValue(0)
        self.progress_del.setVisible(False)
        rowd.addWidget(self.progress_del, 1)
        dl.addLayout(rowd)
        self.lbl_del = QLabel("")
        self.lbl_del.setObjectName("SideBrandSub")
        dl.addWidget(self.lbl_del)
        self.body_layout.addWidget(danger)
        # ---- 实用工具箱（网络 / 系统 / 日常） ----
        extra = glass_card()
        el = QVBoxLayout(extra)
        el.setContentsMargins(24, 20, 24, 20)
        el.setSpacing(12)
        el.addWidget(section_title("🧰 实用工具箱"))
        row = QHBoxLayout()
        self.btn_speed = primary_btn("🌐 网络测速")
        self.btn_speed.clicked.connect(self._net_speed)
        row.addWidget(self.btn_speed)
        self.app._attach_memory(self.btn_speed, "net_speed", row)
        self.lbl_speed = QLabel("测速三个常用源：BMCLAPI / Mojang / GitHub")
        self.lbl_speed.setObjectName("SideBrandSub")
        self.lbl_speed.setWordWrap(True)
        row.addWidget(self.lbl_speed, 1)
        el.addLayout(row)
        row = QHBoxLayout()
        self.btn_clip = ghost_btn("📋 剪贴板")
        self.btn_clip.clicked.connect(self._clipboard)
        row.addWidget(self.btn_clip)
        self.app._attach_memory(self.btn_clip, "clipboard", row)
        self.btn_sysinfo = ghost_btn("💻 系统信息")
        self.btn_sysinfo.clicked.connect(self._sysinfo)
        row.addWidget(self.btn_sysinfo)
        self.app._attach_memory(self.btn_sysinfo, "sysinfo", row)
        self.btn_power = ghost_btn("🔄 电源计划")
        self.btn_power.clicked.connect(self._power)
        row.addWidget(self.btn_power)
        self.app._attach_memory(self.btn_power, "power_plan", row)
        self.btn_uptime = ghost_btn("⏱ 运行时长")
        self.btn_uptime.clicked.connect(self._uptime)
        row.addWidget(self.btn_uptime)
        self.app._attach_memory(self.btn_uptime, "uptime", row)
        el.addLayout(row)
        row = QHBoxLayout()
        self.btn_crash = ghost_btn("📄 崩溃报告")
        self.btn_crash.clicked.connect(self._crash_reports)
        row.addWidget(self.btn_crash)
        self.app._attach_memory(self.btn_crash, "crash_reports", row)
        self.btn_dns = ghost_btn("⚡ 刷新 DNS")
        self.btn_dns.clicked.connect(self._flush_dns)
        row.addWidget(self.btn_dns)
        self.app._attach_memory(self.btn_dns, "flush_dns", row)
        self.btn_tmp = ghost_btn("🗑 清理临时文件")
        self.btn_tmp.clicked.connect(self._clean_temp)
        row.addWidget(self.btn_tmp)
        self.app._attach_memory(self.btn_tmp, "clean_temp", row)
        self.btn_shot = ghost_btn("📸 全屏截图")
        self.btn_shot.clicked.connect(self._screenshot)
        row.addWidget(self.btn_shot)
        self.app._attach_memory(self.btn_shot, "screenshot", row)
        self.btn_jtest = ghost_btn("🧪 Java 自测")
        self.btn_jtest.clicked.connect(self._java_test)
        row.addWidget(self.btn_jtest)
        self.app._attach_memory(self.btn_jtest, "java_test", row)
        el.addLayout(row)
        self.lbl_extra = QLabel("")
        self.lbl_extra.setObjectName("SideBrandSub")
        self.lbl_extra.setWordWrap(True)
        el.addWidget(self.lbl_extra)
        self.body_layout.addWidget(extra)
        self.body_layout.addStretch(1)
        self.dl_thread = None
        self.del_thread = None
        self.backup_thread = None
        self.restore_thread = None
        self.scan_thread = None
        self._last_cpu = None
        self._mon_timer = QTimer(self)
        self._mon_timer.timeout.connect(self._tick_monitor)
        self._mon_timer.start(2000)

    def refresh(self):
        self.chk_mem.setChecked(bool(self.app.config.get("auto_memory", False)))
        self.lbl_mem.setText("当前建议堆内存：%d MB" % auto_heap_mb())
        javas = self.app.detect_javas()
        if javas:
            self.lbl_javas.setText("检测到 %d 套可用 Java（缺失时自动下载）：\n%s" % (
                len(javas), "\n".join("  Java %s" % k for k in sorted(javas))))
        else:
            self.lbl_javas.setText("未检测到系统 Java，启动时将自动下载所需版本")
        self._update_play()
        # 模组快捷区版本下拉（强制版本隔离）：列出全部已安装版本
        cur = self.cmb_modver.currentData() or ""
        self.cmb_modver.blockSignals(True)
        self.cmb_modver.clear()
        for vid in scan_versions(self.app.mc_root()):
            self.cmb_modver.addItem(version_icon(self.app.base_dir, vid), vid, vid)
        if cur:
            idx = self.cmb_modver.findData(cur)
            if idx >= 0:
                self.cmb_modver.setCurrentIndex(idx)
        self.cmb_modver.blockSignals(False)
        self._update_mods()
        self.chk_pre_mem.setChecked(bool(self.app.config.get("prelaunch_mem", False)))
        self.chk_gc.setChecked(bool(self.app.config.get("gc_log", False)))
        kill = self.app.config.get("prelaunch_kill") or []
        self.edt_pre_kill.setText(", ".join(kill))
        self.lbl_pre.setText("当前启动前自动结束：%s" % ("无" if not kill else ", ".join(kill)))
        self.lbl_video.setText(video_settings_advice())
        self._tick_monitor()

    def _toggle_mem(self, on):
        self.app.config["auto_memory"] = bool(on)
        self.app.save_config()

    def _optimize(self):
        ssd = detect_ssd()
        if ssd is False:
            self.lbl_opt.setText("检测到机械硬盘，不建议一键优化（可能造成读写变慢），已跳过。")
            return
        mem = auto_heap_mb()
        args = perf_jvm_args(mem)
        self.app.config["perf_optimized"] = True
        self.app.config["perf_jvm_args"] = args
        self.app.config["auto_memory"] = True
        self.app.save_config()
        self.chk_mem.setChecked(True)
        disk = "固态硬盘" if ssd else "未知硬盘类型"
        self.lbl_opt.setText("优化完成（%s）：已启用 G1GC 等性能参数，推荐堆内存 %d MB" % (disk, mem))

    def _clean(self):
        removed, freed = clean_mc_junk(self.app.mc_root())
        self.lbl_clean.setText("已清理 %d 个文件，释放 %.1f MB" % (removed, freed / 1048576.0))
        self.btn_clean.setEnabled(False)
        QTimer.singleShot(2500, lambda: self.btn_clean.setEnabled(True))

    def _download(self):
        url = self.edt_url.text().strip()
        if not url:
            self.lbl_dl.setText("请填写下载地址")
            return
        ddir = self.edt_dir.text().strip() or os.path.join(self.app.mc_root(), "downloads")
        fname = self.edt_fn.text().strip()
        if not fname:
            fname = os.path.basename(url.split("?")[0]) or "download.bin"
        dest = os.path.join(ddir, fname)
        self.progress_dl.setValue(0)
        self.btn_dl.setEnabled(False)
        self.dl_thread = ToolboxDownloadThread(url, dest)
        self.app._track_thread(self.dl_thread)
        self.dl_thread.progress.connect(lambda d, t: self.progress_dl.setValue(
            int(d * 100 / t) if t else 0))
        self.dl_thread.done.connect(lambda p: (self.lbl_dl.setText("已保存: %s" % p),
                                               self.btn_dl.setEnabled(True)))
        self.dl_thread.failed.connect(lambda e: (self.lbl_dl.setText("下载失败: %s" % e),
                                                 self.btn_dl.setEnabled(True)))
        self.dl_thread.start()

    def _diag(self):
        txt = collect_diag(self.app)
        QApplication.clipboard().setText(txt)
        self.lbl_diag.setText("已复制到剪贴板（%d 行）" % len(txt.splitlines()))

    def _copy_jvm(self):
        QApplication.clipboard().setText(self.edt_jvm.toPlainText())
        self.lbl_jvm.setText("已复制")
        QTimer.singleShot(2000, lambda: self.lbl_jvm.setText(""))

    def _del_all(self):
        mc = self.app.mc_root()
        if not os.path.isdir(mc):
            self.lbl_del.setText("游戏目录不存在：%s" % mc)
            return
        cnt = sum(1 for _ in os.scandir(mc))
        text, ok = QInputDialog.getText(
            self, "危险操作",
            "将永久删除游戏目录下的全部内容（共 %d 个项目）：\n%s\n\n"
            "此操作不可恢复！请输入「删除」以确认：" % (cnt, mc))
        if not ok or text.strip() != "删除":
            self.lbl_del.setText("已取消（需输入「删除」确认）")
            return
        self.progress_del.setVisible(True)
        self.progress_del.setRange(0, cnt or 1)
        self.btn_delall.setEnabled(False)
        self.del_thread = DeleteAllThread(mc)
        self.app._track_thread(self.del_thread)
        self.del_thread.progress.connect(
            lambda i, n, name: (self.progress_del.setValue(i), self.lbl_del.setText("删除中: %s" % name)))
        self.del_thread.done.connect(
            lambda s: (self.lbl_del.setText(s), self.progress_del.setVisible(False),
                       self.btn_delall.setEnabled(True)))
        self.del_thread.start()

    # ---- 实用工具箱（网络 / 系统 / 日常） ----
    def _net_speed(self):
        import urllib.request as _ur
        def worker():
            results = []
            for name, url in (("BMCLAPI", "https://bmclapi2.bangbang93.com/"),
                              ("Mojang", "https://piston-meta.mojang.com/"),
                              ("GitHub", "https://github.com/")):
                try:
                    t0 = time.time()
                    req = _ur.Request(url, headers={"User-Agent": "KMCL/1.0"})
                    with _ur.urlopen(req, timeout=8) as r:
                        r.read(65536)
                    dt = time.time() - t0
                    results.append("%s %dms" % (name, int(dt * 1000)))
                except Exception:
                    results.append("%s 失败" % name)
            self.lbl_extra.setText("测速结果：" + " | ".join(results))
        self.lbl_extra.setText("测速中…（约 3-8 秒）")
        threading.Thread(target=worker, daemon=True).start()

    def _clipboard(self):
        try:
            txt = QApplication.clipboard().text()
            QMessageBox.information(self, "剪贴板", txt[:2000] if txt else "（剪贴板为空）")
        except Exception as e:
            QMessageBox.warning(self, "剪贴板", "读取失败：%s" % e)

    def _sysinfo(self):
        try:
            import platform as _p
            lines = ["操作系统: %s %s" % (_p.system(), _p.release()),
                     "版本: %s" % _p.version(),
                     "机器: %s" % _p.machine(),
                     "处理器: %s" % _p.processor()]
            try:
                r = subprocess.run("wmic cpu get name", capture_output=True, shell=True, timeout=10)
                cpu = (r.stdout or b"").decode("gbk", "replace").strip().splitlines()
                if len(cpu) > 1 and cpu[1].strip():
                    lines.append("CPU: %s" % cpu[1].strip())
            except Exception:
                pass
            try:
                r = subprocess.run("wmic path win32_VideoController get name",
                                   capture_output=True, shell=True, timeout=10)
                gpu = (r.stdout or b"").decode("gbk", "replace").strip().splitlines()
                if len(gpu) > 1 and gpu[1].strip():
                    lines.append("显卡: %s" % gpu[1].strip())
            except Exception:
                pass
            try:
                import ctypes
                class _M(ctypes.Structure):
                    _fields_ = [("u", ctypes.c_uint64), ("s", ctypes.c_uint64)]
                m = _M()
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
                lines.append("内存: %.1f GB（总）" % (m.u / 1073741824.0))
            except Exception:
                pass
            text = "\n".join(lines)
            QApplication.clipboard().setText(text)
            self.lbl_extra.setText("系统信息已复制到剪贴板：\n" + text)
        except Exception as e:
            QMessageBox.warning(self, "系统信息", "获取失败：%s" % e)

    def _power(self):
        try:
            r = subprocess.run("powercfg /getactivescheme", capture_output=True, shell=True, timeout=10)
            cur = (r.stdout or b"").decode("gbk", "replace").strip()
            if QMessageBox.question(self, "电源计划", "当前：%s\n\n切换到「高性能」计划？" % cur,
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                subprocess.run("powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
                               shell=True, timeout=10)
                self.lbl_extra.setText("已切换到高性能电源计划（游戏性能优先）。")
        except Exception as e:
            self.lbl_extra.setText("电源计划操作失败：%s" % e)

    def _uptime(self):
        try:
            import ctypes
            ups = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetTickCount64(ctypes.byref(ups))
            sec = ups.value // 1000
            d, rem = divmod(sec, 86400)
            h, rem = divmod(rem, 3600)
            m, s = divmod(rem, 60)
            self.lbl_extra.setText("系统已运行：%d 天 %d 小时 %d 分 %d 秒" % (d, h, m, s))
        except Exception as e:
            self.lbl_extra.setText("获取失败：%s" % e)

    def _crash_reports(self):
        cr = os.path.join(self.app.mc_root(), "crash-reports")
        if not os.path.isdir(cr):
            QMessageBox.information(self, "崩溃报告", "暂无崩溃报告目录（%s）" % cr)
            return
        files = sorted(os.listdir(cr), reverse=True)[:10]
        if not files:
            QMessageBox.information(self, "崩溃报告", "崩溃报告目录为空，无崩溃记录。")
            return
        msg = "最近 10 份崩溃报告：\n\n" + "\n".join("· %s" % f for f in files)
        if QMessageBox.question(self, "崩溃报告", msg + "\n\n是否打开崩溃报告文件夹？",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            os.startfile(cr)

    def _flush_dns(self):
        try:
            subprocess.run("ipconfig /flushdns", capture_output=True, shell=True, timeout=15)
            self.lbl_extra.setText("DNS 刷新完成。")
        except Exception as e:
            self.lbl_extra.setText("DNS 刷新失败：%s" % e)

    def _clean_temp(self):
        tmp = os.environ.get("TEMP") or os.environ.get("TMP")
        if not tmp:
            self.lbl_extra.setText("未找到临时目录。")
            return
        n = 0
        for dp, _, fns in os.walk(tmp):
            for fn in fns:
                try:
                    os.remove(os.path.join(dp, fn))
                    n += 1
                except OSError:
                    pass
            if n > 20000:
                break
        self.lbl_extra.setText("已清理临时文件 %d 个（%s）" % (n, tmp))

    def _screenshot(self):
        try:
            scr = QApplication.primaryScreen()
            pm = scr.grabWindow(0)
            d = os.path.join(self.app.base_dir, "screenshots")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, time.strftime("shot_%Y%m%d_%H%M%S.png"))
            pm.save(p, "PNG")
            self.lbl_extra.setText("截图已保存：%s" % p)
        except Exception as e:
            self.lbl_extra.setText("截图失败：%s" % e)

    def _java_test(self):
        javas = self.app.detect_javas() or {}
        if not javas:
            self.lbl_extra.setText("未检测到内置 Java")
            return
        out = []
        for ver, j in sorted(javas.items()):
            try:
                r = subprocess.run([j, "-version"], capture_output=True, timeout=15)
                s = (r.stderr or r.stdout or b"").decode("utf-8", "replace").splitlines()
                out.append("Java %s: %s" % (ver, s[0].strip() if s else "?"))
            except Exception:
                out.append("Java %s: 失败" % ver)
        self.lbl_extra.setText("\n".join(out))

    def _open_dir(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, "KMCL", "无法打开文件夹：%s" % e)

    def _backup(self):
        mc = self.app.mc_root()
        if not os.path.isdir(os.path.join(mc, "saves")):
            self.lbl_backup.setText("未找到 saves（世界存档）目录")
            return
        self.btn_backup.setEnabled(False)
        self.lbl_backup.setText("备份中…")
        self.backup_thread = BackupWorldsThread(mc)
        self.app._track_thread(self.backup_thread)
        self.backup_thread.done.connect(
            lambda p: (self.lbl_backup.setText("已备份到: %s" % p), self.btn_backup.setEnabled(True)))
        self.backup_thread.failed.connect(
            lambda e: (self.lbl_backup.setText("备份失败: %s" % e), self.btn_backup.setEnabled(True)))
        self.backup_thread.start()

    def _restore(self):
        mc = self.app.mc_root()
        zips = list_world_backups(mc)
        if not zips:
            self.lbl_backup.setText("backups 目录下没有可恢复的备份")
            return
        item, ok = QInputDialog.getItem(
            self, "恢复世界存档",
            "选择要恢复的备份（同名世界将被覆盖，恢复前建议先备份一次）：", zips, 0, False)
        if not ok or not item:
            return
        if QMessageBox.question(self, "确认恢复",
                                "恢复「%s」将覆盖同名世界，是否继续？" % item,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.btn_restore.setEnabled(False)
        self.lbl_backup.setText("恢复中…")
        self.restore_thread = RestoreWorldThread(os.path.join(mc, "backups", item), mc)
        self.app._track_thread(self.restore_thread)
        self.restore_thread.done.connect(
            lambda s: (self.lbl_backup.setText(s), self.btn_restore.setEnabled(True)))
        self.restore_thread.failed.connect(
            lambda e: (self.lbl_backup.setText("恢复失败: %s" % e), self.btn_restore.setEnabled(True)))
        self.restore_thread.start()

    def _check_versions(self):
        res = check_versions_integrity(self.app.mc_root())
        if not res:
            self.lbl_checkv.setText("versions 目录为空或不存在")
            return
        bad = [v for v, ok, _ in res if not ok]
        self.lbl_checkv.setText("共 %d 个版本：%d 个正常，%d 个异常%s" % (
            len(res), len(res) - len(bad), len(bad),
            "" if not bad else "（%s）" % "，".join(v for v, _, _ in res if not ok)))

    def _update_play(self):
        c = self.app.config
        n = int(c.get("launch_count", 0))
        secs = int(c.get("play_seconds", 0))
        h, m = divmod(secs // 60, 60)
        self.lbl_play.setText("已启动游戏 %d 次\n累计游玩 %d 小时 %d 分钟" % (n, h, m))

    def _reset_play(self):
        self.app.config["launch_count"] = 0
        self.app.config["play_seconds"] = 0
        self.app.save_config()
        self._update_play()

    def _home_mods_ver(self):
        """模组快捷区针对所选版本（强制版本隔离）。"""
        vid = self.cmb_modver.currentData() if hasattr(self, "cmb_modver") else None
        return vid or None

    def _update_mods(self):
        en, dis = mods_status(self.app.mc_root(), self._home_mods_ver())
        vid = self._home_mods_ver()
        self.lbl_mods.setText("版本 %s：已启用 %d 个模组，已禁用 %d 个" % (vid or "?", en, dis))

    def _toggle_mods(self, enable):
        vid = self._home_mods_ver()
        if not vid:
            QMessageBox.warning(self, "KMCL", "尚未选择游戏版本。")
            return
        n = set_all_mods(self.app.mc_root(), enable, vid)
        self.lbl_mods.setText("版本 %s：已%s %d 个模组" % (vid, "启用" if enable else "禁用", n))
        self._update_mods()

    def _kill_java(self):
        if QMessageBox.question(self, "清理残留进程",
                                "将强制结束系统中所有 javaw 进程（含正在运行的其它 Java 程序），是否继续？",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            n = kill_stray_java()
            self.lbl_kill.setText("已结束 %d 个残留 javaw 进程" % n)
        except Exception as e:
            self.lbl_kill.setText("清理失败：%s" % e)

    def _tick_monitor(self):
        """实时性能监控：CPU（两次采样差值）/ 内存 / 游戏盘使用。"""
        try:
            idle, kernel, user = get_cpu_times()
            if self._last_cpu:
                pid0, pk0, pu0 = self._last_cpu
                didle = idle - pid0
                dtotal = (kernel - pk0) + (user - pu0)
                cpu = max(0, min(100, int(100 * (1 - didle / dtotal) if dtotal else 0)))
            else:
                cpu = 0
            self._last_cpu = (idle, kernel, user)
            total, avail, load = get_mem_status()
            used_mb, total_mb = disk_usage_mb(self.app.mc_root())
            self.lbl_mon.setText(
                "CPU 使用率：%d%%\n内存：%d / %d MB（%d%%）\n游戏目录磁盘：%d / %d MB"
                % (cpu, total - avail, total, load, used_mb, total_mb))
        except Exception:
            self.lbl_mon.setText("监控暂不可用")

    def _scan_space(self):
        mc = self.app.mc_root()
        if not os.path.isdir(mc):
            self.lbl_scan.setText("游戏目录不存在")
            return
        self.btn_scan.setEnabled(False)
        self.lbl_scan.setText("扫描中…（大目录可能稍慢）")
        self.scan_thread = ScanSpaceThread(mc)
        self.app._track_thread(self.scan_thread)
        self.scan_thread.done.connect(self._scan_done)
        self.scan_thread.start()

    def _scan_done(self, rows):
        self.btn_scan.setEnabled(True)
        if not rows:
            self.lbl_scan.setText("游戏目录为空")
            return
        total = sum(s for _, s in rows)
        lines = ["共扫描出最大占用："]
        for name, size in rows:
            lines.append("  %s：%.1f MB" % (name, size / 1048576.0))
        lines.append("（以上 %d 项合计 %.1f MB）" % (len(rows), total / 1048576.0))
        self.lbl_scan.setText("\n".join(lines))

    def _clear_mem(self):
        if QMessageBox.question(self, "系统内存急救",
                                "将清理所有进程的工作集以立即释放内存（所有程序可能短暂卡顿），是否继续？",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            n = clear_system_memory()
            _, _, load = get_mem_status()
            self.lbl_mem2.setText("已清理 %d 个进程，当前内存占用 %d%%" % (n, load))
        except Exception as e:
            self.lbl_mem2.setText("清理失败：%s" % e)

    def _toggle_pre_mem(self, on):
        self.app.config["prelaunch_mem"] = bool(on)
        self.app.save_config()

    def _save_pre_kill(self):
        txt = self.edt_pre_kill.text().strip()
        names = [t.strip() for t in txt.replace("，", ",").split(",") if t.strip()]
        self.app.config["prelaunch_kill"] = names
        self.app.save_config()
        self.lbl_pre.setText("已保存，启动游戏前将自动结束：%s" % ("无" if not names else ", ".join(names)))

    def _toggle_gc(self, on):
        self.app.config["gc_log"] = bool(on)
        self.app.save_config()

    def _copy_video(self):
        QApplication.clipboard().setText(self.lbl_video.text())
        self.lbl_video.setText(self.lbl_video.text() + "（已复制）")
        QTimer.singleShot(2000, lambda: self.lbl_video.setText(video_settings_advice()))


# ============================================================
# 全局游戏设置（弹窗）
# ============================================================
class GrassAdvancedDialog(QDialog):
    """草方块引擎 · 高级选项（二级弹窗）：TAA 抗锯齿 / 动态模糊。"""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("高级选项")
        self.setModal(True)
        self.resize(480, 300)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(14)
        t = QLabel("高级选项")
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        sub = QLabel("启动时注入到游戏的高级渲染设置：")
        sub.setObjectName("SideBrandSub")
        lay.addWidget(sub)

        self.chk_taa = QCheckBox("启用 TAA 抗锯齿，减少闪烁")
        self.chk_taa.setChecked(bool(cfg.get("taa")))
        lay.addWidget(self.chk_taa)
        d1 = QLabel("写入 Mipmap 等级 + 垂直同步，明显减少远处纹理/网格闪烁（建议开启）")
        d1.setObjectName("SideBrandSub"); d1.setWordWrap(True)
        lay.addWidget(d1)
        lay.addSpacing(6)

        self.chk_blur = QCheckBox("启用动态模糊")
        self.chk_blur.setChecked(bool(cfg.get("blur")))
        lay.addWidget(self.chk_blur)
        d2 = QLabel("注意：Minecraft 原版没有动态模糊，需配合支持动态模糊的光影/模组才能看到效果")
        d2.setObjectName("SideBrandSub"); d2.setWordWrap(True)
        lay.addWidget(d2)

        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = ghost_btn("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_save = primary_btn("保存")
        btn_save.clicked.connect(self._save)
        row.addWidget(btn_cancel)
        row.addWidget(btn_save)
        lay.addLayout(row)

    def _save(self):
        self.cfg["taa"] = bool(self.chk_taa.isChecked())
        self.cfg["blur"] = bool(self.chk_blur.isChecked())
        self.accept()


class GrassEngineSection(QWidget):
    """草方块引擎（设置页内嵌版，原侧栏弹窗并入设置页）。

    五项：启用引擎 / 自动优化 / 画质预设（性能优先·均衡·画质优先·低端设备专属）/
    高级选项（TAA 抗锯齿、动态模糊）。load() 读取配置填充，collect() 写回配置，
    启动游戏时由启动逻辑注入生效。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # 1) 启用草方块引擎
        self.chk_enable = QCheckBox("启用草方块引擎")
        lay.addWidget(self.chk_enable)
        lay.addSpacing(2)

        # 2) 自动优化
        self.chk_auto = QCheckBox("自动优化")
        lay.addWidget(self.chk_auto)
        d_auto = QLabel("每次启动游戏前自动清理系统内存并应用最优 GC 参数（老电脑推荐）")
        d_auto.setObjectName("SideBrandSub"); d_auto.setWordWrap(True)
        lay.addWidget(d_auto)
        lay.addSpacing(2)

        # 3) 画质预设
        p = QLabel("画质预设")
        p.setObjectName("SectionTitle")
        lay.addWidget(p)
        self.cmb_preset = QComboBox()
        for key, name in GRASS_PRESET_NAMES.items():
            self.cmb_preset.addItem(name, key)
        lay.addWidget(self.cmb_preset)
        d_preset = QLabel("性能优先=低特效保帧率 · 均衡=默认推荐 · 画质优先=高特效 · 低端设备专属=极小视距+软件渲染兼容（老核显/无独显可玩）")
        d_preset.setObjectName("SideBrandSub"); d_preset.setWordWrap(True)
        lay.addWidget(d_preset)
        lay.addSpacing(2)

        # 4) 高级选项（二级弹窗：TAA / 动态模糊）
        self.btn_adv = ghost_btn("高级选项 ▶")
        self.btn_adv.clicked.connect(self._open_advanced)
        lay.addWidget(self.btn_adv)
        self.lbl_adv = QLabel("未配置高级项")
        self.lbl_adv.setObjectName("SideBrandSub")
        lay.addWidget(self.lbl_adv)

    def _ge(self):
        return self.app.config.setdefault("grass_engine", {})

    def load(self, ge):
        ge = ge or {}
        self.chk_enable.setChecked(bool(ge.get("enabled")))
        self.chk_auto.setChecked(bool(ge.get("auto_optimize")))
        cur = ge.get("preset", "balanced")
        idx = self.cmb_preset.findData(cur)
        self.cmb_preset.setCurrentIndex(idx if idx >= 0 else 1)
        self._refresh_adv_label()

    def collect(self):
        ge = self._ge()
        ge["enabled"] = bool(self.chk_enable.isChecked())
        ge["auto_optimize"] = bool(self.chk_auto.isChecked())
        ge["preset"] = self.cmb_preset.currentData() or "balanced"
        return ge

    def _refresh_adv_label(self):
        ge = self._ge()
        parts = []
        if ge.get("taa"):
            parts.append("TAA 抗锯齿")
        if ge.get("blur"):
            parts.append("动态模糊")
        self.lbl_adv.setText("高级选项：%s" % ("、".join(parts) if parts else "未配置高级项"))

    def _open_advanced(self):
        dlg = GrassAdvancedDialog(self._ge(), self)
        if dlg.exec_() == QDialog.Accepted:
            self._refresh_adv_label()


class GlobalGameSettingsDialog(QDialog):
    """全局游戏设置弹窗：启动器可见性等全局选项。"""

    VISIBILITY_OPTS = [
        ("exit", "游戏启动后结束启动器",
         "游戏窗口出现后自动关闭启动器进程（游戏独立运行，不受影响）"),
        ("hide", "游戏启动后自动隐藏启动器",
         "启动器窗口自动隐藏，游戏结束后可手动从任务栏/托盘重新唤起"),
        ("visible", "保持启动器可见（默认）",
         "游戏启动后启动器窗口保持原样，不做任何动作"),
        ("hide_restore", "隐藏启动器，并在游戏结束后重新打开",
         "游戏启动后隐藏启动器，游戏进程退出时自动恢复显示"),
    ]

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("全局游戏设置")
        self.setModal(True)
        self.resize(560, 400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(14)
        t = QLabel("启动器可见性")
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        sub = QLabel("选择游戏启动后启动器的显示状态：")
        sub.setObjectName("SideBrandSub")
        lay.addWidget(sub)
        cur = app.config.get("launcher_visibility", "visible")
        self.radios = {}
        for key, label, desc in self.VISIBILITY_OPTS:
            rb = QRadioButton(label)
            rb.setChecked(key == cur)
            self.radios[key] = rb
            lay.addWidget(rb)
            dl = QLabel(desc)
            dl.setObjectName("SideBrandSub")
            dl.setWordWrap(True)
            lay.addWidget(dl)
            lay.addSpacing(4)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = ghost_btn("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_save = primary_btn("保存")
        btn_save.clicked.connect(self._save)
        row.addWidget(btn_cancel)
        row.addWidget(btn_save)
        lay.addLayout(row)

    def _save(self):
        for key, rb in self.radios.items():
            if rb.isChecked():
                self.app.config["launcher_visibility"] = key
                self.app.save_config()
                break
        self.accept()


# ============================================================
# 设置
# ============================================================
class SettingsPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("设置")
        t.setObjectName("PageTitle")
        s = QLabel("启动器与游戏参数")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        card = glass_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(12)
        cl.addWidget(section_title("启动器设置"))
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        r = 0
        form.addWidget(QLabel("玩家名"), r, 0)
        self.edt_name = QLineEdit(); form.addWidget(self.edt_name, r, 1); r += 1
        form.addWidget(QLabel("默认版本"), r, 0)
        self.cmb_version = QComboBox(); form.addWidget(self.cmb_version, r, 1); r += 1
        form.addWidget(QLabel("内置 Java"), r, 0)
        self.edt_java = QLineEdit(); self.edt_java.setReadOnly(True)
        self.edt_java.setText("自动匹配：8 / 17 / 21 / 25")
        form.addWidget(self.edt_java, r, 1); r += 1
        form.addWidget(QLabel("游戏目录"), r, 0)
        self.edt_root = QLineEdit(); form.addWidget(self.edt_root, r, 1)
        br = ghost_btn("浏览"); br.clicked.connect(self._pick_root); form.addWidget(br, r, 2); r += 1
        form.addWidget(QLabel("版本隔离"), r, 0)
        row_isol = QHBoxLayout()
        row_isol.setSpacing(8)
        self.btn_isol = QPushButton("已强制开启")
        self.btn_isol.setObjectName("AccentBtn")
        self.btn_isol.setEnabled(False)
        self.btn_isol.setToolTip("KMCL 社区维护版强制版本隔离，不再支持共享游戏目录。")
        row_isol.addWidget(self.btn_isol)
        form.addLayout(row_isol, r, 1)
        lbl_isol = QLabel("强制开启：每个版本使用独立游戏目录（versions/<版本名>），存档 / 模组 / 光影 / 配置完全隔离，互不干扰")
        lbl_isol.setObjectName("SideBrandSub"); lbl_isol.setWordWrap(True)
        form.addWidget(lbl_isol, r, 2); r += 1
        form.addWidget(QLabel("模糊半径"), r, 0)
        self.slider_blur = QSlider(Qt.Horizontal); self.slider_blur.setRange(0, 60)
        form.addWidget(self.slider_blur, r, 1); r += 1
        form.addWidget(QLabel("壁纸"), r, 0)
        self.cmb_wp = QComboBox()
        for wid, name in (("01_nature", "自然风光（增强版默认）"),
                          ("02_hell", "地狱暗红"),
                          ("03_battle", "机甲对战"),
                          ("04_craft", "工坊暖色")):
            self.cmb_wp.addItem(name, wid)
        self.cmb_wp.currentIndexChanged.connect(self._apply_wallpaper)
        form.addWidget(self.cmb_wp, r, 1)
        r += 1
        form.addWidget(QLabel("字体风格"), r, 0)
        self.cmb_font = QComboBox()
        self.cmb_font.addItem("默认字体", "default")
        self.cmb_font.addItem("像素风（Minecraft 风格）", "pixel")
        self.cmb_font.currentIndexChanged.connect(self._apply_font_preview)
        form.addWidget(self.cmb_font, r, 1)
        lbl_font = QLabel("内置开源像素字体（Fusion Pixel · OFL 1.1），中文像素方块感，可免费商用与分发")
        lbl_font.setObjectName("SideBrandSub"); lbl_font.setWordWrap(True)
        form.addWidget(lbl_font, r, 2)
        r += 1
        form.setColumnStretch(1, 1)
        cl.addLayout(form)
        row = QHBoxLayout()
        self.btn_save = primary_btn("保存设置")
        self.btn_save.clicked.connect(self._save)
        self.btn_reload = ghost_btn("重新加载")
        self.btn_reload.clicked.connect(self.refresh)
        self.btn_global = ghost_btn("全局游戏设置")
        self.btn_global.clicked.connect(self._open_global)
        self.btn_icon = ghost_btn("清理图标缓存")
        self.btn_icon.clicked.connect(self._clear_icon_cache)
        row.addWidget(self.btn_save)
        self.app._attach_memory(self.btn_save, "save_settings", row)
        row.addWidget(self.btn_reload)
        self.app._attach_memory(self.btn_reload, "reload_settings", row)
        row.addWidget(self.btn_global)
        self.app._attach_memory(self.btn_global, "global_settings", row)
        row.addWidget(self.btn_icon)
        self.app._attach_memory(self.btn_icon, "clear_icon_cache", row)
        cl.addLayout(row)
        self.body_layout.addWidget(card)

        adv = glass_card()
        al = QVBoxLayout(adv)
        al.setContentsMargins(24, 20, 24, 20)
        al.setSpacing(12)
        al.addWidget(section_title("兼容性与高级参数"))
        row1 = QHBoxLayout()
        self.btn_ogl = ghost_btn("旧 OpenGL → 新 OpenGL")
        self.btn_ogl.setCheckable(True)
        row1.addWidget(self.btn_ogl)
        self.app._attach_memory(self.btn_ogl, "ogl_compat", row1,
                            is_on=lambda: self.btn_ogl.isChecked())
        self.lbl_ogl = QLabel("老英特尔核显建议开启（启用软件 OpenGL 兼容）")
        self.lbl_ogl.setObjectName("SideBrandSub")
        self.lbl_ogl.setWordWrap(True)
        row1.addWidget(self.lbl_ogl, 1)
        al.addLayout(row1)
        row2 = QHBoxLayout()
        self.btn_vk = ghost_btn("旧 OpenGL → Vulkan（实验性）")
        self.btn_vk.setCheckable(True)
        row2.addWidget(self.btn_vk)
        self.app._attach_memory(self.btn_vk, "vulkan_compat", row2,
                            is_on=lambda: self.btn_vk.isChecked())
        self.lbl_vk = QLabel("性能损耗偏大，除非你是真想玩，否则不建议尝试")
        self.lbl_vk.setObjectName("SideBrandSub")
        self.lbl_vk.setWordWrap(True)
        row2.addWidget(self.lbl_vk, 1)
        al.addLayout(row2)
        al.addSpacing(6)
        al.addWidget(QLabel("自定义 JVM 参数（每行一个，启动时追加到 Java 启动命令）"))
        self.edt_jvm_adv = QPlainTextEdit()
        self.edt_jvm_adv.setPlaceholderText("例如：\n-XX:+UseZGC\n-Dorg.lwjgl.opengl.Display.allowSoftwareOpenGL=true")
        self.edt_jvm_adv.setMaximumHeight(90)
        al.addWidget(self.edt_jvm_adv)
        al.addSpacing(6)
        al.addWidget(QLabel("自定义游戏参数（每行一个，追加到游戏启动参数末尾）"))
        self.edt_game_adv = QPlainTextEdit()
        self.edt_game_adv.setPlaceholderText("例如：\n--server 127.0.0.1:25565\n--width 1280")
        self.edt_game_adv.setMaximumHeight(90)
        al.addWidget(self.edt_game_adv)
        self.body_layout.addWidget(adv)

        # ---- 草方块引擎（原侧栏「草方块引擎」入口并入设置页） ----
        grass_card = glass_card()
        gl = QVBoxLayout(grass_card)
        gl.setContentsMargins(24, 20, 24, 20)
        gl.setSpacing(12)
        gl.addWidget(section_title("🍃 草方块引擎"))
        gl.addWidget(QLabel("KMCL 自研图形/性能引擎：启动游戏时自动应用画质预设与优化参数"))
        self.grass_section = GrassEngineSection(app, self)
        gl.addWidget(self.grass_section)
        self.body_layout.addWidget(grass_card)

        # ---- 游戏修复（原侧栏「游戏修复」选项卡并入设置页） ----
        rep = glass_card()
        rl = QVBoxLayout(rep)
        rl.setContentsMargins(24, 20, 24, 20)
        rl.setSpacing(12)
        rl.addWidget(section_title("🛠 游戏修复"))
        rl.addWidget(QLabel("校验并补全缺失的游戏文件（官方源 + BMCLAPI 镜像）"))
        row_r = QHBoxLayout()
        self.cmb_repair = QComboBox()
        row_r.addWidget(self.cmb_repair, 1)
        self.btn_repair = primary_btn("开始修复")
        self.btn_repair.clicked.connect(self._repair)
        row_r.addWidget(self.btn_repair)
        self.app._attach_memory(self.btn_repair, "repair_game", row_r)
        rl.addLayout(row_r)
        self.lbl_repair = QLabel("尚未收集任务")
        self.lbl_repair.setObjectName("SideBrandSub")
        rl.addWidget(self.lbl_repair)
        self.repair_progress = QProgressBar()
        self.repair_progress.setValue(0)
        rl.addWidget(self.repair_progress)
        self.repair_log = QPlainTextEdit()
        self.repair_log.setReadOnly(True)
        self.repair_log.setMaximumBlockCount(1200)
        self.repair_log.setMaximumHeight(180)
        rl.addWidget(self.repair_log)
        self.body_layout.addWidget(rep)
        self.repair_tasks = []
        self.repair_thread = None

        # ---- 更多设置（实用扩展） ----
        more = glass_card()
        ml = QVBoxLayout(more)
        ml.setContentsMargins(24, 20, 24, 20)
        ml.setSpacing(12)
        ml.addWidget(section_title("🧰 更多设置"))
        form2 = QGridLayout()
        form2.setHorizontalSpacing(12)
        form2.setVerticalSpacing(12)
        r2 = 0
        form2.addWidget(QLabel("默认内存(MB)"), r2, 0)
        self.spin_mem = QSpinBox()
        self.spin_mem.setRange(512, 16384)
        self.spin_mem.setSingleStep(512)
        form2.addWidget(self.spin_mem, r2, 1)
        r2 += 1
        form2.addWidget(QLabel("界面语言"), r2, 0)
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("简体中文", "zh_CN")
        self.cmb_lang.addItem("English", "en_US")
        form2.addWidget(self.cmb_lang, r2, 1)
        r2 += 1
        form2.addWidget(QLabel("下载线程数"), r2, 0)
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 16)
        form2.addWidget(self.spin_threads, r2, 1)
        r2 += 1
        form2.addWidget(QLabel("启动器窗口"), r2, 0)
        row_w = QHBoxLayout()
        self.edt_win_w = QLineEdit()
        self.edt_win_w.setFixedWidth(64)
        self.edt_win_h = QLineEdit()
        self.edt_win_h.setFixedWidth(64)
        row_w.addWidget(self.edt_win_w)
        row_w.addWidget(QLabel(" × "))
        row_w.addWidget(self.edt_win_h)
        form2.addLayout(row_w, r2, 1)
        r2 += 1
        form2.addWidget(QLabel("游戏内语言"), r2, 0)
        self.cmb_game_lang = QComboBox()
        self.cmb_game_lang.addItems(["简体中文 zh_cn", "English en_us"])
        form2.addWidget(self.cmb_game_lang, r2, 1)
        r2 += 1
        form2.setColumnStretch(1, 1)
        ml.addLayout(form2)
        row3 = QHBoxLayout()
        self.btn_autostart = QCheckBox("开机自启启动器")
        self.btn_autostart.toggled.connect(self._toggle_autostart)
        row3.addWidget(self.btn_autostart)
        self.app._attach_memory(self.btn_autostart, "autostart", row3,
                            is_on=lambda: self.btn_autostart.isChecked())
        self.btn_clear_log = ghost_btn("清空启动日志")
        self.btn_clear_log.clicked.connect(self._clear_logs)
        row3.addWidget(self.btn_clear_log)
        self.app._attach_memory(self.btn_clear_log, "clear_logs", row3)
        self.btn_cfg_backup = ghost_btn("备份配置")
        self.btn_cfg_backup.clicked.connect(self._backup_cfg)
        row3.addWidget(self.btn_cfg_backup)
        self.app._attach_memory(self.btn_cfg_backup, "backup_cfg", row3)
        self.btn_cfg_restore = ghost_btn("恢复配置")
        self.btn_cfg_restore.clicked.connect(self._restore_cfg)
        row3.addWidget(self.btn_cfg_restore)
        self.app._attach_memory(self.btn_cfg_restore, "restore_cfg", row3)
        self.btn_reset = ghost_btn("重置设置")
        self.btn_reset.clicked.connect(self._reset_cfg)
        row3.addWidget(self.btn_reset)
        self.app._attach_memory(self.btn_reset, "reset_settings", row3)
        ml.addLayout(row3)
        self.lbl_more = QLabel("")
        self.lbl_more.setObjectName("SideBrandSub")
        self.lbl_more.setWordWrap(True)
        ml.addWidget(self.lbl_more)
        self.body_layout.addWidget(more)

        note = glass_card()
        nl = QVBoxLayout(note)
        nl.setContentsMargins(20, 16, 20, 16)
        lbl = QLabel("提示：启动器内置 Java 8 / 17 / 21 / 25 四套运行时，启动游戏时会自动检测该版本需要的 Java 并匹配，无需手动选择。")
        lbl.setWordWrap(True)
        lbl.setObjectName("SideBrandSub")
        nl.addWidget(lbl)
        self.body_layout.addWidget(note)
        self.body_layout.addStretch(1)

    def _pick_root(self):
        p = QFileDialog.getExistingDirectory(self, "选择 .minecraft 目录")
        if p:
            self.edt_root.setText(p)

    def _apply_wallpaper(self):
        wid = self.cmb_wp.currentData()
        if wid:
            self.app._set_wallpaper(wid)

    def _apply_font_preview(self):
        """字体风格下拉即时预览：切换「默认字体 / 像素风」后立即重建全局 QSS。"""
        style = self.cmb_font.currentData() or "default"
        from ui import theme
        theme.set_font_style(style)
        self.app.apply_theme()
        # 同步应用默认 QFont（无 QSS 覆盖的窗口/弹窗也生效）
        fam = theme.font_family()
        if fam:
            QApplication.instance().setFont(QFont(fam))

    def _open_global(self):
        GlobalGameSettingsDialog(self.app, self).exec_()

    def _clear_icon_cache(self):
        """一键清理图标缓存（.icon_cache）：确认后清空全部图标文件，下次浏览自动重下。"""
        cache = self.app.cache_dir
        n = 0
        try:
            if os.path.isdir(cache):
                for dp, _, fns in os.walk(cache):
                    n += len(fns)
        except OSError:
            n = 0
        if QMessageBox.question(
                self, "KMCL",
                "确定清空图标缓存吗？\n\n当前缓存：%s\n图标文件约 %d 个\n（下次浏览模组/光影等资源时会自动重新下载）" %
                (cache, n),
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        trim_icon_cache(cache, 0)
        QMessageBox.information(self, "KMCL", "图标缓存已清理。")

    # ---- 更多设置 ----
    def _toggle_autostart(self, on):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            exe = os.path.join(self.app.base_dir, "KMCL.exe")
            if not os.path.exists(exe):
                exe = os.path.join(self.app.base_dir, "启动KMCL.bat")
            if on:
                winreg.SetValueEx(key, "KMCL", 0, winreg.REG_SZ, '"%s"' % exe)
            else:
                try:
                    winreg.DeleteValue(key, "KMCL")
                except OSError:
                    pass
            winreg.CloseKey(key)
            self.app.config["autostart"] = bool(on)
            self.app.save_config()
            self.lbl_more.setText("开机自启：已%s" % ("开启" if on else "关闭"))
        except Exception as e:
            self.lbl_more.setText("自启设置失败：%s" % e)

    def _clear_logs(self):
        d = os.path.join(self.app.data_dir, "logs")
        n = 0
        if os.path.isdir(d):
            for f in os.listdir(d):
                try:
                    os.remove(os.path.join(d, f))
                    n += 1
                except OSError:
                    pass
        self.lbl_more.setText("已清空启动日志 %d 个文件" % n)

    def _backup_cfg(self):
        src = os.path.join(self.app.data_dir, "launcher_config.json")
        if not os.path.exists(src):
            self.lbl_more.setText("没有配置文件可备份")
            return
        dst = os.path.join(self.app.data_dir,
                           "launcher_config_backup_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy(src, dst)
        self.lbl_more.setText("配置已备份：%s" % dst)

    def _restore_cfg(self):
        p = QFileDialog.getOpenFileName(self, "选择备份文件", self.app.base_dir,
                                        "备份配置 (*.json)")[0]
        if not p:
            return
        if QMessageBox.question(self, "恢复配置",
                                "确认用 %s 覆盖当前配置？" % os.path.basename(p),
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            self.app.config.update(cfg)
            self.app.save_config()
            self.refresh()
            self.app.apply_theme()
            self.lbl_more.setText("配置已恢复，界面已刷新。")
        except Exception as e:
            QMessageBox.warning(self, "恢复配置", "失败：%s" % e)

    def _reset_cfg(self):
        if QMessageBox.question(self, "重置设置", "确认恢复默认设置？当前配置将被覆盖。",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.app.config.clear()
            self.app.config.update(dict(DEFAULT_CONFIG))
            self.app.save_config()
            self.refresh()
            self.app.apply_theme()
            self.lbl_more.setText("已恢复默认设置。")
        except Exception as e:
            self.lbl_more.setText("重置失败：%s" % e)

    # ---- 游戏修复（并入设置页） ----
    def _collect_repair(self):
        """收集选中版本的修复任务；失败/无版本返回 False 并给出提示。"""
        vid = self.cmb_repair.currentText()
        if not vid:
            self.lbl_repair.setText("⚠ 当前无任何版本，请先在游戏库安装游戏版本")
            self.repair_log.appendPlainText("无可用版本，无法收集任务")
            self.repair_tasks = []
            return False
        try:
            from repair_game import collect_tasks
            tasks, natives, _ = collect_tasks(vid, self.app.mc_root())
        except Exception as e:
            self.repair_tasks = []
            self.lbl_repair.setText("收集任务失败：%s" % str(e)[:120])
            self.repair_log.appendPlainText("收集任务失败（%s）：%s" % (vid, e))
            return False
        self.repair_tasks = list(tasks) + list(natives or [])
        self.lbl_repair.setText("%s：共 %d 个文件待校验/下载" % (vid, len(self.repair_tasks)))
        self.repair_log.appendPlainText("收集到 %d 个任务（%s）" % (len(self.repair_tasks), vid))
        return len(self.repair_tasks) > 0

    def _repair(self):
        if not self.repair_tasks and not self._collect_repair():
            QMessageBox.warning(self, "KMCL",
                                "未能开始修复：没有可修复的任务。\n\n"
                                "可能原因：\n"
                                "· 版本下拉框为空 —— 请先到「游戏库」安装游戏版本\n"
                                "· 收集任务失败 —— 详情见下方日志")
            return
        self.btn_repair.setEnabled(False)
        self.repair_progress.setRange(0, len(self.repair_tasks))
        self.repair_progress.setValue(0)
        self.repair_thread = RepairThread(self.repair_tasks, self.app.base_dir)
        self.app._track_thread(self.repair_thread)
        self.repair_thread.progress.connect(
            lambda i, n, msg: (self.repair_progress.setValue(i),
                               msg and self.repair_log.appendPlainText(msg)))
        self.repair_thread.done.connect(
            lambda s: (self.repair_log.appendPlainText(s),
                       self.btn_repair.setEnabled(True)))
        self.repair_thread.start()

    def refresh(self):
        cfg = self.app.config
        self.edt_name.setText(cfg.get("player_name", ""))
        self.edt_java.setText("自动匹配：8 / 17 / 21 / 25")
        self.edt_root.setText(cfg.get("mc_root", ""))
        self.slider_blur.setValue(int(cfg.get("blur_radius", 30)))
        wid = cfg.get("wallpaper", "01_nature")
        idx = self.cmb_wp.findData(wid)
        self.cmb_wp.setCurrentIndex(idx if idx >= 0 else 0)
        fs = cfg.get("font_style", "default")
        fi = self.cmb_font.findData(fs)
        self.cmb_font.setCurrentIndex(fi if fi >= 0 else 0)
        self.btn_ogl.setChecked(bool(cfg.get("compat_opengl", False)))
        self.btn_vk.setChecked(bool(cfg.get("compat_vulkan", False)))
        # 版本隔离强制开启，不做可切换状态
        self.edt_jvm_adv.setPlainText(cfg.get("custom_jvm_args", ""))
        self.edt_game_adv.setPlainText(cfg.get("custom_game_args", ""))
        # 草方块引擎（设置页内嵌）
        self.grass_section.load(cfg.get("grass_engine") or {})
        # 更多设置
        self.spin_mem.setValue(int(cfg.get("default_mem_mb", auto_heap_mb())))
        lang = cfg.get("ui_lang", "zh_CN")
        li = self.cmb_lang.findData(lang)
        self.cmb_lang.setCurrentIndex(li if li >= 0 else 0)
        self.spin_threads.setValue(int(cfg.get("download_threads", 8)))
        self.edt_win_w.setText(str(cfg.get("win_w", 1280)))
        self.edt_win_h.setText(str(cfg.get("win_h", 800)))
        gl = cfg.get("game_lang", "zh_cn")
        self.cmb_game_lang.setCurrentIndex(0 if str(gl).startswith("zh") else 1)
        self.btn_autostart.setChecked(bool(cfg.get("autostart", False)))
        self.cmb_version.clear()
        for v in scan_versions(self.app.mc_root()):
            self.cmb_version.addItem(version_icon(self.app.base_dir, v), v)
        if cfg.get("game_version") in [self.cmb_version.itemText(i) for i in range(self.cmb_version.count())]:
            self.cmb_version.setCurrentText(cfg.get("game_version"))
        # 游戏修复版本下拉 + 自动收集任务
        self.cmb_repair.clear()
        for v in scan_versions(self.app.mc_root()):
            self.cmb_repair.addItem(version_icon(self.app.base_dir, v), v)
        self._collect_repair()

    def _save(self):
        cfg = self.app.config
        cfg["player_name"] = self.edt_name.text().strip() or "KMCL Player"
        cfg["game_version"] = self.cmb_version.currentText()
        cfg["java_path"] = ""  # 始终自动匹配内置 Java
        cfg["mc_root"] = self.edt_root.text().strip()
        cfg["blur_radius"] = self.slider_blur.value()
        wp = self.cmb_wp.currentData()
        if wp:
            cfg["wallpaper"] = wp
        cfg["font_style"] = self.cmb_font.currentData() or "default"
        cfg["compat_opengl"] = bool(self.btn_ogl.isChecked())
        cfg["compat_vulkan"] = bool(self.btn_vk.isChecked())
        cfg["version_isolation"] = True  # 强制版本隔离，不可关闭
        cfg["custom_jvm_args"] = self.edt_jvm_adv.toPlainText()
        cfg["custom_game_args"] = self.edt_game_adv.toPlainText()
        # 草方块引擎（设置页内嵌）
        cfg["grass_engine"] = self.grass_section.collect()
        # 更多设置
        cfg["default_mem_mb"] = self.spin_mem.value()
        cfg["ui_lang"] = self.cmb_lang.currentData()
        cfg["download_threads"] = self.spin_threads.value()
        try:
            cfg["win_w"] = max(800, int(self.edt_win_w.text() or 1280))
            cfg["win_h"] = max(600, int(self.edt_win_h.text() or 800))
        except ValueError:
            cfg["win_w"], cfg["win_h"] = 1280, 800
        cfg["game_lang"] = "zh_cn" if self.cmb_game_lang.currentIndex() == 0 else "en_us"
        # 游戏内语言写入 options.txt（游戏根目录）：键为 lang（Minecraft 实际键名），
        # 值统一小写（如 lang:zh_cn / lang:en_us），与 java_manager._ensure_default_language 一致。
        try:
            opts = os.path.join(self.app.mc_root(), "options.txt")
            gl_key = "zh_cn" if cfg["game_lang"] == "zh_cn" else "en_us"
            if os.path.isfile(opts):
                with open(opts, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                import re as _re
                if _re.search(r"(?m)^lang:", content):
                    content = _re.sub(r"(?m)^lang:.*$", "lang:" + gl_key, content)
                else:
                    content = content.rstrip() + "\nlang:" + gl_key + "\n"
                with open(opts, "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception:
            pass
        self.app.save_config()
        self.app.apply_theme()
        # 应用窗口大小
        try:
            self.app.resize(cfg.get("win_w", 1280), cfg.get("win_h", 800))
        except Exception:
            pass
        QMessageBox.information(self, "KMCL", "设置已保存。")


# ============================================================
# 关于
# ============================================================
class AboutPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("关于")
        t.setObjectName("PageTitle")
        s = QLabel("KMCL 社区维护版")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        card = glass_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(12)
        icon = QLabel()
        if app.icon_path and os.path.exists(app.icon_path):
            pm = QPixmap(app.icon_path).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon.setPixmap(pm)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedHeight(104)
        cl.addWidget(icon)
        name = QLabel("KMCL 社区维护版")
        name.setObjectName("SideBrand")
        name.setAlignment(Qt.AlignCenter)
        cl.addWidget(name)
        sub = QLabel("基于 KMCL 开源底层架构的社区维护版本\n简洁轻便 · 专注 Minecraft 启动")
        sub.setAlignment(Qt.AlignCenter)
        sub.setObjectName("SideBrandSub")
        cl.addWidget(sub)
        cl.addWidget(divider())
        for line in [
            "· 内置 Python 运行环境，无需用户安装 Python",
            "· 支持 Java 8 / 17 / 21 自动检测与匹配",
            "· 局域网联机大厅：开房 / 联机码加入",
            "· 游戏文件校验修复（官方源 + BMCLAPI 镜像）",
            "· 微软账号登录支持（microsoft_auth 模块）",
        ]:
            lbl = QLabel(line)
            lbl.setObjectName("SideBrandSub")
            cl.addWidget(lbl)
        cl.addSpacing(8)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_full = primary_btn("📄 完整版全声明")
        self.btn_full.clicked.connect(self._open_full_decl)
        btn_row.addWidget(self.btn_full)
        btn_row.addStretch(1)
        cl.addLayout(btn_row)
        self.body_layout.addWidget(card)
        self.body_layout.addStretch(1)

    def _open_full_decl(self):
        """打开启动器目录下的「关于启动器.docx」完整声明文档。"""
        doc = os.path.join(self.app.base_dir, "关于启动器.docx")
        if not os.path.exists(doc):
            QMessageBox.warning(self, "KMCL",
                                "未找到文档：关于启动器.docx\n\n"
                                "应位于启动器目录下（%s），请确认该文件存在。" % self.app.base_dir)
            return
        try:
            os.startfile(doc)
        except Exception as e:
            QMessageBox.warning(self, "KMCL", "打开文档失败：\n%s" % e)


# ============================================================
# 自定义标题栏（自绘拖拽 + 双击最大化）
# ============================================================
class TitleBar(QWidget):
    """鼠标按下时记录偏移，移动时拖动整个窗口。双击切换最大化。"""

    def __init__(self, window):
        super().__init__()
        self._win = window
        self._off = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._off = e.globalPos() - self._win.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._off is not None and (e.buttons() & Qt.LeftButton):
            self._win.move(e.globalPos() - self._off)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._off = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._win._toggle_max()


# ============================================================
# 主窗口
# ============================================================
# ============================================================
# Alpha 3.0 · 账号中心（微软正版 / 离线账号 / 皮肤）
# ============================================================
class AccountPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("账号中心")
        t.setObjectName("PageTitle")
        s = QLabel("微软正版 / 离线账号 / 皮肤管理")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        # 当前账号卡
        card = glass_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 20, 22, 20)
        cl.setSpacing(10)
        cl.addWidget(section_title("当前账号"))
        row = QHBoxLayout()
        self.avatar = QLabel()
        self.avatar.setFixedSize(56, 56)
        self.avatar.setStyleSheet("background: rgba(128,128,128,0.15); border-radius: 28px;")
        self.avatar.setAlignment(Qt.AlignCenter)
        row.addWidget(self.avatar)
        info_box = QVBoxLayout()
        self.lbl_acc_name = QLabel("未登录")
        self.lbl_acc_name.setObjectName("SideBrand")
        self.lbl_acc_type = QLabel("使用离线账号或登录微软账号后即可启动正版联机")
        self.lbl_acc_type.setObjectName("SideBrandSub")
        info_box.addWidget(self.lbl_acc_name)
        info_box.addWidget(self.lbl_acc_type)
        row.addLayout(info_box)
        row.addStretch(1)
        btn_ms = QPushButton("微软账号登录")
        btn_ms.setObjectName("AccentBtn")
        btn_ms.clicked.connect(self._login_microsoft)
        row.addWidget(btn_ms)
        cl.addLayout(row)
        self.body_layout.addWidget(card)

        # 离线账号
        card2 = glass_card()
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(22, 20, 22, 20)
        c2.setSpacing(10)
        c2.addWidget(section_title("离线账号"))
        off_row = QHBoxLayout()
        self.edt_offline = QLineEdit()
        self.edt_offline.setPlaceholderText("输入离线玩家名，如：Steve")
        off_row.addWidget(self.edt_offline, 1)
        btn_add = QPushButton("创建离线账号")
        btn_add.setObjectName("AccentBtn")
        btn_add.clicked.connect(self._add_offline)
        off_row.addWidget(btn_add)
        c2.addLayout(off_row)
        tip = QLabel("离线账号可正常玩单人/局域网；想进正版服务器请登录微软账号。")
        tip.setObjectName("SideBrandSub")
        tip.setWordWrap(True)
        c2.addWidget(tip)
        self.body_layout.addWidget(card2)

        # 账号列表
        card3 = glass_card()
        c3 = QVBoxLayout(card3)
        c3.setContentsMargins(22, 20, 22, 20)
        c3.setSpacing(10)
        h = QHBoxLayout()
        h.addWidget(section_title("账号列表"))
        btn_switch = QPushButton("切换选中账号")
        btn_switch.setObjectName("AccentBtn")
        btn_switch.clicked.connect(self._switch_account)
        h.addStretch(1)
        h.addWidget(btn_switch)
        btn_del = QPushButton("删除选中账号")
        btn_del.setObjectName("DangerBtn")
        btn_del.clicked.connect(self._del_account)
        h.addWidget(btn_del)
        c3.addLayout(h)
        self.acc_list = QListWidget()
        self.acc_list.setObjectName("VersionList")
        c3.addWidget(self.acc_list)
        self.body_layout.addWidget(card3)

        # 皮肤管理
        card4 = glass_card()
        c4 = QVBoxLayout(card4)
        c4.setContentsMargins(22, 20, 22, 20)
        c4.setSpacing(10)
        c4.addWidget(section_title("离线皮肤"))
        warn = QLabel("⚠ 由于技术问题，此功能只保证对 1.19.2 以前的版本有效（离线启动时生效）")
        warn.setStyleSheet("color: #FFB84D; font-size: 12px;")
        warn.setWordWrap(True)
        c4.addWidget(warn)
        sk_row = QHBoxLayout()
        for label, key in (("随机", "random"), ("史蒂夫", "steve"), ("艾利克斯", "alex"),
                           ("正版皮肤", "ms_skin"), ("自定义", "custom")):
            b = QPushButton(label)
            b.clicked.connect(lambda _, k=key: self._pick_skin(k))
            sk_row.addWidget(b)
        c4.addLayout(sk_row)
        sk_tip = QLabel("选择后自动写入 skins 目录；正版皮肤需先登录微软账号，自定义可导入本地 PNG。")
        sk_tip.setObjectName("SideBrandSub")
        sk_tip.setWordWrap(True)
        c4.addWidget(sk_tip)
        self.body_layout.addWidget(card4)

    # ---- 账号操作 ----
    def refresh(self):
        cfg = self.app.config
        acc = current_account(cfg)
        if acc:
            self.lbl_acc_name.setText(acc.get("name", "?"))
            self.lbl_acc_type.setText("类型：%s" % ("微软正版" if acc.get("type") == "microsoft" else "离线账号"))
        else:
            self.lbl_acc_name.setText("未登录")
            self.lbl_acc_type.setText("使用离线账号或登录微软账号后即可启动正版联机")
        self.acc_list.clear()
        for i, a in enumerate(cfg.get("accounts") or []):
            tag = "● " if i == int(cfg.get("current_account", 0)) else "○ "
            self.acc_list.addItem("%s%s  [%s]" % (tag, a.get("name", "?"),
                                                  "微软正版" if a.get("type") == "microsoft" else "离线"))
        self._refresh_avatar()

    def _refresh_avatar(self):
        """纯本地显示头像：只用已存在的皮肤文件，绝不联网下载（避免切页卡死）。
        皮肤文件不存在时显示灰色占位，由用户点击皮肤按钮后才触发下载。"""
        cfg = self.app.config
        mc_root = self.app.mc_root()
        skins_dir = os.path.join(mc_root, "skins")
        skin = cfg.get("skin", "steve")
        cands = ("custom.png", "custom_skin.png") if skin == "custom" else (skin + ".png",)
        p = None
        for fn in cands:
            fp = os.path.join(skins_dir, fn)
            if os.path.exists(fp):
                p = fp
                break
        if p:
            try:
                pm = QPixmap(p).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.avatar.setPixmap(pm)
            except Exception:
                self.avatar.setPixmap(QPixmap())
        else:
            self.avatar.setPixmap(QPixmap())

    def _login_microsoft(self):
        from microsoft_auth import get_auth_url, open_browser, login_with_code, extract_code_from_url
        try:
            url = get_auth_url()
        except Exception as e:
            QMessageBox.warning(self, "KMCL", "无法获取授权链接：%s" % e)
            return
        try:
            open_browser()
        except Exception:
            pass
        text, ok = QInputDialog.getText(
            self, "微软账号登录",
            "浏览器已打开，完成登录后浏览器地址栏会变成一段长链接。\n"
            "请复制整段链接粘贴到下面：\n\n%s" % url)
        if not ok or not text.strip():
            return
        try:
            code = extract_code_from_url(text.strip())
            acc = login_with_code(code)
        except Exception as e:
            QMessageBox.critical(self, "KMCL", "登录失败：\n%s" % e)
            return
        accs = self.app.config.get("accounts") or []
        accs.append(acc)
        self.app.config["accounts"] = accs
        self.app.config["current_account"] = len(accs) - 1
        self.app.config["player_name"] = acc.get("name", "")
        self.app.save_config()
        self.refresh()
        QMessageBox.information(self, "KMCL", "登录成功：%s" % acc.get("name", "?"))

    def _add_offline(self):
        name = self.edt_offline.text().strip()
        if not name:
            QMessageBox.warning(self, "KMCL", "请输入离线玩家名。")
            return
        if len(name) > 16:
            QMessageBox.warning(self, "KMCL", "玩家名不能超过 16 个字符。")
            return
        import uuid as _uuid
        acc = {"name": name, "type": "offline",
               "uuid": str(_uuid.uuid3(_uuid.NAMESPACE_DNS, "offline:" + name)),
               "access_token": "0", "refresh_token": "", "expires_at": 0}
        accs = self.app.config.get("accounts") or []
        accs.append(acc)
        self.app.config["accounts"] = accs
        self.app.config["current_account"] = len(accs) - 1
        self.app.config["player_name"] = name
        self.app.save_config()
        self.edt_offline.clear()
        self.refresh()

    def _switch_account(self):
        i = self.acc_list.currentRow()
        if i < 0:
            QMessageBox.warning(self, "KMCL", "请先在列表中选择一个账号。")
            return
        accs = self.app.config.get("accounts") or []
        if 0 <= i < len(accs):
            self.app.config["current_account"] = i
            self.app.config["player_name"] = accs[i].get("name", "")
            self.app.save_config()
            self.refresh()

    def _del_account(self):
        i = self.acc_list.currentRow()
        if i < 0:
            QMessageBox.warning(self, "KMCL", "请先在列表中选择一个账号。")
            return
        accs = self.app.config.get("accounts") or []
        if not (0 <= i < len(accs)):
            return
        if QMessageBox.question(self, "KMCL", "确定删除账号「%s」？" % accs[i].get("name", "?")) != QMessageBox.Yes:
            return
        accs.pop(i)
        self.app.config["accounts"] = accs
        cur = int(self.app.config.get("current_account", 0))
        if i < cur:
            self.app.config["current_account"] = max(0, cur - 1)
        elif i == cur:
            self.app.config["current_account"] = 0
        self.app.save_config()
        self.refresh()

    # ---- 皮肤 ----
    def _pick_skin(self, key):
        cfg = self.app.config
        mc_root = self.app.mc_root()
        skins_dir = os.path.join(mc_root, "skins")
        os.makedirs(skins_dir, exist_ok=True)
        if key == "custom":
            path, _ = QFileDialog.getOpenFileName(self, "选择皮肤 PNG", "", "PNG 图片 (*.png)")
            if not path:
                return
            import shutil as _sh
            _sh.copyfile(path, os.path.join(skins_dir, "custom.png"))
        if key == "ms_skin":
            acc = current_account(cfg)
            if not acc or acc.get("type") != "microsoft":
                QMessageBox.warning(self, "KMCL", "请先登录微软账号，才能获取正版皮肤。")
                return
            if not fetch_skin_file("https://crafatar.com/renders/body/%s?overlay" % acc.get("uuid", ""),
                                   os.path.join(skins_dir, "custom.png")):
                # 兜底：下载正面头图
                fetch_skin_file("https://crafatar.com/avatars/%s?overlay" % acc.get("uuid", ""),
                                os.path.join(skins_dir, "custom.png"))
            set_account_skin(cfg, "custom")
        else:
            set_account_skin(cfg, key)
        self.app.save_config()
        self._refresh_avatar()
        QMessageBox.information(self, "KMCL", "皮肤已设置为：%s" % key)


# ============================================================
# Alpha 3.0 · 模组管理（本地模组体检 / 启停 / 删除）
# ============================================================
class ModsPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("模组管理")
        t.setObjectName("PageTitle")
        s = QLabel("本地模组 · 依赖体检 · 启停管理")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        row = QHBoxLayout()
        row.addWidget(QLabel("版本"))
        self.cmb_version = QComboBox()
        self.cmb_version.currentIndexChanged.connect(lambda _: self._rescan())
        row.addWidget(self.cmb_version)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("AccentBtn")
        btn_refresh.clicked.connect(self.refresh)
        row.addWidget(btn_refresh)
        btn_enable = QPushButton("启用选中")
        btn_enable.setObjectName("AccentBtn")
        btn_enable.clicked.connect(lambda: self._toggle(True))
        row.addWidget(btn_enable)
        btn_disable = QPushButton("禁用选中")
        btn_disable.setObjectName("AccentBtn")
        btn_disable.clicked.connect(lambda: self._toggle(False))
        row.addWidget(btn_disable)
        btn_del = QPushButton("删除选中")
        btn_del.setObjectName("DangerBtn")
        btn_del.clicked.connect(self._delete)
        row.addWidget(btn_del)
        btn_dir = QPushButton("打开模组目录")
        btn_dir.setObjectName("AccentBtn")
        btn_dir.clicked.connect(self._open_dir)
        row.addWidget(btn_dir)
        row.addStretch(1)
        self.body_layout.addLayout(row)

        card = glass_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)
        self.list = QListWidget()
        self.list.setObjectName("VersionList")
        cl.addWidget(self.list, 1)
        self.body_layout.addWidget(card, 1)

        self.issues = QLabel("")
        self.issues.setWordWrap(True)
        self.body_layout.addWidget(self.issues)

    def refresh(self):
        vers = scan_versions(self.app.mc_root())
        cur = self.cmb_version.currentText()
        self.cmb_version.blockSignals(True)
        self.cmb_version.clear()
        # 强制版本隔离：不再提供共享 mods 目录，只管理各版本隔离目录
        for v in vers:
            self.cmb_version.addItem(version_icon(self.app.base_dir, v), v, v)
        if cur:
            idx = self.cmb_version.findText(cur)
            if idx > 0:
                self.cmb_version.setCurrentIndex(idx)
        self.cmb_version.blockSignals(False)
        self._rescan()

    def _mods_dir(self):
        vid = self.cmb_version.currentData()
        if vid:
            return os.path.join(self.app.mc_root(), "versions", vid, "mods")
        return None

    def _rescan(self):
        rows = scan_local_mods(self.app.mc_root(), self.cmb_version.currentData() or None)
        self.rows = rows
        self.list.clear()
        for r in rows:
            meta = r["meta"]
            nm = meta.get("name") or r["name"]
            ver = meta.get("version") or "-"
            src = meta.get("source") or "-"
            txt = "%s  [%s %s]%s" % (r["name"], src, ver, "" if r["enabled"] else "  (已禁用)")
            item = QListWidgetItem(("🟢 " if r["enabled"] else "⚪ ") + txt)
            item.setData(Qt.UserRole, r["file"])
            self.list.addItem(item)
        # 体检
        missing, conflicts = mod_issues(rows)
        lines = []
        if missing:
            lines.append("⚠ 缺失依赖：%d 个" % len(missing))
            for f, d in missing[:6]:
                lines.append("   · %s 需要 %s" % (f, d))
        if conflicts:
            lines.append("⚠ 检测到重复/冲突模组：%d 组" % len(conflicts))
            for k, files in conflicts[:3]:
                lines.append("   · %s：%s" % (k, ", ".join(os.path.basename(x) for x in files)))
        if not lines:
            lines.append("✓ 未发现明显依赖缺失或冲突")
        self.issues.setText("\n".join(lines))

    def _toggle(self, enable):
        i = self.list.currentRow()
        if i < 0:
            QMessageBox.warning(self, "KMCL", "请先在列表中选择一个模组。")
            return
        r = self.rows[i]
        f = r["file"]
        try:
            if enable and f.endswith(".disabled"):
                os.rename(f, f[:-len(".disabled")])
            elif not enable and f.endswith(".jar"):
                os.rename(f, f + ".disabled")
        except Exception as e:
            QMessageBox.critical(self, "KMCL", "操作失败：%s" % e)
            return
        self._rescan()

    def _delete(self):
        i = self.list.currentRow()
        if i < 0:
            QMessageBox.warning(self, "KMCL", "请先在列表中选择一个模组。")
            return
        f = self.rows[i]["file"]
        if QMessageBox.question(self, "KMCL", "确定删除模组文件？\n%s" % os.path.basename(f)) != QMessageBox.Yes:
            return
        try:
            os.remove(f)
        except Exception as e:
            QMessageBox.critical(self, "KMCL", "删除失败：%s" % e)
            return
        self._rescan()

    def _open_dir(self):
        d = self._mods_dir()
        if not d:
            QMessageBox.warning(self, "KMCL", "尚未安装任何游戏版本，请先到「下载游戏」安装一个版本。")
            return
        os.makedirs(d, exist_ok=True)
        os.startfile(d)


# ============================================================
# Alpha 3.0 · 整合包（.mrpack / .zip 导入导出）
# ============================================================
class ModpackPage(Page):
    def __init__(self, app):
        super().__init__(app)
        head = QHBoxLayout()
        t = QLabel("整合包")
        t.setObjectName("PageTitle")
        s = QLabel("Modrinth .mrpack / CurseForge .zip 导入与导出")
        s.setObjectName("PageSub")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(s)
        head.addStretch(1)
        self.body_layout.addLayout(head)
        self.body_layout.addWidget(divider())

        row = QHBoxLayout()
        btn_imp = QPushButton("导入整合包")
        btn_imp.setObjectName("AccentBtn")
        btn_imp.clicked.connect(self._import_pack)
        row.addWidget(btn_imp)
        btn_exp = QPushButton("导出当前版本")
        btn_exp.setObjectName("AccentBtn")
        btn_exp.clicked.connect(self._export_pack)
        row.addWidget(btn_exp)
        row.addStretch(1)
        self.body_layout.addLayout(row)

        card = glass_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlaceholderText("选择整合包文件后这里会显示解析结果…")
        cl.addWidget(self.info, 1)
        self.body_layout.addWidget(card, 1)

    def refresh(self):
        pass

    def _import_pack(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择整合包", "", "整合包 (*.mrpack *.zip);;全部文件 (*)")
        if not path:
            return
        self._do_import(path)

    def _do_import(self, path):
        import zipfile
        info_lines = ["解析中…"]
        self.info.setPlainText("\n".join(info_lines))
        try:
            with zipfile.ZipFile(path, "r") as z:
                names = z.namelist()
                if "modrinth.index.json" in names:
                    index = json.loads(z.read("modrinth.index.json").decode("utf-8", "ignore"))
                    info_lines = ["【Modrinth 整合包】",
                                  "名称: %s" % index.get("name", "?"),
                                  "MC 版本: %s" % index.get("dependencies", {}).get("minecraft", "?"),
                                  "加载器: %s" % ", ".join(
                                      k for k in index.get("dependencies", {}) if k != "minecraft") or "原版",
                                  "文件数: %d" % len(index.get("files", [])),
                                  "",
                                  "点击下方按钮确认安装（需先安装对应 MC 版本与加载器）"]
                    self._pending = ("mrpack", path, index, z)
                elif "manifest.json" in names:
                    man = json.loads(z.read("manifest.json").decode("utf-8", "ignore"))
                    over = man.get("overrides", "overrides")
                    has_over = any(n.startswith(over + "/") for n in names)
                    info_lines = ["【CurseForge 整合包】",
                                  "名称: %s" % man.get("name", "?"),
                                  "MC 版本: %s" % man.get("minecraft", {}).get("version", "?"),
                                  "加载器: %s" % ", ".join(
                                      m.get("id", "") for m in man.get("minecraft", {}).get("modLoaders", [])),
                                  "文件数: %d" % len(man.get("files", [])),
                                  "overrides: %s" % over]
                    if not has_over:
                        info_lines.append("")
                        info_lines.append("⚠ CurseForge 依赖文件需 API 授权，本包仅含清单；")
                        info_lines.append("  若压缩包内含 mods/config 目录可直接安装。")
                    else:
                        info_lines.append("")
                        info_lines.append("点击下方按钮：将 overrides 覆盖到游戏目录")
                    self._pending = ("curse", path, man, z)
                else:
                    # 可能是完整包（直接含 mods/ config/ 等）
                    self._pending = ("flat", path, None, z)
                    info_lines = ["【完整整合包】", "压缩包内含游戏文件，可直接覆盖安装。"]
            self._pending_pack = info_lines
            self.info.setPlainText("\n".join(info_lines))
            if QMessageBox.question(self, "KMCL", "解析完成，确认安装该整合包？") == QMessageBox.Yes:
                self._confirm_install()
        except Exception as e:
            self.info.setPlainText("解析失败：%s" % e)

    def _confirm_install(self):
        import zipfile
        kind, path, index, z = self._pending
        mc_root = self.app.mc_root()
        # 强制版本隔离：先选择安装到哪个版本（mods/config/saves 写入 versions/<版本>/）
        vers = scan_versions(mc_root)
        if not vers:
            QMessageBox.warning(self, "KMCL", "尚未安装任何游戏版本，请先到「下载游戏」安装一个版本。")
            return
        vid, ok = QInputDialog.getItem(self, "安装整合包", "选择安装到哪个游戏版本：", vers, 0, False)
        if not ok or not vid:
            return
        target = os.path.join(mc_root, "versions", vid)
        os.makedirs(target, exist_ok=True)
        try:
            if kind == "mrpack":
                self.info.appendPlainText("\n开始安装（下载依赖文件）到版本 %s…" % vid)
                from modrinth_api import download_file
                ok = 0
                for f in index.get("files", []):
                    rel = f.get("path", "")
                    if not rel:
                        continue
                    dest = os.path.join(target, rel)
                    url = (f.get("downloads") or [""])[0]
                    if not url:
                        continue
                    try:
                        download_file(url, dest)
                        ok += 1
                    except Exception:
                        self.info.appendPlainText("  跳过: %s" % rel)
                # overrides 解压
                over = "overrides"
                for n in z.namelist():
                    if n.startswith(over + "/") and not n.endswith("/"):
                        try:
                            z.extract(n, target)
                        except Exception:
                            pass
                self.info.appendPlainText("下载完成 %d 个文件，overrides 已覆盖到 %s" % (ok, vid))
            elif kind == "curse":
                over = index.get("overrides", "overrides")
                n_over = 0
                for n in z.namelist():
                    if n.startswith(over + "/") and not n.endswith("/"):
                        rel = n[len(over) + 1:]
                        try:
                            with z.open(n) as src, open(os.path.join(target, rel), "wb") as dst:
                                dst.write(src.read())
                            n_over += 1
                        except Exception:
                            pass
                self.info.appendPlainText("overrides 已覆盖 %d 个文件（mods/config/saves）到 %s" % (n_over, vid))
            else:
                n_over = 0
                for n in z.namelist():
                    if n.endswith("/") or not n.startswith(("mods/", "config/", "saves/", "resourcepacks/")):
                        continue
                    try:
                        with z.open(n) as src, open(os.path.join(target, n), "wb") as dst:
                            dst.write(src.read())
                        n_over += 1
                    except Exception:
                        pass
                self.info.appendPlainText("已覆盖 %d 个游戏文件到 %s" % (n_over, vid))
            QMessageBox.information(self, "KMCL", "整合包安装完成到 %s。请启动该版本游玩。" % vid)
        except Exception as e:
            self.info.appendPlainText("\n安装出错：%s" % e)

    def _export_pack(self):
        """导出当前选中版本为 .mrpack（含 mods/config/saves）。"""
        vers = scan_versions(self.app.mc_root())
        if not vers:
            QMessageBox.warning(self, "KMCL", "没有已安装版本可导出。")
            return
        vid, ok = QInputDialog.getItem(self, "导出整合包", "选择要导出的版本：", vers, 0, False)
        if not ok or not vid:
            return
        # 强制版本隔离：导出所选版本隔离目录下的资源
        target = os.path.join(self.app.mc_root(), "versions", vid)
        srcs = ["mods", "config", "saves", "resourcepacks"]
        files = []
        for s in srcs:
            d = os.path.join(target, s)
            if os.path.isdir(d):
                for root, _, fns in os.walk(d):
                    for fn in fns:
                        full = os.path.join(root, fn)
                        rel = os.path.relpath(full, target).replace("\\", "/")
                        files.append({"path": rel, "downloads": [], "fileSize": os.path.getsize(full)})
        out, _ = QFileDialog.getSaveFileName(self, "保存整合包", "%s.mrpack" % vid, "Modrinth 整合包 (*.mrpack)")
        if not out:
            return
        import zipfile
        index = {
            "formatVersion": 1,
            "game": "minecraft",
            "versionId": vid,
            "name": "%s (KMCL 导出)" % vid,
            "files": files,
            "dependencies": {"minecraft": vid.split("-")[0].split("+")[0] if vid.split("-")[0] else "1.20.1"},
        }
        try:
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("modrinth.index.json", json.dumps(index, ensure_ascii=False, indent=2))
                for f in files:
                    full = os.path.join(target, f["path"].replace("/", os.sep))
                    if os.path.exists(full):
                        z.write(full, "overrides/" + f["path"])
            QMessageBox.information(self, "KMCL", "已导出 %d 个文件到：\n%s" % (len(files), out))
        except Exception as e:
            QMessageBox.critical(self, "KMCL", "导出失败：%s" % e)


class MicaMainWindow(QWidget):
    """KMCL 社区维护版主窗口（无边框 + 玻璃拟态渐变背景）。

    参数与 main.py 约定一致：
      base_dir  : 工程根目录（资源/配置/python 所在）
      icon_path : 窗口图标 png 路径（可为 None）
    """

    def __init__(self, base_dir, icon_path=None):
        super().__init__()
        self.base_dir = base_dir
        self.data_dir = resolve_data_dir(base_dir)   # 可写数据目录（onefile 下=exe 同级）
        self.cache_dir = resolve_cache_dir(base_dir)  # 图标缓存（开发模式=系统临时目录）
        self.icon_path = icon_path
        self.config = load_config(self.data_dir)
        # 后台线程注册表：退出时统一终止，防止 QThread 仍在运行导致进程崩溃
        self._bg_threads = set()

        self.setObjectName("MainRoot")
        self.setWindowTitle("KMCL 社区维护版")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        # 透明背景：配合 MainRoot 圆角 QSS + setMask，实现真正的窗口四角圆角
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(1240, 800)
        self.setMinimumSize(1080, 700)
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 顶层
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 壁纸背景层（借鉴增强版：游戏壁纸 + 主题遮罩） ----
        # 创建顺序即叠放顺序：壁纸最底 → 半透明遮罩盖其上 → 布局内容最上
        self._bg_wall = QLabel(self)
        self._bg_mask = QLabel(self)
        self._bg_pix = self._wallpaper_pixmap(self.config.get("wallpaper", "01_nature"))
        self._bg_wall.setGeometry(0, 0, self.width(), self.height())
        self._bg_mask.setGeometry(0, 0, self.width(), self.height())
        self._refresh_bg()

        # ---- 标题栏（自绘拖拽） ----
        bar = TitleBar(self)
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(46)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 4, 8, 4)
        bl.setSpacing(6)
        mini_icon = QLabel()
        if icon_path and os.path.exists(icon_path):
            pm = QPixmap(icon_path).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            mini_icon.setPixmap(pm)
        mini_icon.setFixedSize(20, 20)
        bl.addWidget(mini_icon)
        title_lbl = QLabel("KMCL 社区维护版")
        title_lbl.setObjectName("TitleLabel")
        bl.addWidget(title_lbl)
        bl.addStretch(1)
        self.btn_min = self._win_btn("—", self.showMinimized)
        self.btn_max = self._win_btn("□", self._toggle_max)
        self.btn_close = self._win_btn("✕", self.close, close=True)
        bl.addWidget(self.btn_min)
        bl.addWidget(self.btn_max)
        bl.addWidget(self.btn_close)
        root.addWidget(bar)

        # ---- 主体 ----
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # 左侧导航
        side = QWidget()
        side.setObjectName("SideBar")
        side.setFixedWidth(196)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 14, 14, 14)
        sl.setSpacing(6)
        brand_icon = QLabel()
        if icon_path and os.path.exists(icon_path):
            pm = QPixmap(icon_path).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            brand_icon.setPixmap(pm)
        brand_icon.setFixedSize(44, 44)
        brand_icon.setAlignment(Qt.AlignCenter)
        sl.addWidget(brand_icon, 0, Qt.AlignHCenter)
        bname = QLabel("KMCL 社区维护版")
        bname.setObjectName("SideBrand")
        bname.setAlignment(Qt.AlignCenter)
        sl.addWidget(bname)
        bsub = QLabel("COMMUNITY EDITION")
        bsub.setObjectName("SideBrandSub")
        bsub.setAlignment(Qt.AlignCenter)
        sl.addWidget(bsub)
        sl.addSpacing(14)

        # 顶部搜索框：搜索各功能选项（回车弹出结果，双击跳转）
        self.edt_search = QLineEdit()
        self.edt_search.setObjectName("SearchBox")
        self.edt_search.setPlaceholderText("🔍 搜索功能…")
        self.edt_search.returnPressed.connect(self._open_search)
        sl.addWidget(self.edt_search)
        sl.addSpacing(8)

        self.nav_btns = {}
        nav_items = [
            ("home", "🏠  首页"),
            ("account", "👤  账号中心"),
            ("games", "🎮  游戏库"),
            ("multiplayer", "🌐  联机大厅"),
            ("toolbox", "🧰  百宝箱"),
            ("settings", "⚙  设置"),
            ("about", "ℹ  关于"),
        ]
        for key, text in nav_items:
            b = QPushButton(text)
            b.setObjectName("NavBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.goto(k))
            sl.addWidget(b)
            self.nav_btns[key] = b
        sl.addStretch(1)
        ver = QLabel("KMCL 社区维护版 · Alpha 3.0")
        ver.setObjectName("SideBrandSub")
        ver.setAlignment(Qt.AlignCenter)
        sl.addWidget(ver)
        body.addWidget(side)

        # 内容区
        self.stack = QStackedWidget()
        self.stack.setObjectName("ContentArea")
        self.pages = {
            "home": HomePage(self),
            "account": AccountPage(self),
            "games": GamesPage(self),
            "multiplayer": MultiplayerPage(self),
            "toolbox": ToolboxPage(self),
            "settings": SettingsPage(self),
            "about": AboutPage(self),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)
        body.addWidget(self.stack, 1)
        root.addLayout(body)

        self.apply_theme()
        self.goto(self.config.get("current_page", "home"))

        # 图标缓存自动瘦身（.icon_cache 超 50MB 清空，防止随浏览无限膨胀）
        try:
            trim_icon_cache(self.cache_dir)
        except Exception:
            pass

        # Alpha 3.0 · 全局按钮果冻反馈（所有 QPushButton 自动生效）
        app = QApplication.instance()
        if app is not None:
            self._jelly = JellyFilter()
            app.installEventFilter(self._jelly)

    # ---- 启动渐显动画（首次显示淡入） ----
    _faded_once = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self._faded_once:
            self._faded_once = True
            fade_in_window(self)

    # ---- 标题栏按钮 ----
    def _win_btn(self, text, slot, close=False):
        b = QPushButton(text)
        b.setObjectName("WinBtnClose" if close else "WinBtn")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
            self.btn_max.setText("□")
        else:
            self.showMaximized()
            self.btn_max.setText("❐")

    # ---- 导航 ----
    def goto(self, key):
        if key not in self.pages:
            key = "home"  # 旧配置指向已合并的页面时兜底回首页
        self.stack.setCurrentWidget(self.pages[key])
        self.pages[key].refresh()
        for k, b in self.nav_btns.items():
            b.setChecked(k == key)
        self.config["current_page"] = key

    # ---- 按钮记忆缓存（已开启 / 未开启 状态栏） ----
    def _mem_tag(self, key, on=None):
        """创建按钮状态标签：已开启（绿）/ 未开启（灰）。"""
        if on is None:
            on = BtnState.is_on(self.config, key)
        lbl = QLabel("已开启" if on else "未开启")
        lbl.setProperty("state", "on" if on else "off")
        lbl.setObjectName("StateTag")
        lbl.setAttribute(Qt.WA_StyledBackground, True)
        return lbl

    def _attach_memory(self, btn, key, row=None, is_on=None, mark_click=True):
        """给按钮挂上记忆缓存与右侧状态栏。

        btn       : 目标按钮
        key       : 记忆键（持久化到 button_states）
        row       : 按钮所在 QBoxLayout，在其右侧插入状态标签
        is_on     : 可选回调，返回实际开关状态（如 QCheckBox.isChecked）
        mark_click: 点击按钮时是否标记为「已开启」
        """
        tag = self._mem_tag(key)
        if row is not None:
            row.addWidget(tag)

        def _apply(on):
            tag.setText("已开启" if on else "未开启")
            tag.setProperty("state", "on" if on else "off")
            try:
                tag.style().unpolish(tag)
                tag.style().polish(tag)
            except Exception:
                pass

        def _mark(*_):
            on = bool(is_on() if is_on else True)
            BtnState.mark(self.config, key, on=on, save=self.save_config)
            _apply(on)

        if mark_click:
            btn.clicked.connect(_mark)
        # 开关类按钮：toggled 时同步刷新（含程序 setChecked 触发）
        if isinstance(btn, QCheckBox) or btn.isCheckable():
            btn.toggled.connect(lambda *_: _mark())
        _apply(BtnState.is_on(self.config, key))
        return tag

    # ---- 后台线程管理与退出清理 ----
    def _track_thread(self, t):
        """注册后台线程；finished 时自动移除。退出时统一 terminate+wait 防崩溃。"""
        if t is None:
            return
        self._bg_threads.add(t)
        try:
            t.finished.connect(lambda: self._bg_threads.discard(t))
        except Exception:
            pass

    def closeEvent(self, ev):
        # 终止仍在运行的后台线程（列表/图标/修复等网络线程），避免 QThread 存活时
        # 进程退出触发 access violation。游戏启动线程若在跑：游戏进程独立，仅终止等待逻辑。
        for t in list(self._bg_threads):
            try:
                if t.isRunning():
                    t.terminate()
                    t.wait(800)
            except Exception:
                pass
        self._bg_threads.clear()
        super().closeEvent(ev)

    def _open_search(self):
        """侧边栏搜索：匹配 SEARCH_INDEX，弹出结果列表，双击跳转。"""
        q = self.edt_search.text().strip()
        if not q:
            return
        ql = q.lower()
        hits = [(k, t, d) for k, t, d in SEARCH_INDEX if ql in t.lower() or ql in d.lower()]
        if not hits:
            QMessageBox.information(self, "搜索", "未找到与「%s」相关的功能。\n\n可尝试：内存 / 模组 / 皮肤 / 下载 / 备份 / 主题…" % q)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("搜索结果 · %s（双击跳转）" % q)
        dlg.resize(540, 380)
        vl = QVBoxLayout(dlg)
        vl.addWidget(QLabel("找到 %d 个相关功能：" % len(hits)))
        lst = QListWidget()
        for k, t, d in hits:
            it = QListWidgetItem("🏷  %s\n       %s" % (t, d))
            it.setData(Qt.UserRole, k)
            lst.addItem(it)
        vl.addWidget(lst, 1)
        btn = QHBoxLayout()
        btn.addStretch(1)
        b_cancel = ghost_btn("关闭")
        b_cancel.clicked.connect(dlg.reject)
        btn.addWidget(b_cancel)
        vl.addLayout(btn)
        lst.itemDoubleClicked.connect(
            lambda _: (dlg.accept(),
                       self.goto(lst.currentItem().data(Qt.UserRole))))
        dlg.exec_()

    # ---- 配置与主题 ----
    def save_config(self):
        save_config(self.data_dir, self.config)

    def apply_theme(self):
        # 统一透明玻璃风格（不区分深浅色）
        qss = theme.build_qss("light")
        self.setStyleSheet(qss)
        # 全局应用：二级弹窗（版本选择/加载器/全局设置等 QDialog）同步主题，
        # 不再出现纯黑背景
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
        self._refresh_bg()

    def _wallpaper_pixmap(self, wp_id):
        """按壁纸 ID 加载壁纸；wallpapers 目录缺失时回退旧暗色壁纸。"""
        base = os.path.join(self.base_dir, "assets", "wallpapers")
        p = os.path.join(base, (wp_id or "") + ".png")
        if os.path.exists(p):
            return QPixmap(p)
        try:
            names = sorted(os.listdir(base))
            for n in names:
                if n.endswith(".png"):
                    return QPixmap(os.path.join(base, n))
        except Exception:
            pass
        p2 = os.path.join(self.base_dir, "assets", "bg_wallpaper.png")
        return QPixmap(p2) if os.path.exists(p2) else QPixmap()

    def _set_wallpaper(self, wp_id):
        """切换壁纸并立即刷新（供设置页调用）。"""
        self.config["wallpaper"] = wp_id
        self._bg_pix = self._wallpaper_pixmap(wp_id)
        self._refresh_bg()

    def _refresh_bg(self):
        """刷新壁纸缩放与主题遮罩色。"""
        if self._bg_pix:
            pm = self._bg_pix.scaled(self.width(), self.height(),
                                     Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self._bg_wall.setPixmap(pm)
            self._bg_wall.setAlignment(Qt.AlignCenter)
        # 唯一默认深色透明玻璃：深色半透明遮罩（壁纸隐约透出，整体深沉通透）
        self._bg_mask.setStyleSheet("background: rgba(15,15,22,0.45);")

    def _apply_round_mask(self, radius=14):
        """把整个窗口裁剪成圆角（最大化时恢复方角，避免遮挡任务栏）。"""
        if self.isMaximized() or self.isFullScreen():
            self.clearMask()
            return
        try:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), radius, radius)
            region = QRegion(path.toFillPolygon().toPolygon())
            self.setMask(region)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bg_wall.setGeometry(0, 0, self.width(), self.height())
        self._bg_mask.setGeometry(0, 0, self.width(), self.height())
        self._refresh_bg()
        self._apply_round_mask()

    def mc_root(self):
        return self.config.get("mc_root") or default_mc_root()

    def detect_javas(self):
        """检测可用 Java：系统已安装（注册表/JAVA_HOME/常见目录）+ 内置 runtime。"""
        try:
            from java_manager import find_system_javas, find_builtin_javas
            javas = find_system_javas()
            builtin = find_builtin_javas(self.base_dir)
            if not builtin:
                builtin = find_builtin_javas(os.path.dirname(self.base_dir))
            for k, v in builtin.items():
                javas.setdefault(k, v)
            return javas or {}
        except Exception:
            return {}

    # ---- 按需下载 Java 的进度弹窗 ----
    def _jdk_progress(self, *args):
        if len(args) == 1 and isinstance(args[0], str):
            # 阶段提示：创建进度框
            if getattr(self, "_jdk_dlg", None) is None:
                from PyQt5.QtWidgets import QProgressDialog
                dlg = QProgressDialog(args[0], "取消", 0, 0, self)
                dlg.setWindowTitle("KMCL · 下载 Java")
                dlg.setWindowModality(Qt.WindowModal)
                dlg.setMinimumWidth(420)
                dlg.setAutoClose(False)
                dlg.setAutoReset(False)
                dlg.canceled.connect(self._jdk_cancel_clicked)
                dlg.show()
                self._jdk_dlg = dlg
                self._jdk_cancel_flag = False
            else:
                self._jdk_dlg.setLabelText(args[0])
        else:
            done, total = (args[0], args[1]) if len(args) >= 2 else (args[0], 0)
            dlg = getattr(self, "_jdk_dlg", None)
            if dlg:
                if total > 0:
                    dlg.setRange(0, total)
                    dlg.setValue(done)
                dlg.setLabelText("正在下载 Java… %d MB" % (done // 1048576))
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()

    def _jdk_cancel(self):
        return getattr(self, "_jdk_cancel_flag", False)

    def _jdk_cancel_clicked(self):
        self._jdk_cancel_flag = True

    def _jdk_done(self):
        dlg = getattr(self, "_jdk_dlg", None)
        if dlg:
            dlg.close()
            self._jdk_dlg = None
