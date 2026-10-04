# -*- coding: utf-8 -*-
"""KMCL 社区维护版 - Mica Edition"""
import sys, os

# ---- KMCL 社区维护版：内置 Python 引导 ----
# 若当前解释器不是内置 Python（用户系统没装 Python / 版本不匹配），
# 自动切换到工程自带的 python/python.exe 重新启动，保证人人可跑。
if not getattr(sys, 'frozen', False):
    # 嵌入式 Python 的 python312._pth 会固定 sys.path，
    # 不自动包含脚本所在目录 → 必须显式注入，否则 import ui 失败
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        _py_dir = os.path.join(_here, "python")
        _cur = os.path.normcase(os.path.abspath(sys.executable)) if sys.executable else ""
        # 按目录判断：只要已经在工程内置 python 目录内（python.exe 或 pythonw.exe），
        # 就不再引导，避免 pythonw.exe 被误判为外部解释器而弹出黑色控制台窗口。
        if _cur and _cur.startswith(os.path.normcase(os.path.abspath(_py_dir))):
            pass
        else:
            _w = os.path.join(_py_dir, "pythonw.exe")
            target = _w if os.path.exists(_w) else os.path.join(_py_dir, "python.exe")
            if os.path.exists(target):
                import subprocess
                code = subprocess.call([target, __file__] + sys.argv[1:])
                sys.exit(code)
    except Exception:
        pass  # 引导失败时继续用当前解释器运行

if getattr(sys, 'frozen', False):
    # PyInstaller 打包后
    if hasattr(sys, '_MEIPASS'):
        BASE_DIR = sys._MEIPASS
    else:
        exe_dir = os.path.dirname(sys.executable)
        internal = os.path.join(exe_dir, "_internal")
        BASE_DIR = internal if os.path.isdir(internal) else exe_dir
else:
    # 开发模式：优先用 _internal（和打包后一致），否则用当前目录
    dev_dir = os.path.dirname(os.path.abspath(__file__))
    internal = os.path.join(dev_dir, "_internal")
    BASE_DIR = internal if os.path.isdir(internal) else dev_dir
# 注意：不要把 BASE_DIR 加进 sys.path！
# 旧版打包的 _internal 里有 Python 3.14 编译的 _ctypes.pyd，
# 会遮蔽 Python 3.11 自带的标准库扩展，导致
# "Module use of python314.dll conflicts with this version of Python"

from PyQt5.QtWidgets import QApplication
from ui.mica_window import MicaMainWindow

# 随包字体：开发时位于项目根目录（BASE_DIR 的上级），打包后位于 BASE_DIR
FONT_FILE = "Kmcl Minecraft!Launcher Fonts.ttf"
# 内置像素字体（Fusion Pixel · OFL 1.1 开源免费商用），设置页「像素风」使用
PIXEL_FONT_FILE = "Kmcl Pixel Font.ttf"


def setup_app_font(app, search_dirs):
    """注册字体包并设为应用默认字体。

    项目内所有文字都用 QFont("") / QFont()（空族名），会自动解析为
    应用默认字体，因此只需在此处设置一次即可全局生效。加载失败则保持
    系统默认字体，不影响启动。
    """
    from PyQt5.QtGui import QFontDatabase, QFont
    import glob
    candidates = []
    for d in search_dirs:
        candidates.append(os.path.join(d, FONT_FILE))
        candidates.extend(glob.glob(os.path.join(d, "*.ttf")))
        candidates.extend(glob.glob(os.path.join(d, "*.otf")))
    for path in candidates:
        if not os.path.exists(path):
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0]))
            # 注入全局 QSS，覆盖项目内 QFont("") 空族名创建的标题/按钮
            from ui import theme
            theme.set_app_font_family(families[0])
            # 记录随包字体族名：设置页「默认字体」选项 / 恢复默认时用
            theme.set_bundled_font_family(families[0])
            return families[0]
    return None


def setup_pixel_font(search_dirs):
    """注册内置像素字体（Fusion Pixel，OFL 1.1 开源免费商用），
    记录族名供设置页「字体风格 → 像素风」切换使用。文件缺失时静默跳过。"""
    from PyQt5.QtGui import QFontDatabase
    for d in search_dirs:
        p = os.path.join(d, PIXEL_FONT_FILE)
        if not os.path.exists(p):
            continue
        font_id = QFontDatabase.addApplicationFont(p)
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            from ui import theme
            theme.set_pixel_font_family(families[0])
            return families[0]
    return None


def _install_excepthook():
    """全局异常兜底：任何未捕获异常写入 logs/kmcl-error.log 并弹窗，
    避免 pythonw 无控制台时启动器静默消失。"""
    import traceback
    import time as _t

    def hook(etype, value, tb):
        try:
            # 打包版日志写系统应用数据目录（不在 exe 旁边/桌面生成文件）
            if getattr(sys, "frozen", False):
                base = os.path.join(
                    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "KMCL")
                os.makedirs(base, exist_ok=True)
            else:
                base = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(base, "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "kmcl-error.log"), "a", encoding="utf-8") as f:
                f.write("\n[%s] %s\n%s\n" % (
                    _t.strftime("%Y-%m-%d %H:%M:%S"),
                    "".join(traceback.format_exception(etype, value, tb)),
                    "=" * 50))
        except Exception:
            pass
        try:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(None, "KMCL 错误",
                                 "发生未预期的错误：\n%s\n\n详情已写入 logs/kmcl-error.log" % value)
        except Exception:
            pass
    sys.excepthook = hook


def main():
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName("KMCL 社区维护版")

    # 终端里 Ctrl+C / IDE 停止按钮：安静退出，不打 KeyboardInterrupt traceback。
    # Qt 事件循环是 C++ 循环，Python 信号处理器要靠定时唤醒才能执行。
    import signal
    from PyQt5.QtCore import QTimer

    def _sigint_handler(signum, frame):
        app.quit()

    for sig in (signal.SIGINT, getattr(signal, "SIGBREAK", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _sigint_handler)
        except (ValueError, OSError):
            pass
    _wake = QTimer()
    _wake.timeout.connect(lambda: None)   # 空回调，仅唤醒 Python 解释器
    _wake.start(200)

    # 找 ico.png：优先 BASE_DIR，其次项目根目录（可能是 _internal 的上级）
    icon_path = None
    candidates = [BASE_DIR]
    # 加上 _internal 的上级（打包后的 exe 目录 / 开发时的项目根）
    parent = os.path.dirname(BASE_DIR)
    if parent and parent != BASE_DIR:
        candidates.append(parent)
    for c in candidates:
        p = os.path.join(c, "ico.png")
        if os.path.exists(p):
            icon_path = p; break
    if icon_path:
        from PyQt5.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))

    # 在创建任何窗口/控件之前注册并应用随包字体
    setup_app_font(app, candidates)
    # 注册内置像素字体（Fusion Pixel · OFL 1.1），供「像素风」字体风格切换
    setup_pixel_font(candidates)

    # 读取配置里的字体风格偏好（default / pixel），在窗口 QSS 生成前生效
    try:
        import json as _json
        with open(os.path.join(BASE_DIR, "launcher_config.json"), encoding="utf-8") as _f:
            _cfg = _json.load(_f)
        from ui import theme
        theme.set_font_style(_cfg.get("font_style", "default"))
    except Exception:
        pass

    window = MicaMainWindow(BASE_DIR, icon_path=icon_path)
    window.show()
    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        # 终端里 Ctrl+C / 手动停止程序时的正常退出，不打 traceback
        sys.exit(0)

if __name__ == "__main__":
    main()
