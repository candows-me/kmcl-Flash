# -*- coding: utf-8 -*-
"""KMCL 社区维护版 - 主题与全局 QSS。

深色玻璃拟态 + 蓝紫渐变（品牌语言延续 MCDX：主紫 #6750A4 / 亮紫 #8B5CF6）。
所有文字用 QFont("") 空族名，由 main.setup_app_font 注入随包字体；
此处额外提供 set_app_font_family / set_bundled_font_family 供 main.py 调用。
"""
import os

# ---- 字体族管理 ----
APP_FONT_FAMILY = ""          # 随包字体族（由 main.py 注入）
BUNDLED_FONT_FAMILY = None    # 记录随包字体族名（设置页「默认字体」用）
PIXEL_FONT_FAMILY = None      # 像素字体族名（main.py 注册 Fusion Pixel 后注入）
FONT_STYLE = "default"        # 当前字体风格："default" / "pixel"


def set_app_font_family(family):
    """注入全局 QSS 字体族。main.setup_app_font 找到随包字体后调用。"""
    global APP_FONT_FAMILY
    APP_FONT_FAMILY = family or ""


def set_bundled_font_family(family):
    """记录随包字体族名，供设置页「恢复默认字体」使用。"""
    global BUNDLED_FONT_FAMILY
    BUNDLED_FONT_FAMILY = family


def set_pixel_font_family(family):
    """记录内置像素字体（Fusion Pixel）族名，供「像素风」字体风格使用。"""
    global PIXEL_FONT_FAMILY
    PIXEL_FONT_FAMILY = family


def set_font_style(style):
    """切换字体风格："default"（随包字体）/ "pixel"（Minecraft 像素风）。"""
    global FONT_STYLE
    FONT_STYLE = "pixel" if style == "pixel" else "default"


def font_family():
    if FONT_STYLE == "pixel" and PIXEL_FONT_FAMILY:
        return PIXEL_FONT_FAMILY
    return APP_FONT_FAMILY or "Microsoft YaHei UI"


# ---- 调色板（唯一默认：深色透明玻璃。侧栏不单独涂色，与右侧同背景）----
LIGHT_COLORS = {
    "bg0": "#24242C",          # 最深（深色基底，再提亮一档）
    "bg1": "#2E2E3A",          # 渐变中部
    "bg2": "#24242C",          # 渐变尾部
    "accent": "#8B5CF6",       # 主紫（亮紫，深色下醒目）
    "accent_sel_bg": "rgba(139,92,246,0.24)",
    "accent2": "#A78BFA",
    "accent3": "#C4B5FD",
    "text": "#F2F2F7",
    "text_dim": "rgba(255,255,255,0.72)",
    "text_faint": "rgba(255,255,255,0.50)",
    "card": "rgba(255,255,255,0.085)",
    "card_hover": "rgba(255,255,255,0.125)",
    "card_border": "rgba(255,255,255,0.12)",
    "section_title": "rgba(215,204,252,0.95)",
    "sidebar_bg": "transparent",   # 侧栏不涂色：与右侧同背景，整体一块透明玻璃
    "nav_hover": "rgba(255,255,255,0.08)",
    "btn_bg": "rgba(255,255,255,0.045)",   # 通用按钮平时底色（与左侧导航按钮同透明档）
    "menu_bg": "#1E1E26",
    "input_bg": "rgba(255,255,255,0.08)",
    "track_bg": "rgba(255,255,255,0.10)",
    "code_bg": "rgba(0,0,0,0.30)",
    "code_text": "rgba(255,255,255,0.92)",
    "danger": "#FF6B6B",
    "ok": "#6BCB77",
}


def _f():
    return font_family()


def build_qss(theme="light"):
    """生成全局 QSS 字符串。统一透明玻璃风格（不再区分深浅色）。"""
    c = LIGHT_COLORS
    return f"""
* {{
    font-family: "{_f()}";
    font-size: 13px;
    color: {c['text']};
    outline: none;
}}
QWidget {{
    background: transparent;
}}
/* ===== 主窗口背景：深蓝紫渐变 + 全局圆角 ===== */
#MainRoot {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {c['bg0']}, stop:0.55 {c['bg1']}, stop:1 {c['bg2']});
    border: 1px solid {c['card_border']};
    border-radius: 14px;
}}

/* ===== 二级弹窗：主题背景（不再纯黑）+ 圆角 ===== */
QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {c['bg0']}, stop:0.55 {c['bg1']}, stop:1 {c['bg2']});
    border: 1px solid {c['card_border']};
    border-radius: 16px;
}}

/* ===== 标题栏 ===== */
#TitleBar {{
    background: transparent;
}}
#TitleLabel {{
    color: {c['text']};
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#WinBtn {{
    background: transparent;
    color: {c['text_dim']};
    border: none;
    border-radius: 16px;
    font-size: 14px;
    min-width: 48px;
    min-height: 34px;
}}
QPushButton#WinBtn:hover {{
    background: {c['card_hover']};
    color: {c['text']};
}}
QPushButton#WinBtnClose {{
    background: transparent;
    color: {c['text_dim']};
    border: none;
    border-radius: 16px;
    font-size: 14px;
    min-width: 48px;
    min-height: 34px;
}}
QPushButton#WinBtnClose:hover {{
    background: #E81123;
    color: white;
    border-radius: 16px;
}}

/* ===== 左侧导航 ===== */
#SideBar {{
    background: {c['sidebar_bg']};
    border-right: 1px solid {c['card_border']};
}}
#SideBrand {{
    font-size: 17px;
    font-weight: 700;
    color: {c['text']};
}}
#SideBrandSub {{
    font-size: 10px;
    color: {c['text_faint']};
}}
/* ===== 按钮状态记忆标签（已开启 / 未开启）===== */
#StateTag {{
    font-size: 10px;
    padding: 2px 9px;
    border-radius: 9px;
    font-weight: 600;
}}
#StateTag[state="on"] {{
    color: #7ee6a1;
    background: rgba(64, 200, 120, 0.16);
    border: 1px solid rgba(64, 200, 120, 0.38);
}}
#StateTag[state="off"] {{
    color: {c['text_faint']};
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid {c['card_border']};
}}
QPushButton#NavBtn {{
    background: transparent;
    color: {c['text_dim']};
    border: none;
    border-radius: 12px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    min-height: 26px;
}}
QPushButton#NavBtn:hover {{
    background: {c['nav_hover']};
    color: {c['text']};
}}
QPushButton#NavBtn:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: white;
    font-weight: 600;
}}
QLineEdit#SearchBox {{
    background: rgba(255,255,255,0.09);
    border: 1px solid {c['card_border']};
    border-radius: 12px;
    color: {c['text']};
    padding: 7px 12px;
    font-size: 12.5px;
}}
QLineEdit#SearchBox:focus {{
    border-color: {c['accent']};
}}
QLineEdit#SearchBox::placeholder {{
    color: {c['text_faint']};
}}
QPushButton#SubTabBtn {{
    background: {c['btn_bg']};
    color: {c['text_dim']};
    border: 1px solid {c['card_border']};
    border-radius: 16px;
    padding: 7px 18px;
    font-size: 12px;
    min-height: 22px;
}}
QPushButton#SubTabBtn:hover {{
    background: {c['nav_hover']};
    color: {c['text']};
}}
QPushButton#SubTabBtn:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: white;
    border: none;
    font-weight: 600;
}}

/* ===== 内容区 ===== */
#ContentArea {{
    background: transparent;
}}
QLabel#PageTitle {{
    font-size: 20px;
    font-weight: 700;
    color: {c['text']};
}}
QLabel#PageSub {{
    font-size: 11.5px;
    color: {c['text_faint']};
}}
QLabel#SectionTitle {{
    font-size: 13.5px;
    font-weight: 600;
    color: {c['section_title']};
}}

/* ===== 玻璃卡片 ===== */
QFrame#GlassCard {{
    background: {c['card']};
    border: 1px solid {c['card_border']};
    border-radius: 18px;
}}
QFrame#GlassCard:hover {{
    background: {c['card_hover']};
}}
QFrame#GlassCard[selected="true"] {{
    background: {c['accent_sel_bg']};
    border: 2px solid {c['accent']};
}}

/* ===== 按钮 ===== */
/* Alpha 3.0 · 所有按钮按下时内容微微下沉（配合果冻回弹动画） */
QPushButton:pressed {{
    padding-top: 2px;
    padding-bottom: 0px;
}}
QPushButton#PrimaryBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 14px;
    font-weight: 600;
    padding: 12px 26px;
    min-height: 22px;
}}
QPushButton#PrimaryBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {c['accent2']}, stop:1 {c['accent3']});
}}
QPushButton#PrimaryBtn:pressed {{
    padding-top: 13px;
    padding-bottom: 11px;
}}
QPushButton#GhostBtn {{
    background: {c['btn_bg']};
    color: {c['text']};
    border: 1px solid {c['card_border']};
    border-radius: 10px;
    padding: 8px 18px;
    font-size: 12.5px;
}}
QPushButton#GhostBtn:hover {{
    background: {c['nav_hover']};
    border-color: rgba(139, 92, 246, 0.5);
}}
QPushButton#GhostBtn:disabled {{
    color: {c['text_faint']};
}}
QPushButton#DangerBtn {{
    background: rgba(230, 60, 80, 0.16);
    color: {c['danger']};
    border: 1px solid rgba(230, 60, 80, 0.4);
    border-radius: 10px;
    padding: 8px 18px;
}}
QPushButton#DangerBtn:hover {{
    background: rgba(230, 60, 80, 0.28);
}}
QPushButton#OkBtn {{
    background: rgba(80, 200, 120, 0.16);
    color: {c['ok']};
    border: 1px solid rgba(80, 200, 120, 0.4);
    border-radius: 10px;
    padding: 8px 18px;
}}
QPushButton#OkBtn:hover {{
    background: rgba(80, 200, 120, 0.26);
}}

/* ===== 输入控件 ===== */
QLineEdit, QSpinBox, QComboBox {{
    background: {c['input_bg']};
    border: 1px solid {c['card_border']};
    border-radius: 10px;
    padding: 8px 12px;
    color: {c['text']};
    selection-background-color: {c['accent2']};
    min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {c['accent2']};
}}
QLineEdit::placeholder {{
    color: {c['text_faint']};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {c['text_dim']};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background: {c['menu_bg']};
    border: 1px solid {c['card_border']};
    border-radius: 10px;
    selection-background-color: {c['accent']};
    padding: 4px;
}}

/* ===== 列表 ===== */
QListWidget, QListWidget#VersionList {{
    background: transparent;
    border: none;
}}
QListWidget::item {{
    background: {c['card']};
    border: 1px solid {c['card_border']};
    border-radius: 12px;
    padding: 10px 14px;
    margin: 3px 0;
}}
QListWidget::item:hover {{
    background: {c['card_hover']};
}}
QListWidget::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(103, 80, 164, 0.45), stop:1 rgba(139, 92, 246, 0.45));
    border: 1px solid {c['accent2']};
}}

/* ===== 进度条 ===== */
QProgressBar {{
    background: {c['track_bg']};
    border: none;
    border-radius: 7px;
    min-height: 10px;
    max-height: 10px;
    text-align: center;
    font-size: 9px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent']}, stop:1 {c['accent2']});
    border-radius: 7px;
}}

/* ===== 文本区 / 日志 ===== */
QPlainTextEdit {{
    background: {c['code_bg']};
    border: 1px solid {c['card_border']};
    border-radius: 12px;
    color: {c['code_text']};
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11.5px;
    padding: 8px;
}}
QPlainTextEdit[logLevel="error"] {{
    color: {c['danger']};
}}

/* ===== Tab 页（游戏库资源分区） ===== */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {c['text_dim']};
    border: none;
    padding: 8px 20px;
    margin-right: 6px;
    border-radius: 12px;
    font-size: 13px;
}}
QTabBar::tab:hover {{
    background: {c['card_hover']};
    color: {c['text']};
}}
QTabBar::tab:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: white;
    font-weight: 600;
}}

/* ===== 首页功能入口卡片 ===== */
QPushButton#EntryCard {{
    background: {c['card']};
    border: 1px solid {c['card_border']};
    border-radius: 16px;
    padding: 14px 16px;
    text-align: left;
    color: {c['text']};
}}
QPushButton#EntryCard:hover {{
    background: {c['card_hover']};
    border-color: rgba(139, 92, 246, 0.55);
}}
QPushButton#EntryCard:pressed {{
    background: rgba(103, 80, 164, 0.35);
}}
QPushButton#EntryCard QLabel#EntryIcon {{
    font-size: 24px;
    background: transparent;
}}
QPushButton#EntryCard QLabel#EntryName {{
    font-size: 14px;
    font-weight: 600;
    color: {c['text']};
    background: transparent;
}}
QPushButton#EntryCard QLabel#EntryDesc {{
    font-size: 11px;
    color: {c['text_faint']};
    background: transparent;
}}

/* ===== 滚动条 ===== */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(139, 92, 246, 0.35);
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(139, 92, 246, 0.6);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(139, 92, 246, 0.35);
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ===== 开关（设置页用简单 CheckBox 美化） ===== */
QCheckBox {{
    color: {c['text']};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {c['card_border']};
    background: {c['input_bg']};
}}
QCheckBox::indicator:checked {{
    background: {c['accent2']};
    border-color: {c['accent2']};
    image: none;
}}
QCheckBox::indicator:hover {{
    border-color: {c['accent2']};
}}

/* ===== 分割线 ===== */
QFrame#Divider {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(190,170,255,0), stop:0.2 rgba(190,170,255,0.35),
        stop:0.8 rgba(190,170,255,0.35), stop:1 rgba(190,170,255,0));
    min-height: 1px;
    max-height: 1px;
}}
"""
