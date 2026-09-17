# -*- coding: utf-8 -*-
"""主题样式与基础控件：调色板、全局 QSS、应用图标、游戏卡片绘制、状态胶囊。

本模块只负责"看起来怎样"（配色 / 样式 / 绘制），不含任何业务逻辑：
不读写数据库、不发网络请求、不改变任何界面交互流程。
"""

import os
import re
from string import Template

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRect, QRectF, QSize, QSizeF, Signal,
)
from PySide6.QtGui import (
    QPixmap, QIcon, QFont, QFontMetrics, QImage, QPainter, QColor, QPainterPath,
    QPen, QPalette, QLinearGradient, QRadialGradient, QBrush,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QToolButton,
    QLabel, QLineEdit, QSlider, QPushButton, QStyledItemDelegate, QStyle, QFrame,
    QLayout,
)

import config
from config import (
    get_theme, set_theme, accent_color, accent_hover, accent_soft,
    get_accent_override,
    get_bg_image, to_abs, fmt_rating, APP_ICON_PNG, APP_ICON_ICO,
)
from theme_manager import theme_manager, readable_text, readable_gradient_text


# ============================================================
# 调色板：深色（默认视觉规范）/ 浅色（配套版本）
# 全部为 #RRGGBB；需要透明度时用下面的 _rgba / pcolor 计算
# ============================================================
PALETTE_DARK = {
    "bg": "#14151C",           # 主背景
    "sidebar": "#181923",      # 侧边栏
    "card": "#20212D",         # 卡片
    "card_hover": "#262736",   # 卡片悬停/选中
    "cover_bg": "#262736",     # 封面留白底色
    "input": "#1C1D27",        # 输入框
    "menu": "#1B1C26",         # 菜单/下拉
    "row": "#1B1C26",          # 列表/表格底
    "header": "#1B1C26",       # 表头
    "btn": "#232433",          # 普通按钮
    "btn_hover": "#2A2B3B",
    "btn_press": "#1D1E29",
    "btn_disabled": "#1A1B24",
    "text": "#F5F5F7",         # 主文字
    "muted": "#A1A1AA",        # 次要文字
    "muted2": "#C2C2CD",       # 半透明侧边栏上的次要文字（比 muted 亮一档，保证对比度）
    "accent2": "#A99BFF",      # 辅助紫
    "pink": "#F19BC8",         # 樱花粉
    "blue": "#82B8FF",         # 淡蓝
    "danger": "#FF6B6B",       # 危险色（删除类操作）
    "track": "#3A3B49",        # 开关轨道
    # 半透明元素（颜色 + 透明度分开存，QSS 与 QColor 都好用）
    "border": "#FFFFFF", "border_a": 0.08,
    "border_soft": "#FFFFFF", "border_soft_a": 0.05,
    "glass": "#FFFFFF", "glass_a": 0.06,
    "chip": "#FFFFFF", "chip_a": 0.07,
    "grid_line": "#FFFFFF", "grid_line_a": 0.06,
    "scrollbar": "#FFFFFF", "scrollbar_a": 0.16,
    "scrollbar_hover": "#FFFFFF", "scrollbar_hover_a": 0.28,
    "disabled": "#F5F5F7", "disabled_a": 0.32,
    "shadow": "#000000", "shadow_a": 0.45,
    # 毛玻璃面板的不透明度（配合整窗背景图形成"顶部透明 → 往下毛玻璃"）
    "panel_a": 0.68, "sidebar_a": 0.70, "bubble_a": 0.86,
}

PALETTE_LIGHT = {
    "bg": "#F2F2F7",
    "sidebar": "#FFFFFF",
    "card": "#FFFFFF",
    "card_hover": "#F7F6FE",
    "cover_bg": "#EFEFF6",
    "input": "#FFFFFF",
    "menu": "#FFFFFF",
    "row": "#FFFFFF",
    "header": "#F4F3FA",
    "btn": "#FFFFFF",
    "btn_hover": "#F1F0FA",
    "btn_press": "#E6E4F5",
    "btn_disabled": "#EFEFF4",
    "text": "#1C1B22",
    "muted": "#6E6E7E",
    "muted2": "#4C4C58",       # 半透明侧边栏上的次要文字（比 muted 深一档，保证对比度）
    "accent2": "#A99BFF",
    "pink": "#EF8CBE",
    "blue": "#6FA8F5",
    "danger": "#D93B3B",
    "track": "#D5D5E0",
    "border": "#14151C", "border_a": 0.10,
    "border_soft": "#14151C", "border_soft_a": 0.06,
    "glass": "#14151C", "glass_a": 0.03,
    "chip": "#14151C", "chip_a": 0.05,
    "grid_line": "#14151C", "grid_line_a": 0.06,
    "scrollbar": "#14151C", "scrollbar_a": 0.18,
    "scrollbar_hover": "#14151C", "scrollbar_hover_a": 0.30,
    "disabled": "#1C1B22", "disabled_a": 0.30,
    "shadow": "#14151C", "shadow_a": 0.18,
    "panel_a": 0.76, "sidebar_a": 0.76, "bubble_a": 0.90,
}


def is_dark() -> bool:
    """当前是否深色模式（由 ThemeManager 解析 system 后得到）。"""
    try:
        return bool(theme_manager.is_dark)
    except Exception:
        return get_theme() == "dark"


def pal() -> dict:
    """返回当前主题的完整调色板（9 套主题经 ThemeManager 派生）。"""
    try:
        return theme_manager.palette
    except Exception:
        return PALETTE_DARK if is_dark() else PALETTE_LIGHT


def _rgba(hex_color: str, alpha: float) -> str:
    """把 #RRGGBB 转成 QSS 用的 rgba(...) 字符串。"""
    try:
        h = str(hex_color).lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "rgba(%d,%d,%d,%s)" % (r, g, b, ("%.3f" % alpha).rstrip("0").rstrip("."))
    except Exception:
        return str(hex_color)


def pcolor(key: str, alpha_key: str = None) -> QColor:
    """取调色板颜色为 QColor，可附带给定透明度键。"""
    p = pal()
    c = QColor(p.get(key, "#FFFFFF"))
    if alpha_key and alpha_key in p:
        c.setAlphaF(float(p[alpha_key]))
    return c


def pstr(key: str, alpha_key: str = None) -> str:
    """取调色板颜色为 QSS 字符串，可附带给定透明度键。"""
    p = pal()
    if alpha_key and alpha_key in p:
        return _rgba(p.get(key, "#FFFFFF"), float(p[alpha_key]))
    return str(p.get(key, "#FFFFFF"))


def glass_alpha(kind: str = "panel") -> float:
    """毛玻璃面板的底色不透明度（panel / sidebar / bubble）。"""
    return float(pal().get("%s_a" % kind, 0.72))


# ============================================================
# 游戏状态配色（纯展示映射，不改动数据库中的状态值）
# ============================================================
STATUS_COLORS = {
    "通关": "#F19BC8",     # 已通关 → 樱花粉紫
    "正在玩": "#82B8FF",   # 进行中 → 淡蓝
    "想玩": "#A99BFF",     # 想玩   → 辅助紫
    "搁置": "#A1A1AA",
    "放弃": "#A1A1AA",
}


def status_color(status: str) -> str:
    """按状态取标签颜色（未匹配到时用辅助紫）。"""
    return STATUS_COLORS.get(str(status or ""), "#A99BFF")


# ============================================================
# 卡片数据角色（网格项附加的展示信息；0 号仍是 game_id，绝不能改）
# ============================================================
ROLE_GAME_ID = Qt.UserRole
ROLE_STATUS = Qt.UserRole + 1
ROLE_RATING = Qt.UserRole + 2
ROLE_DEVELOPER = Qt.UserRole + 3
ROLE_YEAR = Qt.UserRole + 4
ROLE_TITLE = Qt.UserRole + 5
ROLE_COVER = Qt.UserRole + 6
ROLE_FAVORITE = Qt.UserRole + 7
ROLE_TAGS = Qt.UserRole + 8


# ============================================================
# 应用图标工具
# ============================================================
def app_icon() -> QIcon:
    """应用窗口/任务栏图标（优先用多尺寸 .ico，其次 png）。"""
    for path in (APP_ICON_ICO, APP_ICON_PNG):
        if os.path.isfile(path):
            return QIcon(path)
    return QIcon()


def app_icon_pixmap(size: int, radius: int = 0) -> QPixmap:
    """取一张 size×size 的应用图标位图，可加圆角（用于侧边栏 Logo）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    src = QPixmap("")
    for path in (APP_ICON_PNG, APP_ICON_ICO):
        if os.path.isfile(path):
            src = QPixmap(path)
            if not src.isNull():
                break
    if src.isNull():
        return pm
    scaled = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    if radius > 0:
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
        p.setClipPath(clip)
    p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return pm


def cover_pixmap(rel_path: str, w: int, h: int) -> QPixmap:
    """卡片封面：等比放大填满 + 居中裁切（复用 config 里已有的图片工具）。

    会按屏幕缩放比例（高 DPI）解码，保证 150%/200% 缩放下封面依然清晰。
    """
    try:
        app = QApplication.instance()
        dpr = float(app.primaryScreen().devicePixelRatio()) if app is not None else 1.0
    except Exception:
        dpr = 1.0
    dpr = max(1.0, min(3.0, dpr))
    pw, ph = int(round(w * dpr)), int(round(h * dpr))
    abs_path = to_abs(rel_path) if rel_path else ""
    pm = QPixmap()
    if abs_path and os.path.isfile(abs_path):
        try:
            pm = config._load_pix_cover(abs_path, pw, ph)
        except Exception:
            pm = QPixmap()
    if pm.isNull():
        pm = config.make_placeholder_pixmap(pw, ph, "无封面")
    pm.setDevicePixelRatio(dpr)
    return pm


def rounded_pixmap(pm: QPixmap, radius: int) -> QPixmap:
    """把位图裁成圆角（用于详情页大封面、头像/预设缩略图等）。

    ⚠️ 高 DPI 下这里有坑（2026-09 修复）：
    `cover_pixmap()` 返回的是"设备像素尺寸 + devicePixelRatio"的位图
    （例如 150% 缩放下请求 104×64，拿到的是 156×96 且 dpr=1.5）。
    这种位图一旦画到**还没设 dpr 的画布**上，QPainter 会按"逻辑尺寸"画，
    也就是只画满左上角 104×64 那一块、其余全透明 —— 表现就是
    "缩略图/封面没填满，图片缩在左上角、只有 2/3 大"。
    所以顺序必须是：**先 setDevicePixelRatio，再开 QPainter 画**。
    注意设了 dpr 之后 QPainter 用的是**逻辑坐标**，
    所以裁剪矩形和圆角半径都要按"逻辑尺寸"给（pm.width()/dpr）。
    """
    if pm is None or pm.isNull():
        return pm
    dpr = pm.devicePixelRatio()
    if dpr <= 0:
        dpr = 1.0
    out = QPixmap(pm.size())
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, pm.width() / dpr, pm.height() / dpr), radius, radius)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


def rounded_cover_pixmap(rel_path: str, w: int, h: int, radius: int = 14) -> QPixmap:
    """详情页用：填满裁切 + 圆角的封面。"""
    return rounded_pixmap(cover_pixmap(rel_path, w, h), radius)


# ============================================================
# 整窗背景层（清晰层 + 毛玻璃层）
#
#   绘制层次（自下往上）：
#     1. MainWindow.paintEvent 画"清晰层"（整窗铺满，含压暗/提亮）
#     2. 侧边栏 / 主面板 / 助手气泡 各自按自己在窗口里的位置，
#        从缓存的"毛玻璃层 / 清晰层"里取对应区域绘制 → 形成毛玻璃层次
#   没有任何图片可画时用程序生成的渐变兜底，保证层次依旧存在。
# ============================================================
def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
    """按比例混合两个颜色（t=0 取 c1，t=1 取 c2）。"""
    t = max(0.0, min(1.0, float(t)))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


def _fallback_backdrop_image(w: int, h: int, dark: bool) -> QImage:
    """没有背景图时的兜底背景：主题色渐变 + 两团柔光（保证层次感）。"""
    w, h = max(1, int(w)), max(1, int(h))
    img = QImage(w, h, QImage.Format_ARGB32)
    bg = QColor(pstr("bg"))
    ac = QColor(accent_color())
    top = _mix(bg, ac, 0.42 if dark else 0.26)
    mid = _mix(bg, ac, 0.18 if dark else 0.10)
    bot = QColor(bg).darker(118) if dark else QColor(bg)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0.0, top)
    g.setColorAt(0.52, mid)
    g.setColorAt(1.0, bot)
    p.fillRect(img.rect(), g)
    for fx, fy, fr, col, a in ((0.16, 0.04, 0.62, pstr("pink"), 0.20),
                               (0.86, 0.00, 0.58, accent_color(), 0.22)):
        c = QColor(col)
        c.setAlphaF(a if dark else a * 0.72)
        c2 = QColor(col)
        c2.setAlphaF(0.0)
        rg = QRadialGradient(QPointF(w * fx, h * fy), max(w, h) * fr)
        rg.setColorAt(0.0, c)
        rg.setColorAt(1.0, c2)
        p.fillRect(img.rect(), QBrush(rg))
    p.end()
    return img


def blur_pixmap(pm: QPixmap, level: int = 14) -> QPixmap:
    """毛玻璃用的快速模糊：两次降采样后用平滑插值放大回来。"""
    if pm is None or pm.isNull():
        return pm
    w, h = pm.width(), pm.height()
    if w < 4 or h < 4:
        return pm
    lv = max(3, int(level))
    small = pm.scaled(max(1, w // lv), max(1, h // lv),
                      Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = small.scaled(max(1, small.width() // 2), max(1, small.height() // 2),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out.setDevicePixelRatio(pm.devicePixelRatio())
    return out


def build_backdrop(src_path: str, w: int, h: int, dark: bool, dpr: float = 1.0):
    """兼容旧签名：把背景预处理委托给 ThemeManager（含 15% 压暗 + 遮罩缓存）。"""
    return theme_manager.render_backdrop_for_source(src_path, w, h, dpr, dark)


class GlassSurface(QWidget):
    """半透明 / 毛玻璃面板。

    背景不是自己贴图，而是按"自己在窗口中的位置"从主窗口缓存的背景层里取对应
    区域绘制，因此面板边缘与整窗背景严丝合缝，视觉上像是同一张壁纸被一块玻璃
    压住 —— 顶部背景图照常透出，面板区域变成毛玻璃。

    参数（都可在构造后通过 set_glass 调整）：
        blur      : True 取毛玻璃层，False 取清晰层（更通透，适合侧边栏）
        alpha     : 底色不透明度（0~1），越大越不透
        tint_key  : 底色取自调色板的哪个键（默认 bg / 可传 sidebar）
        radius    : 圆角半径
        corners   : 需要倒圆的角，字符串里含 tl/tr/bl/br
        edge_top  : 顶部画一条 1px 高光描边
        edge_right: 右侧画一条分隔线
    """

    def __init__(self, parent=None, *, name: str = "", blur: bool = True,
                 alpha: float = 0.72, tint_key: str = "bg", radius: int = 0,
                 corners: str = "", edge_top: bool = False,
                 edge_right: bool = False):
        super().__init__(parent)
        if name:
            self.setObjectName(name)
        self._g_blur = bool(blur)
        self._g_alpha = float(alpha)
        self._g_tint = tint_key
        self._g_radius = int(radius)
        self._g_corners = str(corners or "")
        self._g_edge_top = bool(edge_top)
        self._g_edge_right = bool(edge_right)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_glass(self, **kw):
        """更新外观参数（主题/强调色变化后调用），并触发重绘。"""
        m = {"blur": "_g_blur", "alpha": "_g_alpha", "tint_key": "_g_tint",
             "radius": "_g_radius", "corners": "_g_corners",
             "edge_top": "_g_edge_top", "edge_right": "_g_edge_right"}
        for k, v in kw.items():
            if k in m:
                setattr(self, m[k], v)
        self.update()

    def _shape(self) -> QPainterPath:
        r = QRectF(self.rect())
        rad = float(self._g_radius)
        c = self._g_corners
        if rad <= 0 or not c:
            path = QPainterPath()
            path.addRect(r)
            return path
        tl, tr = "tl" in c, "tr" in c
        bl, br = "bl" in c, "br" in c
        path = QPainterPath()
        path.moveTo(r.left() + (rad if tl else 0), r.top())
        path.lineTo(r.right() - (rad if tr else 0), r.top())
        if tr:
            path.quadTo(r.right(), r.top(), r.right(), r.top() + rad)
        path.lineTo(r.right(), r.bottom() - (rad if br else 0))
        if br:
            path.quadTo(r.right(), r.bottom(), r.right() - rad, r.bottom())
        path.lineTo(r.left() + (rad if bl else 0), r.bottom())
        if bl:
            path.quadTo(r.left(), r.bottom(), r.left(), r.bottom() - rad)
        path.lineTo(r.left(), r.top() + (rad if tl else 0))
        if tl:
            path.quadTo(r.left(), r.top(), r.left() + rad, r.top())
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        path = self._shape()
        painter.setClipPath(path)

        win = self.window()
        pm = getattr(win, "_bd_blur" if self._g_blur else "_bd_sharp", None)
        if pm is not None and not pm.isNull():
            origin = self.mapTo(win, QPoint(0, 0))     # 面板在窗口里的位置
            painter.drawPixmap(-origin.x(), -origin.y(), pm)

        tint = pcolor(self._g_tint)
        tint.setAlphaF(max(0.0, min(1.0, self._g_alpha)))
        painter.fillPath(path, tint)
        painter.setClipping(False)

        r = QRectF(self.rect())
        if self._g_edge_top:
            pen = QPen(pcolor("border", "border_a"))
            painter.setPen(pen)
            y = r.top() + 0.5
            painter.drawLine(QPointF(r.left() + self._g_radius, y),
                             QPointF(r.right() - self._g_radius, y))
        if self._g_edge_right:
            painter.setPen(QPen(pcolor("border_soft", "border_soft_a")))
            x = r.right() - 0.5
            painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))


def faded_bg_path(src_path: str, alpha: float = 0.16, cover_size=None) -> str:
    """把背景图按 alpha 淡化后缓存为一份 PNG，返回可供 QSS 引用的路径。

    只做"显示用"的淡化副本（缓存在系统临时目录），不改动原图；
    这样即使用户选了很抢眼的动漫图，也不会盖住界面上的文字。
    """
    import hashlib
    import tempfile
    try:
        st = os.stat(src_path)
        raw = "%s|%d|%.3f|%s" % (src_path, int(st.st_mtime), alpha, cover_size)
        key = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()[:16]
    except Exception:
        key = "default"
    out = os.path.join(tempfile.gettempdir(), "galgame_memoir_bg_%s.png" % key)
    if os.path.isfile(out):
        return out
    img = QImage(src_path)
    if img.isNull():
        return src_path
    if cover_size:
        tw_, th_ = int(cover_size[0]), int(cover_size[1])
        if tw_ > 0 and th_ > 0:
            img = img.scaled(tw_, th_, Qt.KeepAspectRatioByExpanding,
                             Qt.SmoothTransformation)
            if img.width() > tw_ or img.height() > th_:
                img = img.copy(max(0, (img.width() - tw_) // 2),
                               max(0, (img.height() - th_) // 2), tw_, th_)
    elif img.width() > 1920:
        img = img.scaledToWidth(1920, Qt.SmoothTransformation)
    img = img.convertToFormat(QImage.Format_ARGB32)
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.fillRect(img.rect(), QColor(0, 0, 0, max(0, min(255, int(255 * alpha)))))
    p.end()
    try:
        img.save(out, "PNG")
        return out
    except Exception:
        return src_path


# ============================================================
# 全局样式表
# ============================================================
_QSS_TEMPLATE = """
* { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }
QWidget { color: @TEXT; }
QMainWindow, QDialog { background-color: @BG; }
/* 右侧主区域整体透明：露出 MainWindow 画的整窗背景图（顶部即"透明"效果） */
QWidget#contentRoot, QSplitter { background-color: transparent; }
/* 侧边栏 / 主面板 / 助手气泡的底色与毛玻璃由 theme.GlassSurface 自己绘制 */
QWidget#sidebar { background-color: transparent; border: none; }
/* 侧边栏滚动区 + 内容层都要透明，玻璃底色由 theme.GlassSurface 画 */
QWidget#sideScroll, QWidget#sideContent { background-color: transparent; border: none; }
QFrame#topbar { background-color: transparent; border: none; }
QWidget#glassPanel { background-color: transparent; border: none; }
QLabel#pageTitle { font-size: 21px; font-weight: 700; color: @TEXT; }
/* 侧边栏导航项（游戏库 / 收藏）：主窗口里这两个是 QPushButton，
   选择器必须写成 QPushButton#... —— 写成 QLabel#... 不会命中，
   两项都会退回通用按钮样式，且看不出哪个是当前项。 */
QPushButton#navItem, QPushButton#navItemActive {
    background: transparent; border: none; text-align: left;
    color: @MUTED; font-size: 13px; padding: 9px 12px; border-radius: 10px; }
QPushButton#navItem:hover { background: @GLASS; color: @TEXT; }
QPushButton#navItemActive {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 @GRAD_1_SOFT, stop:1 @GRAD_2_SOFT);
    color: @TEXT; font-weight: 600; }
QPushButton#navItemActive:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 @GRAD_1_SOFT, stop:1 @GRAD_2_SOFT); }
QWidget#statusList { background: transparent; }
QLabel#statusRowText { font-size: 12px; }
QLabel#statusRowCount { color: @MUTED2; font-size: 11px; }
QLabel#avatarTile { border: 1px solid @BORDER; border-radius: 14px; }
QWidget#assistantBubble { background-color: transparent; border: none; }
QLabel#assistantText { color: @TEXT; font-size: 13px; }
QLabel#petPreview { background: @GLASS; border: 1px solid @BORDER_SOFT; border-radius: 10px;
    padding: 8px 12px; color: @TEXT; font-size: 12px; }
/* 设置页：分类标签页（不写这些会被系统默认样式画成白底浅色，和深色主题打架） */
QTabWidget#settingsTabs::pane { border: 1px solid @BORDER_SOFT; border-radius: 12px;
    background: @GLASS; top: -1px; }
QTabWidget#settingsTabs QTabBar { background: transparent; }
QTabWidget#settingsTabs QTabBar::tab { background: transparent; color: @MUTED; font-size: 13px;
    padding: 8px 18px; margin-right: 6px; border: 1px solid transparent; border-radius: 10px; }
QTabWidget#settingsTabs QTabBar::tab:hover { background: @GLASS; color: @TEXT; }
QTabWidget#settingsTabs QTabBar::tab:selected { background: @ACCENT_SOFT_BG; color: @TEXT;
    border-color: @ACCENT_LINE; font-weight: 600; }
QScrollArea#settingsTab, QWidget#settingsTabPage { background: transparent; border: none; }
QLabel#userImgPreview { background: @GLASS; border: 1px solid @BORDER_SOFT; border-radius: 14px;
    color: @MUTED; font-size: 10px; }
/* 桌宠气泡的关闭按钮：小圆点。底色/文字色由 MainWindow._apply_pet_bubble_style()
   按深浅主题下发（浅 rgba(shadow,.06) / 深 rgba(shadow,.20) + @MUTED2），
   这里只兜底字号与圆角，避免首次布局时闪成方角。 */
QToolButton#bubbleClose { color: @MUTED2; border-radius: 8px; font-size: 11px; }
QToolButton#bubbleClose:hover { color: @TEXT; }
/* 设置页：预设缩略图条（data/profile photo/ 与 data/wallpapers/ 里的图片）。
   注意：缩略图把整个按钮铺满了，靠底层 QToolButton:checked 的底色完全被图标挡住，
   所以"当前正在用"的高亮必须画在 border 上，不能只靠 background。 */
QScrollArea#presetStrip, QWidget#presetPage { background: transparent; border: none; }
QWidget#presetBox { background: transparent; border: none; }
QPushButton#presetRefresh { padding: 5px 8px; font-size: 11px; border-radius: 9px; }
QToolButton#presetBtn { background: transparent; border: 2px solid transparent;
    border-radius: 13px; padding: 0px; }
QToolButton#presetBtn:hover { border-color: @ACCENT_LINE; background: @GLASS; }
QToolButton#presetBtn:checked { border-color: @ACCENT; background: @ACCENT_SOFT_BG; }
QToolButton#accentSwatch { border-radius: 11px; border: 2px solid transparent; }
QToolButton#accentSwatch:hover { border-color: @ACCENT_LINE; }
QPushButton#pageNum { min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
    border-radius: 16px; padding: 0; }
QPushButton#pageNumActive { background: @ACCENT; color: @ON_ACCENT; border: none; font-weight: 700; }
QLineEdit#pillSearch { padding: 9px 16px; border-radius: 18px; font-size: 13px; }
/* 游戏详情：整页滚动区 + 截图"胶片带" */
QWidget#detailBody, QScrollArea#detailScroll { background: transparent; border: none; }
QListWidget#ssGrid { background: @GLASS; border: 1px solid @BORDER_SOFT; border-radius: 12px;
    padding: 6px; outline: 0; }
QListWidget#ssGrid::item { border-radius: 10px; padding: 4px; color: @MUTED; font-size: 11px; }
QListWidget#ssGrid::item:hover { background: @ACCENT_SOFT_BG; color: @TEXT; }
QListWidget#ssGrid::item:selected { background: @ACCENT_SOFT_BG; color: @TEXT; }
QLabel#ssEmpty { color: @MUTED; font-size: 12px; background: @GLASS;
    border: 1px dashed @BORDER; border-radius: 12px; }
QLabel { color: @TEXT; font-size: 12px; background: transparent; }
QLabel#app_brand { font-size: 15px; font-weight: 700; color: @TEXT; }
QLabel#app_sub { font-size: 10px; color: @MUTED; }
QLabel#appLogo {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 @GRAD_1, stop:1 @GRAD_2);
    border-radius: 12px; }
QLabel#pageTitle { font-size: 20px; font-weight: 700; color: @TEXT; }
QLabel#pageCount { font-size: 11px; color: @MUTED; }
QLabel#navActive { background: @ACCENT_SOFT_BG; color: @TEXT; border-radius: 10px;
    padding: 9px 12px; font-size: 13px; font-weight: 600; }
QLabel#pagerText { color: @MUTED; font-size: 12px; padding: 0 10px; }
QLabel#hint { color: @MUTED; font-size: 11px; }
QScrollArea { background: transparent; border: none; }
QScrollArea::viewport { background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QGroupBox { background: transparent; color: @TEXT; border: 1px solid @BORDER_SOFT;
    border-radius: 10px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: @MUTED; }
QSplitter::handle { background: transparent; width: 0px; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: @INPUT; color: @TEXT; border: 1px solid @BORDER;
    border-radius: 10px; padding: 6px 10px;
    selection-background-color: @ACCENT; selection-color: @ON_ACCENT;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid @ACCENT_LINE; }
QLineEdit#searchBox { padding: 8px 12px; border-radius: 12px; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background-color: @MENU; color: @TEXT;
    border: 1px solid @BORDER; border-radius: 10px; padding: 4px;
    selection-background-color: @ACCENT_SOFT_BG; selection-color: @TEXT; outline: 0; }
QListWidget, QTableWidget, QTableView { background-color: @ROW; color: @TEXT;
    border: 1px solid @BORDER_SOFT; border-radius: 12px; }
QListWidget::item { color: @TEXT; padding: 2px; }
QListWidget::item:selected { background-color: @ACCENT_SOFT_BG; color: @TEXT; }
QListWidget#gameGrid { background: transparent; border: none; outline: 0; }
QListWidget#gameGrid::item { background: transparent; border: none; }
QListWidget#gameGrid::item:selected, QListWidget#gameGrid::item:hover { background: transparent; }
QTableWidget { gridline-color: @GRID_LINE; }
QTableWidget::item { padding: 2px 4px; }
QTableWidget::item:selected { background-color: @CARD_HOVER; color: @TEXT; }
QHeaderView::section { background-color: @HEADER; color: @MUTED; border: none;
    border-bottom: 1px solid @BORDER_SOFT; padding: 6px 8px; }
QHeaderView::section:vertical { background-color: @HEADER; color: @MUTED; border: none;
    border-right: 1px solid @BORDER_SOFT; padding: 2px 6px; }
QTableWidget::corner { background-color: @HEADER; border: none; }
QMenuBar, QMenu { background-color: @MENU; color: @TEXT; }
QMenu { border: 1px solid @BORDER; border-radius: 12px; padding: 5px; }
QMenu::item { padding: 7px 20px 7px 14px; border-radius: 7px; margin: 1px 2px; }
QMenu::item:selected { background-color: @ACCENT_SOFT_BG; color: @TEXT; }
QMenu::separator { height: 1px; background: @BORDER_SOFT; margin: 5px 10px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 4px; }
QScrollBar::handle { background: @SCROLLBAR; border-radius: 5px; min-height: 28px; min-width: 28px; }
QScrollBar::handle:hover { background: @SCROLLBAR_HOVER; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QToolTip { background-color: @MENU; color: @TEXT; border: 1px solid @BORDER;
    border-radius: 8px; padding: 6px 8px; }
QProgressBar { background-color: @INPUT; border: 1px solid @BORDER_SOFT;
    border-radius: 8px; text-align: center; color: @TEXT; }
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 @GRAD_1, stop:1 @GRAD_2);
    border-radius: 8px; }
QPushButton { background-color: @BTN; color: @TEXT; border: 1px solid @BORDER_SOFT;
    border-radius: 10px; padding: 7px 14px; }
QPushButton:hover { background-color: @BTN_HOVER; border-color: @ACCENT_LINE; }
QPushButton:pressed { background-color: @BTN_PRESS; }
QPushButton:disabled { color: @DISABLED; background-color: @BTN_DISABLED; border-color: @BORDER_SOFT; }
QPushButton:checked { background-color: @ACCENT_SOFT_BG; border-color: @ACCENT_LINE; color: @TEXT; }
QPushButton#add_btn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 @GRAD_1, stop:1 @GRAD_2);
    color: @ON_GRAD; padding: 9px; border: none; border-radius: 10px; font-weight: 700; }
QPushButton#add_btn:hover { background: @ACCENT_HOVER; color: @ON_ACCENT; }
QPushButton#batch_btn, QPushButton#settings_btn, QPushButton#identify_btn,
QPushButton#random_cg_btn {
    background: @GLASS; color: @TEXT; padding: 9px 12px; border-radius: 10px;
    border: 1px solid @BORDER_SOFT; text-align: left; }
QPushButton#batch_btn:hover, QPushButton#settings_btn:hover, QPushButton#identify_btn:hover,
QPushButton#random_cg_btn:hover {
    background: @ACCENT_SOFT_BG; border-color: @ACCENT_LINE; }
QPushButton#pagerBtn { min-width: 36px; max-width: 36px; min-height: 32px; max-height: 32px;
    border-radius: 18px; padding: 0; font-size: 15px; }
QPushButton#dangerItem { background: transparent; color: @DANGER; border: none;
    border-radius: 8px; padding: 7px 14px; font-size: 12px; text-align: left; }
QPushButton#dangerItem:hover { background: @DANGER_SOFT; }
QToolButton { background-color: transparent; color: @TEXT; border: 1px solid transparent;
    border-radius: 8px; }
QToolButton:hover { background-color: @GLASS; }
QToolButton:checked { background-color: @ACCENT_SOFT_BG; }
QSlider::groove:horizontal { background: @BORDER; height: 6px; border-radius: 3px; }
QSlider::sub-page:horizontal { background: @ACCENT; border-radius: 3px; }
QSlider::add-page:horizontal { background: @BORDER; border-radius: 3px; }
QSlider::handle:horizontal { background: @ON_ACCENT; border: 2px solid @ACCENT;
    width: 14px; height: 14px; margin: -6px 0; border-radius: 9px; }
QCheckBox, QRadioButton { color: @TEXT; spacing: 6px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px;
    border-radius: 4px; border: 1px solid @BORDER; background: @INPUT; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: @ACCENT; border-color: @ACCENT; }
QDialogButtonBox QPushButton { min-width: 78px; }
QStatusBar { background: @SIDEBAR; color: @MUTED; }
QFrame#heroCard { background: @GLASS; border: 1px solid @BORDER_SOFT; border-radius: 16px; }
QFrame#sectionCard { background: @GLASS; border: 1px solid @BORDER_SOFT; border-radius: 14px; }
QLabel#sectionTitle { font-size: 13px; font-weight: 700; color: @TEXT; }
QLabel#sectionHint { color: @MUTED; font-size: 11px; }
QLabel#heroTitle { font-size: 20px; font-weight: 700; color: @TEXT; }
QLabel#heroSub { color: @MUTED; font-size: 12px; }
QLabel#kvKey { color: @MUTED; font-size: 12px; }
QLabel#kvValue { color: @TEXT; font-size: 12px; }
QLabel#chip { background: @CHIP; color: @TEXT; border-radius: 10px;
    padding: 3px 10px; font-size: 11px; }
QLabel#dropZone { background: @GLASS; border: 2px dashed @BORDER; border-radius: 14px;
    color: @MUTED; font-size: 13px; padding: 16px; }
QLabel#starLabel { color: @ACCENT2; font-size: 13px; font-weight: 700; }
QScrollArea#settingsScroll { background: transparent; }
"""


class _AtTemplate(Template):
    """保留现有 @TOKEN 写法，用 string.Template 做 QSS 变量注入。"""
    delimiter = "@"


def _qss_tokens() -> dict:
    """把调色板 + 当前强调色翻译成 QSS 占位符。"""
    ac = accent_color()
    if get_accent_override():
        # 用户手选强调色时，主渐变也跟随覆盖色，保证旧“主题色”功能仍然直观。
        g1 = accent_color()
        g2 = accent_hover()
    else:
        g1 = pstr("gradient_start")
        g2 = pstr("gradient_end")
    on_ac = readable_text(ac)
    on_grad = readable_gradient_text(g1, g2)
    return {
        "@BG": pstr("bg"),
        "@SIDEBAR": pstr("sidebar"),
        "@CARD": pstr("card"),
        "@CARD_HOVER": pstr("card_hover"),
        "@INPUT": pstr("input"),
        "@MENU": pstr("menu"),
        "@ROW": pstr("row"),
        "@HEADER": pstr("header"),
        "@TEXT": pstr("text"),
        "@MUTED": pstr("muted"),
        "@MUTED2": pstr("muted2"),
        "@BORDER": pstr("border", "border_a"),
        "@BORDER_SOFT": pstr("border_soft", "border_soft_a"),
        "@GLASS": pstr("glass", "glass_a"),
        "@CHIP": pstr("chip", "chip_a"),
        "@GRID_LINE": pstr("grid_line", "grid_line_a"),
        "@SCROLLBAR": pstr("scrollbar", "scrollbar_a"),
        "@SCROLLBAR_HOVER": pstr("scrollbar_hover", "scrollbar_hover_a"),
        "@DISABLED": pstr("disabled", "disabled_a"),
        "@BTN": pstr("btn"),
        "@BTN_HOVER": pstr("btn_hover"),
        "@BTN_PRESS": pstr("btn_press"),
        "@BTN_DISABLED": pstr("btn_disabled"),
        "@ACCENT": ac,
        "@ACCENT_HOVER": accent_hover(),
        "@ACCENT2": g2,
        "@ACCENT_LINE": _rgba(ac, 0.55),
        "@ACCENT_SOFT_BG": _rgba(ac, 0.18),
        "@GRAD_1": g1,
        "@GRAD_2": g2,
        "@GRAD_1_SOFT": _rgba(g1, 0.20),
        "@GRAD_2_SOFT": _rgba(g2, 0.16),
        "@ON_ACCENT": on_ac,
        "@ON_GRAD": on_grad,
        "@PINK": pstr("pink"),
        "@BLUE": pstr("blue"),
        "@DANGER": pstr("danger"),
        "@DANGER_SOFT": _rgba(pstr("danger"), 0.16),
        # 毛玻璃层次：面板底色由 theme.GlassSurface 用 glass_alpha() 现算，
        # 这里只给 QSS 用的"最外层底色"，没有背景图时也不会露出白/黑块。
        "@BG_GLASS": _rgba(pstr("bg"), glass_alpha("panel")),
        "@SIDEBAR_GLASS": _rgba(pstr("sidebar"), glass_alpha("sidebar")),
        "@TOP_GLASS": "transparent",
    }


def _apply_theme():
    """应用当前主题的全局样式表（string.Template 注入，不硬编码颜色）。"""
    app = QApplication.instance()
    if app is None:
        return
    tokens = {k[1:]: v for k, v in _qss_tokens().items() if k.startswith("@")}
    qss = _AtTemplate(_QSS_TEMPLATE).safe_substitute(tokens)
    app.setStyleSheet(qss)


def _apply_bg():
    """把自定义背景图应用为"整窗背景层"（主窗口自己重画清晰层 + 毛玻璃层）。"""
    from widgets import MainWindow  # 延迟导入避免循环
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        if isinstance(w, MainWindow):
            refresh = getattr(w, "refresh_backdrop", None)
            if callable(refresh):
                refresh()
            grid = getattr(w, "grid", None)
            if grid is not None:
                grid.setStyleSheet("")      # 网格本身不贴图，背景统一由整窗背景层负责
            break


def _on_theme_manager_changed(*_args):
    """ThemeManager 发出主题变化：重载 QSS，并刷新所有顶层窗口。"""
    _apply_theme()
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        try:
            w.update()
        except Exception:
            pass


# 主题/配色变化 -> 重载 QSS；背景变化 -> 通知主窗口重画背景层。
theme_manager.themeChanged.connect(_on_theme_manager_changed)
theme_manager.backgroundChanged.connect(_apply_bg)


def make_secure_row(edit: "QLineEdit") -> "QWidget":
    """把输入框包成一行：默认密文显示，右侧带眼睛图标切换明文/密文。"""
    edit.setEchoMode(QLineEdit.Password)
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(edit, 1)
    eye = QToolButton()
    eye.setCheckable(True)
    eye.setToolTip("显示 / 隐藏")
    eye.setText("👁")
    eye.setFixedWidth(28)

    def _toggle(checked):
        edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    eye.toggled.connect(_toggle)
    lay.addWidget(eye)
    return row


class TopComboBox(QComboBox):
    """下拉列表固定在控件正下方、从顶部显示，避免“以当前选项为中心”上下晃动。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_combo_theme()

    def _apply_combo_theme(self):
        """应用主题到下拉弹窗（palette 方式，最可靠）。"""
        v = self.view()
        if v is None:
            return
        p = pal()
        bg = QColor(pstr("menu"))
        fg = QColor(pstr("text"))
        sel = QColor(accent_color())
        on_ac = readable_text(accent_color())
        sel_fg = QColor(on_ac)
        border_qss = pstr("border", "border_a")
        pal_ = v.palette()
        pal_.setColor(QPalette.Base, bg)
        pal_.setColor(QPalette.Window, bg)
        pal_.setColor(QPalette.Text, fg)
        pal_.setColor(QPalette.WindowText, fg)
        pal_.setColor(QPalette.Highlight, sel)
        pal_.setColor(QPalette.HighlightedText, sel_fg)
        pal_.setColor(QPalette.PlaceholderText, fg)
        v.setPalette(pal_)
        # 关键：下拉弹窗的外层容器（QFrame）也要上色，否则四周仍是默认色
        pop = v.parentWidget()
        if pop is not None:
            ppal = pop.palette()
            ppal.setColor(QPalette.Window, bg)
            ppal.setColor(QPalette.Base, bg)
            ppal.setColor(QPalette.Text, fg)
            ppal.setColor(QPalette.WindowText, fg)
            pop.setPalette(ppal)
            pop.setAutoFillBackground(True)
            # 去掉 Qt 弹窗容器默认的白色边框 / 阴影线
            try:
                pop.setFrameShape(QFrame.NoFrame)
                pop.setLineWidth(0)
                pop.setMidLineWidth(0)
            except Exception:
                pass
            pop.setStyleSheet(
                "QFrame { background: %s; border: none; }"
                "QListWidget, QListView { background: %s; color: %s; border: none; }"
                % (bg.name(), bg.name(), fg.name()))
        v.setStyleSheet(
            "QListView { background: %s; color: %s; border: none; border-radius: 8px; }"
            "QListView::item { padding: 5px 8px; }"
            "QListView::item:selected { background: %s; color: %s; }"
            % (bg.name(), fg.name(), sel.name(), on_ac))

    def showPopup(self):
        self._apply_combo_theme()
        super().showPopup()
        QTimer.singleShot(0, lambda: (self._apply_combo_theme(), self._place_below()))

    def _place_below(self):
        try:
            pop = self.view().parentWidget()
            if pop is None:
                return
            self.view().scrollToTop()
            pop.move(self.mapToGlobal(QPoint(0, self.height())))
        except Exception:
            pass


class PlainHeaderButton(QToolButton):
    """折叠标题按钮：跟随主题与强调色绘制，不依赖系统样式。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_Hover, True)
        f = self.font()
        f.setPointSize(11)
        f.setBold(True)
        self.setFont(f)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hovered = self.underMouse() or self.isDown()

        if hovered:
            c = QColor(accent_color())
            c.setAlpha(46)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

        color = pcolor("text")
        use = QColor(accent_hover()) if (self.underMouse() and not self.isDown()) else color
        p.setPen(use)
        p.setFont(self.font())

        rect = self.rect().adjusted(6, 0, -6, 0)
        arrow_area_w = 20
        # 箭头
        if self.arrowType() == Qt.DownArrow:
            px = rect.left() + 4
            py = rect.center().y() + 3
            path_arrow = QPainterPath()
            path_arrow.moveTo(px, py - 3)
            path_arrow.lineTo(px + 5, py - 3)
            path_arrow.lineTo(px + 2.5, py + 1)
            path_arrow.closeSubpath()
        else:
            px = rect.left() + 4
            py = rect.center().y()
            path_arrow = QPainterPath()
            path_arrow.moveTo(px, py - 3)
            path_arrow.lineTo(px + 2.5, py)
            path_arrow.lineTo(px, py + 3)
            path_arrow.closeSubpath()
        p.setBrush(use if hovered else pcolor("muted"))
        p.drawPath(path_arrow)

        # 文字
        text_rect = QRect(rect.left() + arrow_area_w, rect.top(),
                          rect.width() - arrow_area_w, rect.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


def draw_icon(painter, pixmap: "QPixmap", rect: "QRect", color: "QColor") -> None:
    """把一张透明背景的线条图标，按目标颜色重绘到 rect 内（保留透明度）。"""
    if pixmap is None or pixmap.isNull():
        return
    # 用 SourceIn 组合模式：把目标色填充到原图 alpha 形状内
    src = QImage(rect.size(), QImage.Format_ARGB32)
    src.fill(Qt.transparent)
    sp = QPainter(src)
    scaled = pixmap.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation).toImage()
    sp.drawImage(0, 0, scaled)
    sp.setCompositionMode(QPainter.CompositionMode_SourceIn)
    sp.fillRect(src.rect(), color)
    sp.end()
    painter.drawImage(rect, src)


def _load_icon(path: str, color: "QColor", bg_threshold: int = 190) -> "QPixmap":
    """从一张浅底深线的图标图，抠除背景并重着色，返回透明 QPixmap。"""
    try:
        from PIL import Image as _Img
        im = _Img.open(path).convert("RGBA")
        w, h = im.size
        px = im.load()
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                # 明度高于阈值的视为背景（浅灰/白），变透明
                if (r + g + b) / 3.0 > bg_threshold:
                    px[x, y] = (0, 0, 0, 0)
                else:
                    px[x, y] = (color.red(), color.green(), color.blue(), a)
        qimg = QImage(im.tobytes(), w, h, w * 4, QImage.Format_ARGB32)
        return QPixmap.fromImage(qimg)
    except Exception:
        return QPixmap()


class ThemeToggleSwitch(QWidget):
    """深浅色主题开关（滑动式），点击滑块切换。勾选=深色。"""
    changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(78, 32)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = theme_manager.is_dark

        # QLabel 渲染彩色 emoji（比 QPainter.drawText 可靠）
        track_h = 26
        icon_s = track_h - 8
        self._moon_lbl = QLabel("🌙")
        self._sun_lbl = QLabel("☀️")
        for lbl in (self._moon_lbl, self._sun_lbl):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("background: transparent;")
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            lbl.setParent(self)
            f = QFont("Segoe UI Emoji")
            f.setPixelSize(icon_s)
            lbl.setFont(f)
        self._position_icons()
        self._update_icons()

    def is_checked(self):
        return self._checked

    def set_checked(self, on):
        self._checked = bool(on)
        self._update_icons()
        self.update()

    def _position_icons(self):
        track_h = 26
        icon_s = track_h - 8
        self._moon_lbl.setGeometry(3, 3, icon_s + 4, icon_s + 4)
        self._sun_lbl.setGeometry(self.width() - 3 - (icon_s + 4), 3, icon_s + 4, icon_s + 4)

    def _update_icons(self):
        self._moon_lbl.setVisible(self._checked)
        self._sun_lbl.setVisible(not self._checked)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_icons()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self._update_icons()
        self.update()
        self.changed.emit(self._checked)
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track_h = 26
        track_y = (h - track_h) // 2
        track = QColor(accent_color()) if self._checked else pcolor("track")
        slider = QColor(readable_text(accent_color()))
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        radius = track_h // 2
        p.drawRoundedRect(1, track_y, w - 2, track_h, radius, radius)

        # 滑块
        pad = 2
        r = (track_h - pad * 2) // 2
        cx = (w - pad - r) if self._checked else (pad + r)
        p.setBrush(slider)
        p.setPen(QPen(pcolor("border", "border_a"), 1))
        p.drawEllipse(cx - r, track_y + pad, r * 2, r * 2)
        p.end()


class CollapsibleSection(QWidget):
    """可折叠的分组：点击标题收起/展开内容。"""

    def __init__(self, title: str, parent=None, expanded: bool = True):
        super().__init__(parent)
        self._expanded = expanded
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._header = PlainHeaderButton()
        self._header.setText(title)
        self._header.setCheckable(True)
        self._header.setChecked(expanded)
        self._header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._header.toggled.connect(self._on_toggle)
        outer.addWidget(self._header)
        self._content = QWidget()
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(10, 2, 10, 8)
        outer.addWidget(self._content)
        self._content.setVisible(expanded)

    def content_layout(self) -> QVBoxLayout:
        return self._content_lay

    def set_expanded(self, expanded: bool):
        """代码里展开 / 收起（与点标题栏等价），供预览与设置页联动使用。"""
        self._header.setChecked(bool(expanded))

    def is_expanded(self) -> bool:
        return bool(self._expanded)

    def _on_toggle(self, checked):
        self._expanded = checked
        self._content.setVisible(checked)
        self._header.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)


class SectionCard(QFrame):
    """统一的卡片分区：标题（可带提示）+ 内容区，用于各对话框统一视觉。"""

    def __init__(self, title: str = "", parent=None, hint: str = ""):
        super().__init__(parent)
        self.setObjectName("sectionCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)
        self.title_lbl = None
        self.hint_lbl = None
        if title:
            row = QHBoxLayout()
            row.setSpacing(8)
            self.title_lbl = QLabel(title)
            self.title_lbl.setObjectName("sectionTitle")
            row.addWidget(self.title_lbl)
            if hint:
                self.hint_lbl = QLabel(hint)
                self.hint_lbl.setObjectName("sectionHint")
                row.addWidget(self.hint_lbl)
            row.addStretch(1)
            outer.addLayout(row)
        self._body = QVBoxLayout()
        self._body.setSpacing(8)
        outer.addLayout(self._body)

    def body(self) -> QVBoxLayout:
        return self._body

    def set_hint(self, text: str):
        """更新标题后面的小灰字提示（没有 hint 标签时不做事）。"""
        if self.hint_lbl is not None:
            self.hint_lbl.setText(str(text or ""))


class FlowLayout(QLayout):
    """自动换行的流式布局：一行放不下就换到下一行。

    为什么要它：普通 QHBoxLayout 的最小宽度 = 所有子项的宽度之和，子项一多
    （例如详情页「类型 / 标签」的胶囊）就会把整个页面撑得比窗口还宽，
    连带把同一页里的其它控件（如截图列表）也拉成超宽的一行。
    本布局的最小宽度只等于"单个最宽的子项"，所以能安全地放进窄窗口。
    """

    def __init__(self, parent=None, spacing: int = 6, margins: int = 0):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(margins, margins, margins, margins)

    # ---- QLayout 必须实现的接口 ----
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return QSize(size.width() + m.left() + m.right(),
                     size.height() + m.top() + m.bottom())

    # ---- 实际排布 ----
    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        gap = max(0, self.spacing())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if line_h > 0 and x + hint.width() > eff.right():
                x, y, line_h = eff.x(), y + line_h + gap, 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


def chip_label(text: str, color: str = "") -> QLabel:
    """小胶囊标签（状态、类型等）。传 color 时用该颜色做底。"""
    lbl = QLabel(text)
    lbl.setObjectName("chip")
    lbl.setAlignment(Qt.AlignCenter)
    if color:
        set_chip_color(lbl, color)
    return lbl


def set_chip_color(lbl: QLabel, color: str = ""):
    """重设胶囊底色；传空字符串则恢复为 QSS 默认样式。"""
    if not color:
        lbl.setStyleSheet("")
        return
    lbl.setStyleSheet(
        "background:%s;color:#16121F;border-radius:10px;padding:3px 10px;"
        "font-size:11px;font-weight:700;" % color)


def kv_row(key: str, value: str = ""):
    """一行"名称 + 值"，返回 (行控件, 值标签) 以便后续刷新内容。"""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    k = QLabel(key)
    k.setObjectName("kvKey")
    k.setFixedWidth(76)
    v = QLabel(value or "—")
    v.setObjectName("kvValue")
    v.setWordWrap(True)
    lay.addWidget(k)
    lay.addWidget(v, 1)
    return w, v


class _StatusRow(QWidget):
    """状态列表的一行（可点）。"""
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        event.accept()


class StatusList(QWidget):
    """状态筛选列表：彩色圆点 + 数量。

    接口刻意与 QComboBox 对齐（addItem / currentData / setCurrentIndex /
    currentIndexChanged），这样主窗口里原有的筛选逻辑可以原样复用。
    """

    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusList")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(1)
        self._lay = lay
        self._rows = []
        self._index = -1

    def addItem(self, text, data=None, color=""):
        row = _StatusRow()
        row.setObjectName("statusRow")
        row.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 7, 10, 7)
        h.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet("background:%s;border-radius:4px;"
                          % (color or pstr("muted")))
        t = QLabel(text)
        t.setObjectName("statusRowText")
        c = QLabel("")
        c.setObjectName("statusRowCount")
        c.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(dot)
        h.addWidget(t, 1)
        h.addWidget(c)
        row.clicked.connect(lambda i=len(self._rows): self.setCurrentIndex(i))
        self._lay.addWidget(row)
        self._rows.append({"row": row, "dot": dot, "text": t, "count": c, "data": data})
        if self._index < 0:
            self.setCurrentIndex(0, emit=False)
        self._restyle()

    def setCount(self, index: int, value):
        if 0 <= index < len(self._rows):
            self._rows[index]["count"].setText(str(value))

    def setCurrentIndex(self, index, emit=True):
        if not self._rows:
            return
        index = max(0, min(int(index), len(self._rows) - 1))
        changed = (index != self._index)
        self._index = index
        self._restyle()
        if changed and emit:
            self.currentIndexChanged.emit(index)

    def currentIndex(self) -> int:
        return self._index

    def count(self) -> int:
        return len(self._rows)

    def currentData(self):
        if 0 <= self._index < len(self._rows):
            return self._rows[self._index]["data"]
        return None

    def currentText(self) -> str:
        if 0 <= self._index < len(self._rows):
            return self._rows[self._index]["text"].text()
        return ""

    def _restyle(self):
        hover_bg = _rgba("#FFFFFF" if is_dark() else "#14151C", 0.07)
        for i, it in enumerate(self._rows):
            if i == self._index:
                it["row"].setStyleSheet(
                    "QWidget#statusRow{background:%s;border-radius:10px;}"
                    % _rgba(accent_color(), 0.20))
                it["text"].setStyleSheet("color:%s;font-weight:600;" % pstr("text"))
            else:
                it["row"].setStyleSheet(
                    "QWidget#statusRow{background:transparent;border-radius:10px;}"
                    "QWidget#statusRow:hover{background:%s;}" % hover_bg)
                it["text"].setStyleSheet("color:%s;" % pstr("muted2"))


class StatusPill(QPushButton):
    """顶部状态筛选胶囊：只负责外观与点击，筛选逻辑仍由原状态下拉驱动。"""

    def __init__(self, text: str, color: str = "", parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._color = color or accent_color()
        self.setObjectName("statusPill")
        self.setMinimumHeight(30)
        self.toggled.connect(lambda _=False: self.refresh_color())
        self.refresh_color()

    def set_color(self, color: str):
        self._color = color or accent_color()
        self.refresh_color()

    def refresh_color(self):
        p = pal()
        c = self._color
        if self.isChecked():
            self.setStyleSheet(
                "QPushButton{background:%s;color:#16121F;border:1px solid %s;"
                "border-radius:15px;padding:6px 16px;font-size:12px;font-weight:700;}"
                % (c, c))
        else:
            self.setStyleSheet(
                "QPushButton{background:transparent;color:%s;border:1px solid %s;"
                "border-radius:15px;padding:6px 16px;font-size:12px;}"
                "QPushButton:hover{background:%s;color:%s;}"
                % (pstr("muted"), pstr("border", "border_a"), _rgba(c, 0.16), pstr("text")))

class GameCardDelegate(QStyledItemDelegate):
    """游戏卡片绘制（参考图风格）：封面铺满整张卡，文字与标签叠在封面下方。

    只负责把已有数据画成卡片，不读数据库、不改交互：网格项结构、tooltip、双击、
    右键菜单、悬浮 CG 轮播全部沿用原来的实现。悬停时额外绘制上浮、封面微放大、
    预渲染光晕与两个操作按钮（按钮点击由主窗口处理）。
    """

    COVER_W = 216        # 卡片即封面
    COVER_H = 300
    CARD_W = 216
    CARD_H = 300
    RADIUS = 14
    LIFT = 5             # 悬停上浮像素
    COVER_ZOOM = 1.035   # 悬停封面放大倍数（1.02 ~ 1.04）
    GLOW_PAD = 8         # 光晕外扩像素（须小于单元格留白，否则会被裁成硬边）
    ACTION_H = 28        # 悬停按钮高度
    HEART_SIZE = 26      # 左上角收藏心形直径

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glow = None
        self._glow_key = None
        self.action_row = -1
        self.action_name = ""

    # ---------- 几何（主窗口做点击命中也复用同一套坐标）----------
    @classmethod
    def card_rect_for(cls, item_rect: QRect) -> QRect:
        return QRect(item_rect.x() + (item_rect.width() - cls.CARD_W) // 2,
                     item_rect.y() + (item_rect.height() - cls.CARD_H) // 2,
                     cls.CARD_W, cls.CARD_H)

    @classmethod
    def cover_rect_for(cls, item_rect: QRect) -> QRect:
        """封面即整张卡（悬停时算上上浮）。"""
        return cls.card_rect_for(item_rect).translated(0, -cls.LIFT)

    @classmethod
    def cell_size(cls) -> QSize:
        """单元格尺寸：卡片 + 四周留白（留白需≥ 上浮 + 光晕）。"""
        pad = cls.LIFT + cls.GLOW_PAD + 2
        return QSize(cls.CARD_W + pad * 2, cls.CARD_H + pad * 2)

    @classmethod
    def _action_items(cls, card: QRect):
        gap = 8
        w = (cls.CARD_W - 24 - gap) // 2
        y = card.bottom() - cls.ACTION_H - 12
        x0 = card.x() + 12
        return (("detail", QRect(x0, y, w, cls.ACTION_H), "查看详情"),
                ("edit", QRect(x0 + w + gap, y, w, cls.ACTION_H), "编辑信息"))

    @classmethod
    def action_rects(cls, item_rect: QRect) -> dict:
        card = cls.cover_rect_for(item_rect)
        return {name: r for name, r, _ in cls._action_items(card)}

    @classmethod
    def heart_rect(cls, item_rect: QRect) -> QRect:
        cover = cls.cover_rect_for(item_rect)
        return QRect(cover.x() + 8, cover.y() + 8, cls.HEART_SIZE, cls.HEART_SIZE)

    def set_hover_action(self, row: int, name: str):
        self.action_row = row
        self.action_name = name or ""

    def refresh(self):
        self._glow = None
        self._glow_key = None

    def sizeHint(self, option, index):
        return self.cell_size()

    def _glow_pixmap(self):
        """预渲染一次柔光（避免在滚动网格里对每张卡片实时算投影）。"""
        key = (accent_color(), is_dark(), self.CARD_W, self.CARD_H)
        if self._glow is not None and self._glow_key == key:
            return self._glow
        pad = self.GLOW_PAD
        pm = QPixmap(self.CARD_W + pad * 2, self.CARD_H + pad * 2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        base = QColor(accent_color())
        for i in range(pad, 0, -1):
            c = QColor(base)
            c.setAlphaF(0.015 + 0.09 * (1.0 - i / float(pad)) ** 1.6)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(pad - i, pad - i,
                                     self.CARD_W + i * 2, self.CARD_H + i * 2),
                              self.RADIUS + i, self.RADIUS + i)
        p.end()
        self._glow = pm
        self._glow_key = key
        return pm

    @staticmethod
    def _chip(painter, x, y, text, fg, bg, max_w, font_px=10):
        f = QFont(painter.font())
        f.setPixelSize(font_px)
        fm = QFontMetrics(f)
        w = min(fm.horizontalAdvance(text) + 16, max_w)
        r = QRectF(x, y, w, 20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(r, 10, 10)
        painter.setFont(f)
        painter.setPen(fg)
        painter.drawText(r, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, int(w) - 12))
        return x + w + 6

    def _paint_actions(self, painter, card: QRect, row: int):
        for name, r, label in self._action_items(card):
            active = (row == self.action_row and name == self.action_name)
            if name == "detail":
                bg = QColor(accent_color())
                bg.setAlphaF(1.0 if active else 0.92)
                fg = QColor("#FFFFFF")
            else:
                bg = QColor(18, 18, 26)
                bg.setAlphaF(0.92 if active else 0.72)
                fg = QColor("#F5F5F7")
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(QRectF(r), self.ACTION_H / 2.0, self.ACTION_H / 2.0)
            f = QFont(painter.font())
            f.setPixelSize(11)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(fg)
            painter.drawText(r, Qt.AlignCenter, label)

    def paint(self, painter, option, index):
        rect = option.rect
        card = self.card_rect_for(rect)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if hovered:
            card = card.translated(0, -self.LIFT)

        title = str(index.data(ROLE_TITLE) or "")
        status = str(index.data(ROLE_STATUS) or "")
        try:
            rating = float(index.data(ROLE_RATING) or 0)
        except (TypeError, ValueError):
            rating = 0.0
        dev = str(index.data(ROLE_DEVELOPER) or "")
        year = str(index.data(ROLE_YEAR) or "")
        tags = list(index.data(ROLE_TAGS) or [])
        favorite = bool(index.data(ROLE_FAVORITE))

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # ---- 悬停光晕（预渲染位图）----
        if hovered or selected:
            glow = self._glow_pixmap()
            if glow is not None and not glow.isNull():
                painter.drawPixmap(card.x() - self.GLOW_PAD, card.y() - self.GLOW_PAD, glow)

        cover = QRect(card.x(), card.y(), self.CARD_W, self.CARD_H)
        body = QPainterPath()
        body.addRoundedRect(QRectF(cover), self.RADIUS, self.RADIUS)
        painter.setPen(Qt.NoPen)
        painter.setBrush(pcolor("cover_bg"))
        painter.drawPath(body)

        # ---- 封面铺满整张卡 ----
        painter.save()
        painter.setClipPath(body)
        icon = index.data(Qt.DecorationRole)
        if icon is not None and not icon.isNull():
            if hovered:
                gw = int(round(self.CARD_W * self.COVER_ZOOM))
                gh = int(round(self.CARD_H * self.COVER_ZOOM))
                icon.paint(painter, QRect(cover.x() - (gw - self.CARD_W) // 2,
                                          cover.y() - (gh - self.CARD_H) // 2,
                                          gw, gh), Qt.AlignCenter)
            else:
                icon.paint(painter, cover, Qt.AlignCenter)

        # ---- 底部深色渐变，保证文字可读 ----
        grad_h = 158
        grad = QLinearGradient(0, cover.bottom() - grad_h, 0, cover.bottom() + 2)
        c0 = QColor(8, 9, 16)
        c0.setAlpha(0)
        c1 = QColor(8, 9, 16)
        c1.setAlpha(238)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        painter.fillRect(QRect(cover.x(), cover.bottom() - grad_h, cover.width(), grad_h + 2), grad)

        # ---- 文字块（标题 / 评分·制作组·年份 / 标签胶囊）----
        tx = card.x() + 12
        tw = self.CARD_W - 24
        f_title = QFont(painter.font())
        f_title.setPixelSize(15)
        f_title.setBold(True)
        fm_title = QFontMetrics(f_title)
        title_y = card.bottom() - (60 if hovered else 82)
        painter.setFont(f_title)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRect(tx, title_y, tw, 22), Qt.AlignLeft | Qt.AlignVCenter,
                         fm_title.elidedText(title, Qt.ElideRight, tw))

        f_meta = QFont(painter.font())
        f_meta.setPixelSize(11)
        fm_meta = QFontMetrics(f_meta)
        meta_y = title_y + 24
        if hovered:
            self._paint_actions(painter, card, index.row())
        else:
            painter.setFont(f_meta)
            x = tx
            if rating > 0:
                star = "★ "
                painter.setPen(QColor("#F7D774"))
                painter.drawText(QRect(x, meta_y, 24, 16), Qt.AlignLeft | Qt.AlignVCenter, star)
                x += fm_meta.horizontalAdvance(star)
                rtxt = fmt_rating(rating)
                painter.setPen(QColor("#F2F2F5"))
                painter.drawText(QRect(x, meta_y, 40, 16), Qt.AlignLeft | Qt.AlignVCenter, rtxt)
                x += fm_meta.horizontalAdvance(rtxt) + 10
            else:
                painter.setPen(QColor("#C9C9D2"))
                painter.drawText(QRect(x, meta_y, 60, 16), Qt.AlignLeft | Qt.AlignVCenter, "未评分")
                x += fm_meta.horizontalAdvance("未评分") + 10
            rest = " · ".join([t for t in (dev, year) if t])
            if rest:
                avail = tx + tw - x
                painter.setPen(QColor("#C9C9D2"))
                painter.drawText(QRect(x, meta_y, max(0, avail), 16),
                                 Qt.AlignLeft | Qt.AlignVCenter,
                                 fm_meta.elidedText(rest, Qt.ElideRight, avail))
            # 标签胶囊：优先类型/标签，没有就退回制作组 + 年份
            chip_y = meta_y + 22
            chip_bg = QColor(255, 255, 255, 46)
            chip_fg = QColor("#F2F2F5")
            cx = tx
            shown = 0
            for text in tags[:3]:
                cx = self._chip(painter, cx, chip_y, text, chip_fg, chip_bg,
                                max(40, tx + tw - cx))
                shown += 1
                if cx > tx + tw - 30:
                    break
            if shown == 0:
                for text in ([dev] if dev else []) + ([year] if year else []):
                    cx = self._chip(painter, cx, chip_y, text, chip_fg, chip_bg,
                                    max(40, tx + tw - cx))
        painter.restore()

        # ---- 左上角收藏心形（可点击）----
        hs = self.HEART_SIZE
        hr = QRectF(cover.x() + 8, cover.y() + 8, hs, hs)
        if favorite:
            heart_bg = QColor(pstr("pink"))
            heart_fg = QColor("#16121F")
        else:
            heart_bg = QColor(0, 0, 0)
            heart_bg.setAlphaF(0.38 if is_dark() else 0.22)
            heart_fg = QColor(pstr("pink"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(heart_bg)
        painter.drawEllipse(hr)
        hf = QFont(painter.font())
        hf.setPixelSize(13)
        painter.setFont(hf)
        painter.setPen(heart_fg)
        painter.drawText(hr.toRect(), Qt.AlignCenter, "♥")

        # ---- 右上角状态标签 ----
        if status:
            sc = QColor(status_color(status))
            chip_bg = QColor(sc)
            chip_bg.setAlphaF(0.94)
            f = QFont(painter.font())
            f.setPixelSize(10)
            f.setBold(True)
            fm = QFontMetrics(f)
            w = fm.horizontalAdvance(status) + 16
            chip = QRectF(cover.right() - 8 - w, cover.y() + 9, w, 21)
            painter.setPen(Qt.NoPen)
            painter.setBrush(chip_bg)
            painter.drawRoundedRect(chip, 10, 10)
            painter.setFont(f)
            painter.setPen(QColor("#16121F"))
            painter.drawText(chip, Qt.AlignCenter, status)

        # ---- 选中 / 悬停描边 ----
        if selected or hovered:
            ring = QColor(accent_color())
            ring.setAlphaF(0.9 if selected else 0.45)
            painter.setPen(QPen(ring, 2 if selected else 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(body)
        painter.restore()
