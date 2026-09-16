# -*- coding: utf-8 -*-
"""??? MainWindow ????? / ??????"""

import os
import math
import random
import re
from PySide6.QtCore import (
    Qt, QTimer, QSize, QPoint, QRect, QRectF, QPointF, QEvent, QPropertyAnimation,
    QEasingCurve, QParallelAnimationGroup, QAbstractAnimation,
)
from PySide6.QtGui import (
    QPixmap, QIcon, QFont, QAction, QKeySequence, QColor, QPainter, QImage, QImageReader,
    QLinearGradient, QRadialGradient, QPainterPath, QBrush, QPen,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QSplitter, QFrame,
    QMessageBox, QAbstractItemView, QListView, QMenu, QGraphicsOpacityEffect, QToolButton,
    QToolTip, QWidgetAction, QCheckBox, QScrollArea, QStackedWidget,
)

import config
from config import (
    get_theme, set_theme, accent_color, accent_hover, accent_soft, get_sgdb_key,
    get_bg_image, STATUS_OPTIONS, PAGE_SIZE, to_abs, fmt_rating, DB_PATH, now_str,
    ask_yes_no, _orphan_worker, delete_game_and_files, delete_cover_if_unused, _hover_box_size,
    make_placeholder_pixmap, _load_pix_fast,
    thumbs_rel_path, get_hover_interval, APP_NAME, APP_SUBTITLE, APP_VERSION,
    ACCENT_PRESETS, set_accent, get_accent, get_avatar_image, get_assistant_hidden,
    set_assistant_hidden, APP_ICON_PNG,
    get_pet_lines, get_pet_click_random, get_pet_auto_minutes, get_pet_image,
    get_accent_override, set_accent_override, get_color_mode, set_color_mode,
    get_custom_background_path,
)
from theme_manager import theme_manager
from database import Database
import net
from net import _search_by_source, _download_cover, _http_get
import workers
from workers import ScreenshotImportWorker
from theme import (
    TopComboBox, PlainHeaderButton, ThemeToggleSwitch, CollapsibleSection, _apply_theme, _apply_bg,
    GameCardDelegate, StatusPill, app_icon, app_icon_pixmap, cover_pixmap, pstr,
    status_color, rounded_pixmap, StatusList, GlassSurface, build_backdrop, glass_alpha,
    is_dark, pcolor,
    ROLE_STATUS, ROLE_RATING, ROLE_DEVELOPER, ROLE_YEAR, ROLE_TITLE,
    ROLE_COVER, ROLE_FAVORITE, ROLE_TAGS,
)
import dialogs
from dialogs import (
    GameEditDialog, GameDetailDialog, BatchImportDialog, SettingsDialog,
    ImageSearchDialog, CoverPickerDialog,
)
from welcome import WelcomePage      # 启动页（纯展示层：只读数据库，不碰业务逻辑）


def _year_of(date_str) -> str:
    """从发售日期里取出年份（纯展示用，解析失败返回空串）。"""
    m = re.search(r"(\d{4})", str(date_str or ""))
    return m.group(1) if m else ""


def _card_tags(g: dict) -> list:
    """卡片底部要显示的标签：优先类型 / 标签，最多 3 个（纯展示）。"""
    parts = []
    for key in ("genres", "tags"):
        for p in re.split(r"[,，、;；/|]+", str(g.get(key, "") or "")):
            p = p.strip()
            if p and p not in parts:
                parts.append(p)
    return parts[:3]


def _image_scale_ok(path: str, need_w: int, need_h: int, max_upscale: float = 1.35) -> bool:
    """判断这张图放进展示框时是否会被明显放大（只读图片头部，开销很小）。

    读不到尺寸时按"够用"处理，交给原有的加载逻辑兜底。
    """
    try:
        size = QImageReader(path).size()
    except Exception:
        return True
    if not size.isValid() or size.width() <= 0 or size.height() <= 0:
        return True
    scale = min(need_w / float(size.width()), need_h / float(size.height()))
    return scale <= max_upscale


def _hover_frame_path(rel_path: str, need_w: int, need_h: int) -> str:
    """挑选悬浮预览要显示的图片文件（只做"挑文件"，不生成/不改写缩略图）。

    规则：优先用缩略图；缩略图缺失、或放进展示框会被明显放大（会糊）时回退原图。
    缩略图本身的生成逻辑仍由 workers.ScreenshotImportWorker 负责，未做改动。
    """
    thumb = to_abs(thumbs_rel_path(rel_path))
    orig = to_abs(rel_path)
    if os.path.isfile(thumb) and _image_scale_ok(thumb, need_w, need_h):
        return thumb
    if os.path.isfile(orig):
        return orig
    return thumb if os.path.isfile(thumb) else ""




# ============================================================
# 桌宠气泡（右下角装饰）
#
#   气泡本体是 theme.GlassSurface（毛玻璃底 + 圆角裁剪），但 Qt 的 QSS
#   既不支持 box-shadow、也没有 inset，所以"外发光 + 1px 边框 + 顶部渐变
#   高光"只能在 paintEvent 里自绘 —— 本文件里放两个小控件，风格仅供参考
#   启动页的 _LiquidGlassCard / _StatsShadowHost，**不改动它们**。
#
#   ⚠️ 不使用 QGraphicsDropShadowEffect：它和页面级/文字级 opacity effect
#      嵌套时出现过渲染异常，稳妥起见一律自绘。
#   ⚠️ 颜色全部来自 pcolor() / accent_color() / accent_hover()，只有 Alpha
#      是字面量（与 theme.py 既有 GlassSurface、welcome.py 液态卡的写法一致）。
# ============================================================

#: 深色主题 / 浅色主题两套外观。数值按"深色要压得住、浅色要够通透"各给一套，
#: 底色不透明度**不在这里** —— 它沿用主题 token（glass_alpha("bubble")）。
_PET_BUBBLE_STYLES = {
    "light": {
        # 外发光：内层 0 0 12px rgba(accent,.08) / 外层 0 0 20px rgba(accent,.05)
        "glow": (0.08, 0.05),
        "reach": 20.0,             # 外层 20px（实机反馈原 28px 偏大，整体缩小约 35%）
        "shadow_a": 0.10,          # 常规投影 0 6px 16px rgba(0,0,0,.10)
        "shadow_dy": 6.0,
        "hl_alpha": 0.35,          # 顶部 1px 高光：主题色 α.35
        "ring_alpha": 0.62,        # 头像 2px 细环（浅背景下要压低一点）
        "ring_glow": 0.12,
        "close_bg": 0.06,          # 关闭按钮：rgba(0,0,0,.06)
    },
    "dark": {
        # 外发光：内层 0 0 14px rgba(accent,.10) / 外层 0 0 22px rgba(accent,.06)
        "glow": (0.10, 0.06),
        "reach": 22.0,             # 外层 22px（实机反馈原 33px 偏大，整体缩小约 33%）
        "shadow_a": 0.12,          # 常规投影 0 6px 16px rgba(0,0,0,.12)
        "shadow_dy": 6.0,
        "hl_alpha": 0.08,          # 深色下高光要极淡，否则像一道白缝
        "ring_alpha": 0.85,
        "ring_glow": 0.22,
        "close_bg": 0.20,          # 关闭按钮：rgba(0,0,0,.20)
    },
}

def _pet_is_light() -> bool:
    """当前是不是亮背景（判据与启动页液态玻璃卡完全一致）。

    pcolor("bg").lightness() > 128 → 亮背景（用浅色套），否则深色套。
    """
    try:
        return pcolor("bg").lightness() > 128
    except Exception:
        return not is_dark()


def _pet_bubble_style() -> dict:
    """当前主题该用的气泡外观（深浅两套参数见 _PET_BUBBLE_STYLES）。"""
    return dict(_PET_BUBBLE_STYLES["light" if _pet_is_light() else "dark"])


class _PetAvatar(QWidget):
    """气泡左侧的 40×40 圆形头像：主题渐变底 + 2px 主题色细环 + 微光晕。

    桌宠图会先被裁成内切圆（见 MainWindow._pet_pixmap），画在渐变底之上；
    没有自定义图时（用应用图标兜底）下面那层主题渐变也不会透出来。
    """

    def __init__(self, parent=None, side: int = 40):
        super().__init__(parent)
        self.setFixedSize(side, side)
        self._side = int(side)
        self._pm = QPixmap()
        self._style = {}

    def set_avatar(self, pm: QPixmap):
        """设置圆形头像位图（空位图则只显示渐变底 + 细环）。"""
        self._pm = pm if (pm is not None and not pm.isNull()) else QPixmap()
        self.update()

    def set_style(self, style: dict):
        self._style = dict(style or {})
        self.update()

    def paintEvent(self, event):
        style = self._style or _pet_bubble_style()
        s = float(self._side)
        c = s * 0.5
        radius = max(1.0, c - 2.0)          # 给 2px 细环 + 极淡外圈留位置

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            try:
                base = QColor(accent_color())
            except Exception:
                base = pcolor("accent2")

            # ① 微光晕：由外向内 3 层递减，越靠外越淡
            halo = float(style.get("ring_glow", 0.18) or 0.0)
            if halo > 0:
                painter.setPen(Qt.NoPen)
                for k, a in ((3.3, 0.22), (2.4, 0.34), (1.7, 0.50)):
                    cc = QColor(base)
                    cc.setAlphaF(max(0.0, min(1.0, halo * a)))
                    if cc.alphaF() <= 0.0:
                        continue
                    painter.setBrush(cc)
                    painter.drawEllipse(QPointF(c, c), radius + k, radius + k)

            # ② 渐变底（无图时的兜底，同时也是细环内侧那一圈）
            try:
                g2 = QColor(accent_hover())
            except Exception:
                g2 = base
            grad = QLinearGradient(QPointF(c - radius, c - radius),
                                   QPointF(c + radius, c + radius))
            cc = QColor(base)
            cc.setAlphaF(0.95)
            grad.setColorAt(0.0, cc)
            cc2 = QColor(g2)
            cc2.setAlphaF(0.95)
            grad.setColorAt(1.0, cc2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QPointF(c, c), radius, radius)

            # ③ 桌宠图（已裁成圆），缩到细环内侧，避免盖住细环
            if not self._pm.isNull():
                target = max(1, int(round(radius * 2.0)))
                scaled = self._pm.scaled(target, target, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation)
                painter.drawPixmap(int(round(c - scaled.width() / 2.0)),
                                   int(round(c - scaled.height() / 2.0)), scaled)

            # ④ 2px 主题色细环
            ring = QColor(base)
            ring.setAlphaF(max(0.0, min(1.0,
                                        float(style.get("ring_alpha", 0.8) or 0.0))))
            pen = QPen(ring, 2.0)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(c, c), radius, radius)
        finally:
            painter.end()


class _AssistantBubble(GlassSurface):
    """桌宠气泡外壳：在 GlassSurface（毛玻璃 + 圆角底）之外补三样东西。

    ① 外发光 —— QSS 不支持多层 box-shadow，这里用多层半透明圆角矩形由外向内
       叠加近似"模糊衰减"（做法与 welcome._StatsShadowHost 一致）；
    ② 1px 边框 —— pcolor("border", "border_a")，贴着圆角画；
    ③ 顶部 1px 渐变高光 —— 结构照搬 _LiquidGlassCard.TOP_HL_STOPS
       （两端透明、中间最亮），只换峰值 Alpha（浅 .35 / 深 .08）。

    ⚠️ 关键：Qt 会把 QWidget 的绘制裁在自己的 rect 里，所以**不能**直接把光晕
       画到 rect 外面去（那样一点都看不见）。这里让"玻璃本体"占据内缩了一圈的
       _inner_rect（四周留出 == 发光半径的透明边），光晕/投影/光晕边缘都画在这圈
       透明边里 —— 于是外发光既有地方画，也不会被裁掉。
       布局内容（头像/文字/✕）由 MainWindow 通过 set_content_margins() 对齐到同一
       内缩区域；_shape() 覆写成内缩圆角，毛玻璃与圆角依然严丝合缝。

    画法顺序：外发光 → 常规投影 → super().paintEvent() 画气泡本体与毛玻璃底
    → 再补 1px 边框与顶部渐变高光（都贴 _inner_rect 的圆角内沿）。
    """

    #: 顶部高光渐变停靠点：左 0 → 中间峰值 → 右 0（结构同 _LiquidGlassCard）
    TOP_HL_STOPS = ((0.00, 0.00), (0.06, 0.42), (0.28, 1.00), (0.50, 1.00),
                    (0.72, 1.00), (0.94, 0.42), (1.00, 0.00))

    #: 外发光向外的最大扩展（px）：深色=外层 22px / 浅色=外层 20px。
    #: 只是兜底 —— 正常情况下由 set_pet_style() 注入的 style["reach"] 决定。
    GLOW_REACH = {"dark": 22.0, "light": 20.0}
    #: 逐个同心环的 alpha 系数（由外向内）；第 0 个是最外环
    GLOW_ALPHAS = (0.45, 0.55, 0.64, 0.73, 0.83, 0.92)
    #: 常规投影（0 6px 16px）参与铺层的扩展量
    SHADOW_SPREADS = (16.0, 11.0, 6.0, 2.0)

    def __init__(self, parent=None, **kw):
        super().__init__(parent, **kw)
        self._pet_style = {}
        self._pad = 0.0

    # ---------- 内缩几何 ----------

    def _pad_px(self) -> float:
        """四周透明边宽度（== 外发光半径），供光晕/投影落笔。"""
        try:
            p = float(getattr(self, "_pad", 0.0) or 0.0)
        except Exception:
            p = 0.0
        if p > 0.0:
            return p
        return float(self.GLOW_REACH["light" if _pet_is_light() else "dark"])

    def _inner_rect(self) -> QRectF:
        """气泡本体（毛玻璃圆角块）的矩形：整个控件内缩 _pad_px()。"""
        return QRectF(self.rect()).adjusted(self._pad_px(), self._pad_px(),
                                            -self._pad_px(), -self._pad_px())

    def _shape(self) -> QPainterPath:
        """覆写 GlassSurface._shape()：毛玻璃/圆角裁剪只作用于内缩后的本体。"""
        r = self._inner_rect()
        rad = float(getattr(self, "_g_radius", 0) or 0)
        path = QPainterPath()
        if rad > 0 and r.width() > 2 and r.height() > 2:
            path.addRoundedRect(r, rad, rad)
        else:
            path.addRect(r)
        return path

    def set_content_margins(self, l: int, t: int, r: int, b: int):
        """给气泡布局设置内边距：外侧留出透明发光边 + 原来的内容边距。"""
        lay = self.layout()
        if lay is not None:
            p = int(round(self._pad_px()))
            lay.setContentsMargins(p + int(l), p + int(t), p + int(r), p + int(b))

    # ---------- 外观 ----------

    def set_pet_style(self, style: dict):
        """注入深浅两套外观参数（主题切换时由 MainWindow 重新下发）。"""
        self._pet_style = dict(style or {})
        try:
            pad = float(self._pet_style.get("reach", 0.0) or 0.0)
        except Exception:
            pad = 0.0
        if pad <= 0.0:
            pad = self.GLOW_REACH["light" if _pet_is_light() else "dark"]
        if abs(pad - float(getattr(self, "_pad", 0.0) or 0.0)) > 0.01:
            self._pad = pad
            self.setFixedWidth(self._glass_width() + 2 * int(round(pad)))
            self.set_content_margins(12, 11, 8, 11)
            self.updateGeometry()
        self.update()

    def _glass_width(self) -> int:
        """玻璃本体的目标宽度（248）；由 MainWindow 构建时写进属性，默认 248。"""
        try:
            return int(getattr(self, "_glass_w", 248) or 248)
        except Exception:
            return 248

    # ---------- 几何 ----------

    def _ring_rect(self, spread: float, dy: float = 0.0,
                   top_extra: float = 0.0) -> QRectF:
        """以内缩本体内沿为基准，向外扩展 spread 的同心环矩形。"""
        return self._inner_rect().adjusted(-spread, -spread + top_extra,
                                           spread, spread + dy)

    def _glow_spreads(self) -> list:
        """按当前外观的"外层扩展量"均分同心环（由外向内）。"""
        try:
            reach = float((self._pet_style or _pet_bubble_style()).get("reach", 0.0) or 0.0)
        except Exception:
            reach = 0.0
        if reach <= 0.0:
            reach = self.GLOW_REACH["light" if _pet_is_light() else "dark"]
        reach = max(2.0, min(reach, float(self._pad_px())))
        n = len(self.GLOW_ALPHAS)
        return [reach * (1.0 - k / float(n)) for k in range(n)]

    def _shadow_spreads(self, dy: float) -> list:
        """常规投影的铺层扩展量：固定按 0 6px 16px 的 16px 上限。

        只在控件内缩边（_pad_px）里可见就够 —— 发光边已缩到 20/22，16px 依然放得下。
        """
        top = max(self.SHADOW_SPREADS)
        cap = max(1.0, min(top, float(self._pad_px())))
        return [min(float(s), cap) for s in self.SHADOW_SPREADS]

    def paintEvent(self, event):
        style = self._pet_style or _pet_bubble_style()
        radius = max(0.0, float(getattr(self, "_g_radius", 0) or 0))
        base = self._inner_rect()
        if radius <= 0.0 or base.width() <= 2.0 or base.height() <= 2.0:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)

            # ① 外发光：由外向内画"嵌套同心环"，内环盖住外环 → 自然形成由内向外
            #    递减的柔和衰减（与 welcome._StatsShadowHost 同思路）。
            #    规格两层含义保留：最内环最深、最外环 ≈ 外层的 α。
            try:
                ac = QColor(accent_color())
            except Exception:
                ac = pcolor("accent2")
            glow = style.get("glow") or (0.13, 0.09)
            a_in = max(0.0, min(1.0, float(glow[0])))
            a_out = max(0.0, min(1.0, float(glow[1])))
            if a_in > 0.0 or a_out > 0.0:
                n_ring = len(self.GLOW_ALPHAS)
                for k, spread in enumerate(self._glow_spreads()):
                    # k=0 最外 → k=n-1 最内：基准 α 由 a_out 升到 a_in，
                    # 再乘同心环系数（内环被叠加得更多 → 外缘自然衰减）
                    t = float(k) / max(1.0, float(n_ring - 1))
                    base_a = a_out + (a_in - a_out) * t
                    cc = QColor(ac)
                    cc.setAlphaF(max(0.0, min(1.0, base_a * self.GLOW_ALPHAS[k])))
                    if cc.alphaF() <= 0.0:
                        continue
                    painter.setBrush(cc)
                    rr = self._inner_rect().adjusted(-spread, -spread, spread, spread)
                    painter.drawRoundedRect(rr, radius + spread, radius + spread)

            # ② 常规投影 0 6px 16px：向下偏移 dy 后自然只在下方/两侧露出
            #    （颜色 pcolor("shadow")，深色主题下是纯黑、浅色下是近黑）
            dy = float(style.get("shadow_dy", 0.0) or 0.0)
            sa = float(style.get("shadow_a", 0.0) or 0.0)
            if sa > 0.0 and dy > 0.0:
                try:
                    sc = QColor(pcolor("shadow"))
                except Exception:
                    sc = QColor(0, 0, 0)
                for spread in self._shadow_spreads(dy):
                    cc = QColor(sc)
                    cc.setAlphaF(max(0.0, min(1.0, sa * 0.30)))
                    if cc.alphaF() <= 0.0:
                        continue
                    painter.setBrush(cc)
                    rr = self._ring_rect(spread, dy, max(0.0, dy - 4.0))
                    painter.drawRoundedRect(rr, radius + spread, radius + spread)
        finally:
            painter.end()

        # ③ 气泡本体：毛玻璃底 + tint（GlassSurface 负责，含圆角裁剪）
        super().paintEvent(event)

        # ④ 1px 边框 + ⑤ 顶部 1px 渐变高光（都贴内缩本体的圆角内沿）
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            r = self._inner_rect().adjusted(0.5, 0.5, -0.5, -0.5)
            if r.width() <= 2.0 or r.height() <= 2.0:
                return
            path = QPainterPath()
            path.addRoundedRect(r, radius, radius)

            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(pcolor("border", "border_a"), 1.0))
            painter.drawPath(path)

            hl_alpha = max(0.0, min(1.0, float(style.get("hl_alpha", 0.08) or 0.0)))
            if hl_alpha > 0.0:
                x0 = r.left() + radius
                x1 = r.right() - radius
                if x1 > x0:
                    try:
                        hl = QColor(accent_color())
                    except Exception:
                        hl = pcolor("text")
                    grad = QLinearGradient(x0, 0.0, x1, 0.0)
                    for frac, a in self.TOP_HL_STOPS:
                        cc = QColor(hl)
                        cc.setAlphaF(max(0.0, min(1.0, hl_alpha * float(a))))
                        grad.setColorAt(float(frac), cc)
                    # 直线高光关掉抗锯齿：1px 线带 AA 在半像素上会被摊成两条，忽明忽暗
                    painter.setRenderHint(QPainter.Antialiasing, False)
                    painter.setPen(QPen(QBrush(grad), 1.0))
                    painter.drawLine(QPointF(x0, r.top() + 1.0),
                                     QPointF(x1, r.top() + 1.0))
        finally:
            painter.end()



class MainWindow(QMainWindow):
    # ---- 主界面入场动画参数 ----
    DASH_ENTER_MS = 600        # 入场时长
    DASH_ENTER_SCALE = 0.92    # 入场起点缩放（0.92 → 1.0，向外放大 + 淡入）

    # ---- 主界面网格滚轮参数 ----
    # IconMode 下 Qt 原生一格滚轮 = 一整屏（pageStep ≈ 视口高度，实测 597px）且瞬间跳变，
    # 所以这里自己接管滚轮：步长可控 + 缓动过渡。
    GRID_WHEEL_STEP_PX = 120   # 一格滚轮滚动多少像素（≈1/3 卡高，3 格≈1 张卡）
    GRID_WHEEL_ANIM_MS = 220   # 滚轮缓动时长

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.current_page = 1
        self.page_size = PAGE_SIZE
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._reload_to_first)
        self._hover_popup = None
        self._hover_shots = []
        self._hover_pixs = []
        self._hover_caps = []
        self._hover_idx = 0
        self._hover_gid = None
        self._hover_global = QPoint()
        self._hover_item_rect = None
        self._frontA = True
        self._hover_has_content = False
        self._sidebar_collapsed = False
        self._page_animating = False
        # 整窗背景层：清晰层（自己画）+ 毛玻璃层（面板取用），尺寸变化后重算
        self._bd_sharp = None
        self._bd_blur = None
        self._bd_ready = False
        self._bg_timer = QTimer(self)
        self._bg_timer.setSingleShot(True)
        self._bg_timer.timeout.connect(self.refresh_backdrop)

        self.setWindowTitle("%s %s — %s" % (APP_NAME, APP_VERSION, APP_SUBTITLE))
        self.setWindowIcon(app_icon())
        self.resize(1360, 820)
        # 侧边栏改成滚动区后，窗口最小高度不再被侧边栏内容顶住（918 → 由右侧决定）。
        # 这里给一个"再小就不像样"的下限：比它小则布局会挤成一团。
        self.setMinimumSize(680, 520)
        self._build_ui()
        theme_manager.themeChanged.connect(self._on_theme_manager_theme_changed)
        # ⚠️ 主界面的首屏渲染（卡片 + 封面缩略图解码）不在这里做：
        #    它被推迟到启动页"离场动画 finished"之后（见 _render_dashboard_first_time），
        #    这样启动页的渐入 / 数字滚动才不会被几十张封面解码抢 CPU。

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)
        self._splitter = splitter

        # ---------- 左侧边栏 ----------
        # 半透明侧边栏：底色 + 整窗背景（清晰层）透过，右侧一条分隔线
        self.sidebar = GlassSurface(name="sidebar", blur=False,
                                    alpha=glass_alpha("sidebar"), tint_key="sidebar",
                                    edge_right=True)
        self.sidebar.setFixedWidth(250)
        self.sidebar.setMinimumWidth(0)
        # 侧边栏内容放进滚动区：内容再长也不会顶高整个窗口的最小高度
        # （玻璃底色仍由 self.sidebar 自己画，滚动区只是透明地叠在上面）
        side_outer = QVBoxLayout(self.sidebar)
        side_outer.setContentsMargins(0, 0, 0, 0)
        side_outer.setSpacing(0)
        self.side_scroll = QScrollArea()
        self.side_scroll.setObjectName("sideScroll")
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setFrameShape(QFrame.NoFrame)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.side_scroll.setAutoFillBackground(False)
        self.side_scroll.viewport().setAutoFillBackground(False)
        side_outer.addWidget(self.side_scroll)
        self.side_content = QWidget()
        self.side_content.setObjectName("sideContent")
        self.side_scroll.setWidget(self.side_content)
        side_lay = QVBoxLayout(self.side_content)
        side_lay.setContentsMargins(16, 18, 16, 14)
        side_lay.setSpacing(10)

        # 品牌区：圆角图标 + 名称 + 副标题 + 收纳按钮
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self._brand_row = brand_row
        self.brand_logo = QLabel()
        self.brand_logo.setObjectName("appLogo")
        self.brand_logo.setFixedSize(40, 40)
        self.brand_logo.setPixmap(app_icon_pixmap(40, radius=12))
        brand_row.addWidget(self.brand_logo)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("app_brand")
        self.brand_lbl = brand
        self.brand_sub_lbl = QLabel(APP_SUBTITLE)
        self.brand_sub_lbl.setObjectName("app_sub")
        brand_box.addWidget(brand)
        brand_box.addWidget(self.brand_sub_lbl)
        brand_row.addLayout(brand_box, 1)
        self.nav_toggle_btn = QToolButton()
        self.nav_toggle_btn.setText("◀")
        self.nav_toggle_btn.setToolTip("收起 / 展开侧边栏")
        self.nav_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.nav_toggle_btn.setFixedSize(26, 26)
        self._nav_btn_orig_text = "◀"
        self.nav_toggle_btn.clicked.connect(self._toggle_sidebar)
        brand_row.addWidget(self.nav_toggle_btn)
        side_lay.addLayout(brand_row)

        # 角色头像块（装饰，使用应用图标；有自定义头像设置时优先用）
        self.avatar_lbl = QLabel()
        self.avatar_lbl.setObjectName("avatarTile")
        self.avatar_lbl.setFixedSize(64, 64)
        self.avatar_lbl.setPixmap(self._avatar_pixmap(64))
        side_lay.addWidget(self.avatar_lbl, 0, Qt.AlignHCenter)

        # 导航：游戏库 / 收藏
        self.nav_game_btn = QPushButton("📚   游戏库")
        self.nav_game_btn.setObjectName("navItemActive")
        self.nav_game_btn.setCursor(Qt.PointingHandCursor)
        self.nav_game_btn.clicked.connect(lambda: self._set_nav_mode("all"))
        self.nav_fav_btn = QPushButton("★   收藏")
        self.nav_fav_btn.setObjectName("navItem")
        self.nav_fav_btn.setCursor(Qt.PointingHandCursor)
        self.nav_fav_btn.clicked.connect(lambda: self._set_nav_mode("favorite"))
        side_lay.addWidget(self.nav_game_btn)
        side_lay.addWidget(self.nav_fav_btn)

        # 筛选分组：默认收起（状态也能用卡片上方的胶囊切，不占侧边栏位置）
        self.filter_sec = CollapsibleSection("🔍 筛选", expanded=False)
        self.filter_lay = self.filter_sec.content_layout()
        self.filter_lay.addWidget(QLabel("状态"))
        self.status_combo = StatusList()
        self.status_combo.addItem("全部", None, accent_color())
        for s in STATUS_OPTIONS:
            self.status_combo.addItem(s, s, status_color(s))
        self.status_combo.currentIndexChanged.connect(self._reload_to_first)
        self.status_combo.currentIndexChanged.connect(self._sync_status_pills)
        self.filter_lay.addWidget(self.status_combo)
        self.filter_lay.addWidget(QLabel("搜索"))
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("pillSearch")
        self.search_edit.setPlaceholderText("搜索游戏名 / 制作组 / 标签…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _: self.search_timer.start(300))
        self.filter_lay.addWidget(self.search_edit)
        self.fav_check = QCheckBox("只看收藏")
        self.fav_check.toggled.connect(self._reload_to_first)
        self.fav_check.toggled.connect(self._sync_nav_items)
        self.filter_lay.addWidget(self.fav_check)
        side_lay.addWidget(self.filter_sec)

        # 游戏管理分组
        self.game_sec = CollapsibleSection("🎮 游戏管理")
        game_lay = self.game_sec.content_layout()
        self.add_btn = QPushButton("＋ 添加游戏")
        self.add_btn.setObjectName("add_btn")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self.on_add_game)
        game_lay.addWidget(self.add_btn)
        self.batch_btn = QPushButton("批量添加")
        self.batch_btn.setObjectName("batch_btn")
        self.batch_btn.setToolTip("手动输入或导入表格，自动识别并批量添加游戏")
        self.batch_btn.setCursor(Qt.PointingHandCursor)
        self.batch_btn.clicked.connect(self.on_batch_import)
        game_lay.addWidget(self.batch_btn)
        side_lay.addWidget(self.game_sec)

        # 工具分组
        self.tool_sec = CollapsibleSection("🛠 工具")
        tool_lay = self.tool_sec.content_layout()
        self.settings_btn = QPushButton("⚙  设置（API / 令牌）")
        self.settings_btn.setObjectName("settings_btn")
        self.settings_btn.setToolTip("配置 SteamGridDB API Key 与 Bangumi 令牌")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self.on_open_settings)
        tool_lay.addWidget(self.settings_btn)
        self.identify_btn = QPushButton("🖼  识图")
        self.identify_btn.setObjectName("identify_btn")
        self.identify_btn.setToolTip("上传或拖入截图，识别属于哪部作品 / 角色")
        self.identify_btn.setCursor(Qt.PointingHandCursor)
        self.identify_btn.clicked.connect(self.on_open_identify)
        tool_lay.addWidget(self.identify_btn)

        self.random_cg_btn = QPushButton("🎲  随机 CG")
        self.random_cg_btn.setObjectName("random_cg_btn")
        self.random_cg_btn.setToolTip("从 Galgame CG 图库随机预览一张图片")
        self.random_cg_btn.setCursor(Qt.PointingHandCursor)
        self.random_cg_btn.clicked.connect(self.on_open_random_cg)
        tool_lay.addWidget(self.random_cg_btn)
        side_lay.addWidget(self.tool_sec)
        side_lay.addStretch(1)

        # 外观：主题开关 + 强调色快捷色卡
        theme_row = QHBoxLayout()
        theme_lbl = QLabel("外观")
        theme_lbl.setObjectName("hint")
        theme_row.addWidget(theme_lbl)
        theme_row.addStretch(1)
        self.theme_toggle = ThemeToggleSwitch()
        self.theme_toggle.set_checked(theme_manager.is_dark)
        self.theme_toggle.changed.connect(self._on_theme_toggle)
        theme_row.addWidget(self.theme_toggle)
        side_lay.addLayout(theme_row)

        self.accent_row = QHBoxLayout()
        self.accent_row.setSpacing(6)
        self._accent_btns = {}
        for key, preset in list(ACCENT_PRESETS.items())[:6]:
            b = QToolButton()
            b.setObjectName("accentSwatch")
            b.setFixedSize(22, 22)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(preset["name"])
            b.setStyleSheet("background:%s;" % preset["color"])
            b.clicked.connect(lambda _=False, k=key: self._on_sidebar_accent(k))
            self._accent_btns[key] = b
            self.accent_row.addWidget(b)
        self.accent_row.addStretch(1)
        side_lay.addLayout(self.accent_row)
        self._refresh_accent_swatches()

        # ---------- 右侧主区域 ----------
        right = QWidget()
        right.setObjectName("contentRoot")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # 顶部区（透明，露出整窗背景图）
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top_lay = QVBoxLayout(topbar)
        top_lay.setContentsMargins(24, 16, 24, 12)
        top_lay.setSpacing(12)

        head_row = QHBoxLayout()
        head_row.setSpacing(12)
        title_icon = QLabel("📖")
        title_icon.setObjectName("pageTitle")
        head_row.addWidget(title_icon)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        page_title = QLabel("游戏库")
        page_title.setObjectName("pageTitle")
        self.page_label = QLabel("")
        self.page_label.setObjectName("pageCount")
        title_box.addWidget(page_title)
        title_box.addWidget(self.page_label)
        head_row.addLayout(title_box)
        head_row.addStretch(1)
        top_lay.addLayout(head_row)

        # 通栏搜索胶囊（与侧边栏搜索联动）
        self.top_search = QLineEdit()
        self.top_search.setObjectName("pillSearch")
        self.top_search.setPlaceholderText("搜索游戏、制作组、标签…")
        self.top_search.setClearButtonEnabled(True)
        top_lay.addWidget(self.top_search)
        right_lay.addWidget(topbar)

        # 毛玻璃主面板
        # 毛玻璃主面板：顶部两个圆角 + 顶部一条高光，上方露出透明背景图
        self.glass = GlassSurface(name="glassPanel", blur=True,
                                  alpha=glass_alpha("panel"), radius=18,
                                  corners="tltr", edge_top=True)
        glass_lay = QVBoxLayout(self.glass)
        glass_lay.setContentsMargins(20, 14, 20, 8)
        glass_lay.setSpacing(10)

        pill_row = QHBoxLayout()
        pill_row.setSpacing(8)
        self._status_pills = []
        for i, (label, value) in enumerate([("全部", None)] + [(s, s) for s in STATUS_OPTIONS]):
            pill = StatusPill(label, status_color(value) if value else accent_color())
            pill.setProperty("statusValue", value)
            pill.clicked.connect(lambda _=False, idx=i: self.status_combo.setCurrentIndex(idx))
            self._status_pills.append(pill)
            pill_row.addWidget(pill)
        pill_row.addStretch(1)
        glass_lay.addLayout(pill_row)

        self.grid = QListWidget()
        self.grid.setObjectName("gameGrid")
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(GameCardDelegate.CARD_W, GameCardDelegate.CARD_H))
        self.grid.setGridSize(GameCardDelegate.cell_size())
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setSpacing(0)
        self.grid.setMovement(QListView.Static)
        self.grid.setWordWrap(False)
        self.grid.setTextElideMode(Qt.ElideRight)
        self.grid.setUniformItemSizes(True)
        self._card_delegate = GameCardDelegate(self.grid)
        self.grid.setItemDelegate(self._card_delegate)
        self.grid.viewport().setMouseTracking(True)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.grid.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.installEventFilter(self)
        self.grid.viewport().installEventFilter(self)
        # 平滑滚轮（选项B）：纵向滚动条也挂同一个过滤器，鼠标停在滚动条上滚轮时体验一致
        self.grid.verticalScrollBar().installEventFilter(self)
        self._grid_scroll_anim = None
        # 用户直接拖滚动条 / 翻页换列表导致范围变化时，停掉缓动，避免和用户抢位置
        self.grid.verticalScrollBar().sliderPressed.connect(self._stop_grid_scroll_anim)
        self.grid.verticalScrollBar().rangeChanged.connect(self._stop_grid_scroll_anim)
        self.grid.itemDoubleClicked.connect(self.on_open_detail)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._show_grid_menu)
        glass_lay.addWidget(self.grid, 1)

        # 数字分页：‹ 1 2 ›
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 8)
        bottom.addStretch(1)
        self.prev_btn = QPushButton("‹")
        self.prev_btn.setObjectName("pagerBtn")
        self.prev_btn.setToolTip("上一页")
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(self._prev_page)
        bottom.addWidget(self.prev_btn)
        self._pager_buttons = []
        self.pager_lay = bottom
        self.next_btn = QPushButton("›")
        self.next_btn.setObjectName("pagerBtn")
        self.next_btn.setToolTip("下一页")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self._next_page)
        bottom.addWidget(self.next_btn)
        bottom.addStretch(1)
        glass_lay.addLayout(bottom)
        right_lay.addWidget(self.glass, 1)

        splitter.addWidget(self.sidebar)
        splitter.addWidget(right)
        splitter.setSizes([250, 950])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # 搜索框双向联动（侧边栏 ↔ 顶部胶囊）
        self._syncing_search = False
        self._link_search(self.search_edit, self.top_search)
        self._link_search(self.top_search, self.search_edit)

        # ---------- 启动页 / 主界面 的堆叠容器 ----------
        # 启动页只在软件启动时出现一次：离开后不再返回（不做侧边栏回看 / 设置开关）。
        self.welcome = WelcomePage(self.db, self)
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.welcome)     # 0：启动页
        self._stack.addWidget(splitter)         # 1：主界面（侧边栏 + 内容区）
        self.setCentralWidget(self._stack)
        self.welcome.add_game_clicked.connect(self.on_add_game)
        self.welcome.identify_clicked.connect(self.on_open_identify)
        self.welcome.leave_finished.connect(self._on_welcome_left)
        self._dashboard_ready = False           # 主界面卡片/缩略图延迟到离场动画结束后再渲染
        self._dash_snap = None                  # 主界面入场动画的快照 QLabel
        self._dash_enter_group = None

        # 右下角助手气泡（纯装饰，可关闭）
        self._build_assistant_bubble()
        self._sync_status_pills()
        QTimer.singleShot(0, self._place_assistant_bubble)   # 布局稳定后再摆一次位置

    # ---------- 侧边栏/顶部辅助控件 ----------
    def _user_pixmap(self, path: str, size: int, radius: int = 14) -> QPixmap:
        """把用户自选图片（头像 / 桌宠形象）裁成 size×size 圆角；不可用时返回空 QPixmap。"""
        if path:
            abs_path = to_abs(path)
            if abs_path and os.path.isfile(abs_path):
                pm = QPixmap(abs_path)
                if not pm.isNull():
                    pm = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
                    if pm.width() > size or pm.height() > size:
                        pm = pm.copy((pm.width() - size) // 2, (pm.height() - size) // 2,
                                     size, size)
                    return rounded_pixmap(pm, radius)
        return QPixmap()

    def _avatar_pixmap(self, size: int) -> QPixmap:
        """侧边栏头像块：有自定义头像就用它，否则用应用图标。"""
        pm = self._user_pixmap(get_avatar_image(), size, 14)
        return pm if not pm.isNull() else app_icon_pixmap(size, radius=14)

    def _pet_pixmap(self, size: int) -> QPixmap:
        """桌宠气泡里的形象：有自定义桌宠图就用它，否则用应用图标。

        气泡头像已改成正圆（外面还有 2px 主题色细环），所以这里统一裁成
        **内切圆**，而不是原来的圆角矩形 —— 否则圆角方图的四个角会从细环
        外面露出来一小块。裁剪方式与 rounded_pixmap 一致：先设 dpr，
        再用逻辑坐标开 QPainter 画（高 DPI 下才不会缩到左上角）。
        """
        pm = self._user_pixmap(get_pet_image(), size, size // 2)
        if pm.isNull():
            pm = app_icon_pixmap(size, radius=size // 2)
        if pm.isNull():
            return pm
        dpr = pm.devicePixelRatio() or 1.0
        out = QPixmap(pm.size())
        out.setDevicePixelRatio(dpr)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        clip = QPainterPath()
        clip.addEllipse(QRectF(0, 0, pm.width() / dpr, pm.height() / dpr))
        p.setClipPath(clip)
        p.drawPixmap(0, 0, pm)
        p.end()
        return out

    def _sync_nav_items(self, *_):
        """导航项高亮跟随"只看收藏"：点导航项、或直接勾选复选框都会走到这里。"""
        fav = self.fav_check.isChecked()
        self.nav_game_btn.setObjectName("navItem" if fav else "navItemActive")
        self.nav_fav_btn.setObjectName("navItemActive" if fav else "navItem")
        for b in (self.nav_game_btn, self.nav_fav_btn):
            b.style().unpolish(b)
            b.style().polish(b)

    def _set_nav_mode(self, mode: str):
        """导航：游戏库 / 收藏（复用收藏筛选）。"""
        want = (mode == "favorite")
        if self.fav_check.isChecked() != want:
            # 勾选状态变化本身就会触发刷新，这里不要再补一次，避免重复查库
            self.fav_check.setChecked(want)
        else:
            self._sync_nav_items()
            self._reload_to_first()

    def _on_sidebar_accent(self, key: str):
        """侧边栏快捷色卡：独立强调色覆盖，不改变主题配色和背景图。"""
        set_accent_override(key)
        theme_manager.refresh_accent()
        self._refresh_sidebar_accent()
        self._refresh_accent_swatches()
        for pill in self._status_pills:
            value = pill.property("statusValue")
            pill.set_color(status_color(value) if value else accent_color())
        if hasattr(self, "status_combo"):
            self.status_combo._restyle()
        self.grid.viewport().update()

    def _refresh_accent_swatches(self):
        cur = get_accent_override()
        for key, b in getattr(self, "_accent_btns", {}).items():
            preset = ACCENT_PRESETS[key]
            if key == cur:
                b.setStyleSheet(
                    "background:%s;border:2px solid rgba(255,255,255,0.9);"
                    "border-radius:11px;" % preset["color"])
            else:
                b.setStyleSheet(
                    "background:%s;border:2px solid transparent;border-radius:11px;"
                    % preset["color"])

    def _link_search(self, src, dst):
        """两个搜索框内容保持同步（任一改动都触发防抖筛选）。"""
        def _on(text):
            if self._syncing_search:
                return
            self._syncing_search = True
            dst.setText(text)
            self._syncing_search = False
            self.search_timer.start(300)
        src.textChanged.connect(_on)

    def _build_assistant_bubble(self):
        """右下角桌宠气泡：纯装饰、可关闭；点一下随机说一句话。

        - 句子池来自 config.get_pet_lines()（内置 30 句，可在「设置 → 桌宠」里替换）
        - 显示 / 隐藏状态记在 settings.json 的 assistant_hidden
        - 点击是否换话、自动换话间隔同样记在设置里（见 _refresh_pet_settings）
        - 外观（玻璃底 / 外发光 / 边框 / 顶部高光）见文件顶部 _AssistantBubble；
          底色一律派生自 pcolor("card")，深浅两套参数由 _pet_bubble_style() 决定
        """
        bubble = _AssistantBubble(self, name="assistantBubble", blur=True,
                                  alpha=glass_alpha("bubble"), tint_key="card",
                                  radius=12)
        # 248 = 玻璃本体宽度，两侧再各留一圈"发光边"（深浅主题不同，随样式更新）
        bubble._glass_w = 248
        bubble.setFixedWidth(248 + 2 * int(round(bubble._pad_px())))
        lay = QHBoxLayout(bubble)
        lay.setSpacing(9)
        bubble.set_content_margins(12, 11, 8, 11)   # 外侧自动叠上发光边
        bubble.adjustSize()
        # 头像：40×40 圆 + 2px 主题色细环 + 微光晕（自绘，见 _PetAvatar）
        icon = _PetAvatar(bubble, side=40)
        icon.set_avatar(self._pet_pixmap(40))
        lay.addWidget(icon, 0, Qt.AlignTop)
        text = QLabel("")
        text.setObjectName("assistantText")
        text.setWordWrap(True)
        text.setMinimumWidth(140)
        lay.addWidget(text, 1)
        close = QToolButton()
        close.setObjectName("bubbleClose")
        close.setText("✕")
        close.setFixedSize(16, 16)
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("关闭桌宠（可在「设置 → 桌宠」里重新打开）")
        close.clicked.connect(self._hide_assistant_bubble)
        lay.addWidget(close, 0, Qt.AlignTop)

        self.assistant_bubble = bubble
        self.assistant_text = text
        self._pet_icon = icon
        self._pet_close = close
        self._pet_last_line = ""
        self._pet_effect = QGraphicsOpacityEffect(text)      # 换话时让文字淡入
        self._pet_effect.setOpacity(1.0)
        text.setGraphicsEffect(self._pet_effect)
        self._pet_anim = QPropertyAnimation(self._pet_effect, b"opacity", self)
        self._pet_anim.setDuration(220)
        self._pet_anim.setEasingCurve(QEasingCurve.OutCubic)
        # 点击气泡（含图标与文字）都算"摸一下桌宠"
        for w in (bubble, icon, text):
            w.installEventFilter(self)
        # 自动换话定时器（0 分钟 = 关闭）
        self._pet_timer = QTimer(self)
        self._pet_timer.timeout.connect(self._pet_say_random)

        self._apply_pet_bubble_style()                       # 深浅两套外观先摆好
        self._pet_say(animate=False)                         # 先摆一句，避免空着
        bubble.setVisible(not get_assistant_hidden())
        self._refresh_pet_settings()
        self._place_assistant_bubble()

    def _apply_pet_bubble_style(self, force: bool = False):
        """按当前主题给桌宠气泡下发外观（深浅两套参数）。

        颜色全部走 token（pcolor/accent_color），这里只决定"哪一套 + 多大 alpha"。
        玻璃底的 alpha 始终取 glass_alpha("bubble")，与 _refresh_glass() 完全同源，
        所以切主题不会出现"闪回旧值"。
        """
        b = getattr(self, "assistant_bubble", None)
        if b is None:
            return
        style = _pet_bubble_style()
        sig = (style.get("glow"), style.get("reach"), style.get("hl_alpha"),
               style.get("ring_alpha"), style.get("ring_glow"),
               style.get("shadow_a"), style.get("close_bg"))
        try:
            if not force and sig == getattr(self, "_pet_style_sig", None):
                return
        except Exception:
            pass
        self._pet_style_sig = sig

        alpha = glass_alpha("bubble")            # 沿用主题 token（深 0.90 / 浅 0.86）
        try:
            # tint_key="card"：深色主题下由 pcolor("card") 派生，绝不会是白底
            b.set_glass(tint_key="card", alpha=alpha, radius=12)
        except Exception:
            pass
        try:
            b.set_pet_style(style)
        except Exception:
            pass
        icon = getattr(self, "_pet_icon", None)
        if icon is not None:
            try:
                icon.set_style(style)
            except Exception:
                pass
        # 关闭按钮：浅色 rgba(shadow,.06) / 深色 rgba(shadow,.20) + muted2 文字
        close = getattr(self, "_pet_close", None)
        if close is not None:
            cbg = float(style.get("close_bg", 0.10) or 0.0)
            try:
                cb = QColor(pcolor("shadow"))
                cb.setAlphaF(max(0.0, min(1.0, cbg)))
                ch = QColor(pcolor("shadow"))
                ch.setAlphaF(max(0.0, min(1.0, cbg + 0.06)))
                cm = QColor(pcolor("muted2"))
                close.setStyleSheet(
                    "QToolButton#bubbleClose{background:rgba(%d,%d,%d,%.3f);"
                    "color:rgba(%d,%d,%d,%.3f);border:none;border-radius:8px;"
                    "font-size:11px;padding:0px;}"
                    "QToolButton#bubbleClose:hover{background:rgba(%d,%d,%d,%.3f);}"
                    % (cb.red(), cb.green(), cb.blue(), cb.alphaF(),
                       cm.red(), cm.green(), cm.blue(), cm.alphaF(),
                       ch.red(), ch.green(), ch.blue(), ch.alphaF()))
            except Exception:
                pass
        try:
            b.update()
        except Exception:
            pass
        # 发光边变化会改控件宽度（248 + 2×发光边），位置得跟着重摆一次，
        # 否则切主题后光晕会在右边/下边被窗口边缘裁掉几个像素。
        try:
            self._place_assistant_bubble()
        except Exception:
            pass

    # ---------- 桌宠（右下角气泡）----------
    def _pet_pick_line(self, lines=None) -> str:
        """随机取一句，尽量不和上一句重复。"""
        pool = list(lines if lines is not None else get_pet_lines())
        if not pool:
            return ""
        if len(pool) == 1:
            self._pet_last_line = pool[0]
            return pool[0]
        line = pool[0]
        for _ in range(8):
            line = random.choice(pool)
            if line != self._pet_last_line:
                break
        self._pet_last_line = line
        return line

    def _pet_say(self, line=None, animate=True):
        """把气泡文字换成指定句子；不传就随机一句。"""
        if not hasattr(self, "assistant_text"):
            return
        if line is None:
            line = self._pet_pick_line()
        self.assistant_text.setText(str(line))
        self.assistant_bubble.adjustSize()
        self._place_assistant_bubble()
        if animate and self._pet_effect is not None:
            self._pet_anim.stop()
            self._pet_effect.setOpacity(0.0)
            self._pet_anim.setStartValue(0.0)
            self._pet_anim.setEndValue(1.0)
            self._pet_anim.start()

    def _pet_say_random(self):
        """点一下 / 定时器触发：换一句（气泡关着时不说话）。"""
        if get_assistant_hidden():
            return
        if not self.assistant_bubble.isVisible():
            return
        self._pet_say()

    def _refresh_pet_settings(self):
        """设置页改动后同步桌宠：显隐 / 点击行为 / 自动换话间隔。"""
        b = getattr(self, "assistant_bubble", None)
        if b is None:
            return
        b.setVisible(not get_assistant_hidden())
        clickable = bool(get_pet_click_random())
        b.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        b.setToolTip("点我换一句话～" if clickable else "桌宠（点击换话已在设置里关闭）")
        minutes = get_pet_auto_minutes()
        if minutes > 0:
            self._pet_timer.start(int(minutes * 60 * 1000))
        else:
            self._pet_timer.stop()
        # 桌宠形象可能刚被换过，这里跟着刷新一下
        if getattr(self, "_pet_icon", None) is not None:
            self._pet_icon.set_avatar(self._pet_pixmap(40))
        if getattr(self, "avatar_lbl", None) is not None:
            self.avatar_lbl.setPixmap(self._avatar_pixmap(64))
        if not self.assistant_text.text().strip():
            self._pet_say(animate=False)
        self._place_assistant_bubble()

    def _hide_assistant_bubble(self):
        set_assistant_hidden(True)
        if getattr(self, "assistant_bubble", None) is not None:
            self.assistant_bubble.hide()
        if getattr(self, "_pet_timer", None) is not None:
            self._pet_timer.stop()

    def _place_assistant_bubble(self):
        b = getattr(self, "assistant_bubble", None)
        if b is None or not b.isVisible():
            return
        # 启动页期间不显示桌宠气泡：它是主界面的装饰，浮在欢迎页上会挡住操作区
        if getattr(self, "_stack", None) is not None and self._stack.currentIndex() == 0:
            b.hide()
            return
        b.adjustSize()
        # 气泡控件本身含一圈"发光边"（深 22px / 浅 20px），而"玻璃本体"就是
        # 控件内缩 pad 之后的那个圆角块 —— 所以控件右沿/下沿距窗口边 = 玻璃本体
        # 距窗口边 = 12px（用户指定），光晕就往这 12px + 发光边里落。
        # 注意：这里不能再多减一次 pad（那会把气泡整体又往里推 22px）。
        b.move(max(8, self.width() - b.width() - 12),
               max(8, self.height() - b.height() - 12))
        b.raise_()

    def _toggle_sidebar(self):
        """收起 / 展开左侧边栏。展开时右侧自动占满。"""
        if not self._sidebar_collapsed:
            self.sidebar.setFixedWidth(0)
            self._splitter.setSizes([0, self.width()])
            self._sidebar_collapsed = True
        else:
            self.sidebar.setFixedWidth(240)
            self._splitter.setSizes([240, max(200, self.width() - 240)])
            self._sidebar_collapsed = False
        self.sidebar.updateGeometry()
        self._update_nav_btn()

    def _on_theme_toggle(self, is_dark):
        # 侧边栏快捷开关 = 手动切浅色/深色；跟随系统在设置页里选。
        theme_manager.set_color_mode("dark" if is_dark else "light")
        # ThemeManager.themeChanged 会触发 _on_theme_manager_theme_changed 刷新控件
        for w in self.findChildren(QWidget):
            if isinstance(w, (PlainHeaderButton, ThemeToggleSwitch)):
                w.update()

    def _on_theme_manager_theme_changed(self, *_args):
        """ThemeManager 主题/强调色变化：同步侧边栏开关与自定义控件。"""
        if getattr(self, "theme_toggle", None) is not None:
            self.theme_toggle.set_checked(theme_manager.is_dark)
        self._refresh_sidebar_accent()

    def _refresh_sidebar_accent(self):
        """主题/强调色变化后刷新品牌图标、状态胶囊与卡片配色。"""
        _apply_theme()
        for pill in getattr(self, "_status_pills", []):
            value = pill.property("statusValue")
            pill.set_color(status_color(value) if value else accent_color())
        if getattr(self, "brand_logo", None) is not None:
            self.brand_logo.setPixmap(app_icon_pixmap(40, radius=12))
        if getattr(self, "avatar_lbl", None) is not None:
            self.avatar_lbl.setPixmap(self._avatar_pixmap(64))
        self._refresh_accent_swatches()
        if getattr(self, "_card_delegate", None) is not None:
            self._card_delegate.refresh()      # 丢弃缓存的光晕图，按新主题/强调色重绘
        self._style_hover_cap()               # 字幕胶囊跟随主题换浅底/深底
        self._refresh_glass()                 # 面板不透明度按深浅色切换
        # 背景刷新由 ThemeManager.backgroundChanged -> _apply_bg 负责；
        # 强调色单独变化时不重算背景，保证“主题色”和“背景”解耦。
        if hasattr(self, "grid"):
            self.grid.viewport().update()
        self.update()

    def _refresh_glass(self):
        """把毛玻璃面板的不透明度同步到当前主题（深浅色数值不同）。"""
        for w, key in ((getattr(self, "sidebar", None), "sidebar"),
                       (getattr(self, "glass", None), "panel"),
                       (getattr(self, "assistant_bubble", None), "bubble")):
            if isinstance(w, GlassSurface):
                w.set_glass(alpha=glass_alpha(key))
        # 气泡还有外发光 / 边框 / 高光 / 细环四样主题相关参数，必须跟着一起重算，
        # 否则切主题只会换底色、光晕与高光会停在旧主题的值上（"闪回"）。
        self._apply_pet_bubble_style(force=True)

    def _sync_status_pills(self, *_):
        """顶部胶囊与左侧状态下拉保持同步（只改外观状态，不触发筛选逻辑）。"""
        idx = self.status_combo.currentIndex()
        for i, pill in enumerate(getattr(self, "_status_pills", [])):
            pill.setChecked(i == idx)

    def _update_nav_btn(self):
        """收纳按钮随侧边栏状态切换位置与方向。"""
        btn = self.nav_toggle_btn
        if self._sidebar_collapsed:
            # 收起后：跳到窗口左上角，变成“展开”
            btn.setText("▶")
            btn.setParent(self)
            btn.move(8, 8)
            btn.setFixedSize(34, 34)
            btn.setToolTip("展开侧边栏")
            btn.show()
            btn.raise_()
        else:
            # 展开时：放回品牌行右侧，变成“收起”
            btn.setText("◀")
            btn.setParent(self.sidebar)
            btn.setFixedSize(26, 26)
            btn.setToolTip("收起侧边栏")
            # 重新加入品牌行
            self._brand_row.addWidget(btn)
            btn.show()
            btn.raise_()

    # ---------- 整窗背景层（顶部透明 → 往下毛玻璃）----------
    def _backdrop_dpr(self) -> float:
        """按屏幕缩放比例生成背景位图，避免高 DPI 下背景发糊。"""
        try:
            app = QApplication.instance()
            if app is not None:
                return float(app.primaryScreen().devicePixelRatio())
        except Exception:
            pass
        return float(self.devicePixelRatioF() or 1.0)

    def refresh_backdrop(self):
        """重算整窗背景层（尺寸 / 主题 / 背景图变化后调用）。

        清晰层由 MainWindow.paintEvent 铺满整窗；毛玻璃层供侧边栏、主面板、
        助手气泡按自身位置取用 —— 面板边缘因此与整窗背景严丝合缝。
        ThemeManager 负责“自定义 > 主题自带 > 纯色兜底”和 15% 压暗 + 遮罩缓存，
        这里只取缓存位图，paintEvent 不做任何像素计算。
        """
        # 先释放旧位图，避免切主题/缩放时内存峰值叠高
        self._bd_sharp = None
        self._bd_blur = None
        try:
            self._bd_sharp, self._bd_blur = theme_manager.build_backdrop(
                self.width(), self.height(), self._backdrop_dpr())
            self._bd_ready = True
        except Exception:
            self._bd_sharp = None
            self._bd_blur = None
            self._bd_ready = False
        for w in self.findChildren(GlassSurface):
            w.update()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), pcolor("bg"))       # 位图还没算好时的底色
        pm = getattr(self, "_bd_sharp", None)
        if pm is not None and not pm.isNull():
            painter.drawPixmap(0, 0, pm)
        # 顶部很淡的一层压暗/提亮，保证标题与搜索框的文字对比度
        h = max(60, min(self.height(), 220))
        g = QLinearGradient(0, 0, 0, h)
        c0 = QColor(pcolor("bg")) if is_dark() else QColor(pcolor("card"))
        c0.setAlphaF(0.24 if is_dark() else 0.26)
        c1 = QColor(c0)
        c1.setAlphaF(0.0)
        g.setColorAt(0.0, c0)
        g.setColorAt(1.0, c1)
        painter.fillRect(QRect(0, 0, self.width(), h), g)
        painter.end()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._bd_ready:
            self.refresh_backdrop()
        self._place_assistant_bubble()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._sidebar_collapsed:
            self._update_nav_btn()
        self._place_assistant_bubble()
        self._bd_ready = False      # 背景位图尺寸过期，重算前先只画底色
        self._bg_timer.start(140)

    # ---------- 数据加载 ----------
    def _current_status(self):
        return self.status_combo.currentData()

    def _current_keyword(self):
        return self.search_edit.text().strip()

    def _current_developer(self):
        # 制作组 / 类型 / 标签已合并进统一搜索框（关键词会同时匹配这些字段）
        return ""

    def _current_genres(self):
        return ""

    def _current_tags(self):
        return ""

    def _favorite_only(self):
        return bool(self.fav_check.isChecked())

    def _reload_to_first(self):
        """换搜索词 / 换筛选 / 换状态：这是"另一份列表"，回到顶部。"""
        self.current_page = 1
        self._load_page()

    # ---------- 启动页 → 主界面 ----------
    def _on_welcome_left(self):
        """启动页离场动画 finished 后：切到主界面，并播放"推开呈现"入场动画。

        ⚠️ 切页只绑在 leave_finished 上，没有任何"固定时长 QTimer 强行切页"。
        """
        if self._dashboard_ready:          # 闸门：整个入场流程只走一次
            return
        self._stack.setCurrentIndex(1)
        # 真身先藏起来：① 避免下面让出事件循环时"主界面闪一帧"；
        #               ② 隐藏状态下 grab() 依然有效（已实测：非空、尺寸正确、内容完整）
        page = self._stack.widget(1)
        if page is not None:
            page.hide()
        # 启动页期间被守卫隐藏的桌宠气泡，离开后要恢复（动画期间会被快照盖住）
        bubble = getattr(self, "assistant_bubble", None)
        if bubble is not None:
            bubble.setVisible(not get_assistant_hidden())
            self._place_assistant_bubble()
        # 让出事件循环一帧：主界面在隐藏状态下结算布局，再抓快照
        QTimer.singleShot(0, self._play_dashboard_enter)

    def _play_dashboard_enter(self):
        """主界面入场：快照 0.92 倍（中心对齐）→ 1.0 倍 + 透明度 0 → 1（0.6s / OutCubic）。

        为什么用快照：QWidget 没有可动画的 scale 属性；直接动真身 geometry 会让
        侧边栏/玻璃面板/网格每帧重排（抖动 + 掉帧）。快照只动一张位图，最稳，
        并且与启动页离场（同样是快照几何动画）完全对称。

        卡片/缩略图在抓快照【之前】渲染：这样 0.6s 的放大入场里，卡片是跟着
        整个主界面一起被"推开"的，而不是动画结束后再"啪"地出现。
        """
        if self._dashboard_ready:
            return
        self._dashboard_ready = True       # 入场一开始就置位，杜绝重复触发
        page = self._stack.widget(1)
        rect = QRect(self._stack.mapTo(self, QPoint(0, 0)), self._stack.size())
        snap_pix = QPixmap()
        if page is not None and rect.width() > 1 and rect.height() > 1:
            try:
                page.resize(rect.size())   # 保证快照尺寸 = 最终尺寸
                self._reload_to_first()    # ★ 先渲染卡片/缩略图，让快照包含它们
                snap_pix = page.grab()     # 未绘制区域 alpha=0 → 壁纸自然透出
            except Exception:
                snap_pix = QPixmap()
        if page is None or snap_pix.isNull():
            if page is not None:
                page.show()                # 退化路径：直接进主界面
            self._render_dashboard_first_time()
            return

        snap = QLabel(self)
        snap.setObjectName("dashboardSnapshot")
        snap.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        snap.setAttribute(Qt.WA_StyledBackground, False)
        snap.setScaledContents(True)       # 位图跟着 geometry 一起缩放
        snap.setAlignment(Qt.AlignCenter)
        snap.setPixmap(snap_pix)
        small = QRect(0, 0,
                      max(1, int(round(rect.width() * self.DASH_ENTER_SCALE))),
                      max(1, int(round(rect.height() * self.DASH_ENTER_SCALE))))
        small.moveCenter(rect.center())
        snap.setGeometry(small)
        eff = QGraphicsOpacityEffect(snap)
        eff.setOpacity(0.0)
        snap.setGraphicsEffect(eff)
        snap.show()
        snap.raise_()                      # 盖在真身与桌宠气泡之上
        self._dash_snap = snap

        group = QParallelAnimationGroup(self)
        geo = QPropertyAnimation(snap, b"geometry", group)
        geo.setDuration(self.DASH_ENTER_MS)
        geo.setStartValue(QRect(small))
        geo.setEndValue(QRect(rect))
        fade = QPropertyAnimation(eff, b"opacity", group)
        fade.setDuration(self.DASH_ENTER_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        for anim in (geo, fade):
            anim.setEasingCurve(QEasingCurve.OutCubic)

        def _done():
            try:
                snap.hide()
                snap.deleteLater()         # 效果器随快照一起销毁
            except Exception:
                pass
            self._dash_snap = None
            group.deleteLater()
            if not page.isVisible():
                page.show()                # 真身复出
            self._render_dashboard_first_time()

        group.finished.connect(_done)
        self._dash_enter_group = group
        group.start()

    def _render_dashboard_first_time(self):
        """入场动画结束：卡片在抓快照前已渲染好，这里只需重算整窗背景层。"""
        self.refresh_backdrop()

    def _reload_current(self):
        """刷新但保持在当前页与当前滚动位置。

        编辑保存、换封面、收藏切换、详情页返回等"原地刷新"都走这里：
        位置保持不变，用户可以直接接着编辑下一条。
        """
        self._load_page(keep_scroll=True)

    def _load_page(self, keep_scroll: bool = False):
        # 列表要重建：先停掉可能在跑的滚轮缓动，避免它和"范围归零 / 位置还原"抢
        # （页内重载条目数不变时 rangeChanged 不会触发，所以必须在这里拦一次）
        self._stop_grid_scroll_anim()
        # 重建列表前先记下滚动偏移：
        #   下面的 self.grid.clear() 会把滚动条归零（内容都没了），所以要提前取。
        scroll_before = self._grid_scroll_value()
        status = self._current_status()
        keyword = self._current_keyword()
        developer = self._current_developer()
        genres = self._current_genres()
        tags = self._current_tags()
        fav_only = self._favorite_only()
        total = self.db.count_games(status, keyword, developer, genres, tags, fav_only)
        self.total_count = total
        total_pages = max(1, math.ceil(total / self.page_size))
        if self.current_page > total_pages:
            self.current_page = total_pages
        self.current_page = max(1, self.current_page)

        offset = (self.current_page - 1) * self.page_size
        games = self.db.get_games_page(offset, self.page_size, status, keyword,
                                       developer, genres, tags, fav_only)

        self.grid.clear()
        cover_size = QSize(GameCardDelegate.COVER_W, GameCardDelegate.COVER_H)
        for g in games:
            rating = g.get("rating", 0)
            rating_text = "评分：" + fmt_rating(rating) if (float(rating or 0) > 0) else "未评分"
            title = g.get("title", "")
            if len(title) > 12:
                title = title[:12] + "…"
            text = "%s\n%s" % (title, rating_text)
            item = QListWidgetItem(
                QIcon(cover_pixmap(g.get("cover_path", ""),
                                   cover_size.width(), cover_size.height())), text)
            item.setData(Qt.UserRole, g["id"])
            # 下面这些只供卡片外观绘制使用，不写回数据库、不参与任何业务判断
            item.setData(ROLE_STATUS, g.get("status", "") or "")
            item.setData(ROLE_RATING, rating)
            item.setData(ROLE_DEVELOPER, g.get("developer", "") or "")
            item.setData(ROLE_YEAR, _year_of(g.get("release_date", "")))
            item.setData(ROLE_TITLE, str(g.get("title", "") or ""))
            item.setData(ROLE_COVER, g.get("cover_path", "") or "")
            item.setData(ROLE_FAVORITE, int(g.get("favorite", 0) or 0))
            item.setData(ROLE_TAGS, _card_tags(g))
            item.setToolTip("%s\n%s" % (g.get("title", ""), g.get("title_jp", "")))
            self.grid.addItem(item)

        self.page_label.setText("共 %d 款游戏" % total)
        self._refresh_status_counts(keyword, developer, genres, tags, fav_only)
        self._rebuild_pager(total_pages)
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < total_pages)
        # 列表刷新后的滚动位置（两种语义要分清）：
        #   keep_scroll=True  -> 还原刷新前的偏移：同一页内的"原地刷新"（编辑保存 / 换封面 /
        #                        收藏切换 / 详情返回），用户停在原处，可继续编辑下一条
        #   keep_scroll=False -> 回到顶部：换页（翻页）或换了一份列表（搜索词 / 筛选 / 状态 / 首屏）
        if keep_scroll:
            QTimer.singleShot(0, lambda v=scroll_before: self._restore_grid_scroll(v))
        else:
            QTimer.singleShot(0, self._grid_to_top)

    def _grid_scroll_value(self) -> int:
        """当前列表的纵向滚动偏移（像素）。取不到时按 0 处理。"""
        try:
            return int(self.grid.verticalScrollBar().value())
        except Exception:
            return 0

    def _restore_grid_scroll(self, value: int):
        """把列表滚动位置还原到 value。

        内容变短（例如最后一页条目更少、或"只看收藏"里取消了收藏）时，
        自动夹到 [minimum, maximum]，不会越界，也不会出现"回弹"。
        """
        if self.grid.count() <= 0:
            return
        bar = self.grid.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(int(value), bar.maximum())))

    def _grid_to_top(self):
        if self.grid.count() > 0:
            self.grid.scrollToItem(self.grid.item(0), QAbstractItemView.PositionAtTop)
        else:
            self.grid.scrollToTop()

    def _prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._load_page_animated()

    def _next_page(self):
        if self.current_page < max(1, math.ceil(self.total_count / self.page_size)):
            self.current_page += 1
            self._load_page_animated()

    def _goto_page(self, page: int):
        pages = max(1, math.ceil(self.total_count / self.page_size))
        page = max(1, min(int(page), pages))
        if page != self.current_page:
            self.current_page = page
            self._load_page_animated()

    def _rebuild_pager(self, total_pages: int):
        """数字分页：‹ 1 2 3 ›（页数多时用省略号窗口）。"""
        for b in getattr(self, "_pager_buttons", []):
            self.pager_lay.removeWidget(b)
            b.deleteLater()
        self._pager_buttons = []
        idx = self.pager_lay.indexOf(self.next_btn)
        if idx < 0:
            return
        if total_pages <= 7:
            pages = list(range(1, total_pages + 1))
        else:
            cur = self.current_page
            pages = sorted(set([1, total_pages] +
                               [p for p in range(cur - 2, cur + 3)
                                if 1 <= p <= total_pages]))
        pos = idx
        last = 0
        for p in pages:
            if last and p - last > 1:
                dots = QLabel("…")
                dots.setObjectName("pagerText")
                self.pager_lay.insertWidget(pos, dots)
                pos += 1
            b = QPushButton(str(p))
            b.setObjectName("pageNumActive" if p == self.current_page else "pageNum")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, page=p: self._goto_page(page))
            self.pager_lay.insertWidget(pos, b)
            self._pager_buttons.append(b)
            pos += 1
            last = p

    def _refresh_status_counts(self, keyword, developer, genres, tags, fav_only):
        """刷新状态列表右侧的数量。

        ⚠️ 这里的"全部"必须自己不带状态条件查一次（共 6 次 COUNT：全部 1 次 + 每状态 1 次）。
        不能复用 _load_page 里算好的 total —— 那个是**已经按当前状态过滤过**的
        （分页要的是当前视图的条数），拿它当"全部"会让点其他状态时"全部"跟着一起变。
        """
        try:
            self.status_combo.setCount(0, self.db.count_games(
                None, keyword, developer, genres, tags, fav_only))
            for i, s in enumerate(STATUS_OPTIONS, start=1):
                self.status_combo.setCount(i, self.db.count_games(
                    s, keyword, developer, genres, tags, fav_only))
        except Exception:
            pass

    def _load_page_animated(self):
        """翻页淡出→填数据→淡入，仅在用户点击翻页按钮时启用。"""
        if getattr(self, "_page_animating", False):
            return
        self._page_animating = True
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)

        eff = QGraphicsOpacityEffect(self.grid)
        eff.setOpacity(1.0)
        self.grid.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(80)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)

        def _after_fadeout():
            # 翻页 = 换了一份内容：新页面从该页顶部开始（keep_scroll 默认 False -> _grid_to_top）。
            #   ⚠️ 这里不要传 keep_scroll=True —— 那会让第 2 页沿用第 1 页的滚动位置（回归 bug）。
            #   重置发生在淡出(80ms)期间、列表正好不可见，所以看不到"跳"的痕迹。
            self._load_page()
            self._page_animating = False
            anim2 = QPropertyAnimation(eff, b"opacity", self)
            anim2.setDuration(120)
            anim2.setStartValue(0.0)
            anim2.setEndValue(1.0)

            def _done():
                self.grid.setGraphicsEffect(None)
                self._page_animating = False
                self.prev_btn.setEnabled(self.current_page > 1)
                self.next_btn.setEnabled(self.current_page < max(1, math.ceil(self.total_count / self.page_size)))

            anim2.finished.connect(_done)
            anim2.start()
            self._fade_in = anim2

        anim.finished.connect(_after_fadeout)
        anim.start()
        self._fade_out = anim

    # ---------- 交互 ----------
    def on_add_game(self):
        dlg = GameEditDialog(self.db, None, self)
        if dlg.exec():
            self._reload_current()

    def on_batch_import(self):
        dlg = BatchImportDialog(self)
        dlg.exec()
        self._reload_current()

    def on_open_settings(self):
        dlg = SettingsDialog(self, db=self.db)
        dlg.exec()

    def on_open_identify(self):
        dlg = ImageSearchDialog(self, self.db)
        dlg.exec()

    def on_open_random_cg(self):
        """打开随机 CG 预览窗；只读图源 + 只读数据库（本地 CG 按游戏归类用）。"""
        from random_cg_viewer import RandomCGViewer  # 延迟导入，避免循环依赖
        dlg = getattr(self, "_random_cg_viewer", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = RandomCGViewer(self, db=self.db)
        self._random_cg_viewer = dlg
        dlg.show()

    def on_open_detail(self, item):
        game_id = item.data(Qt.UserRole)
        self._open_detail_by_id(game_id)

    def _open_detail_by_id(self, game_id):
        dlg = GameDetailDialog(self.db, game_id, self)
        dlg.exec()
        self._reload_current()  # 编辑/删除后保持在当前页

    def _build_grid_menu(self, game_ids, favorite=False):
        """构建卡片右键菜单（外观见 QSS；删除项用危险色，避免误点）。

        返回 (menu, 动作字典, 状态字典)：
        - 普通项通过 menu.exec 的返回值判断；
        - 删除项是内嵌按钮（要有红色危险样式），点击后置位 state["delete"]。
        """
        menu = QMenu(self)
        menu.setObjectName("cardMenu")
        open_act = menu.addAction("打开详情")
        edit_act = menu.addAction("编辑信息")
        fav_act = menu.addAction("取消收藏" if favorite else "添加到收藏")
        cover_act = menu.addAction("更换封面")
        menu.addSeparator()

        del_btn = QPushButton("删除所选（%d 款）" % len(game_ids))
        del_btn.setObjectName("dangerItem")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setMinimumWidth(168)
        del_widget_action = QWidgetAction(menu)
        del_widget_action.setDefaultWidget(del_btn)
        menu.addAction(del_widget_action)

        state = {"delete": False}

        def _request_delete():
            state["delete"] = True
            menu.close()

        del_btn.clicked.connect(_request_delete)
        return menu, {"open": open_act, "edit": edit_act, "fav": fav_act,
                      "cover": cover_act}, state

    def _show_grid_menu(self, pos):
        item = self.grid.itemAt(pos)
        if not item:
            return
        if not item.isSelected():
            self.grid.clearSelection()
            item.setSelected(True)
        game_id = item.data(Qt.UserRole)
        game_ids = [it.data(Qt.UserRole) for it in self.grid.selectedItems()
                    if it.data(Qt.UserRole) is not None]
        menu, acts, state = self._build_grid_menu(
            game_ids, bool(item.data(ROLE_FAVORITE)))
        act = menu.exec(self.grid.mapToGlobal(pos))
        if state["delete"]:
            self._confirm_delete_many(game_ids)
        elif act == acts["open"]:
            self._open_detail_by_id(game_id)
        elif act == acts["edit"]:
            dlg = GameEditDialog(self.db, game_id, self)
            if dlg.exec():
                self._reload_current()
        elif act == acts["fav"]:
            self._toggle_favorite_items([it for it in self.grid.selectedItems()
                                         if it.data(Qt.UserRole) is not None])
        elif act == acts["cover"]:
            self._change_cover(game_id)

    def _change_cover(self, game_id):
        g = self.db.get_game(game_id)
        if not g:
            return
        key = (g.get("title_jp") or g.get("title") or "").strip()
        if not key:
            QMessageBox.warning(self, "提示", "没有可用的名称来搜索封面。")
            return
        dlg = CoverPickerDialog(key, "vndb", self, g.get("developer", ""))
        if dlg.exec() and dlg.selected_cover:
            old = g.get("cover_path")
            try:
                self.db.update_cover(game_id, dlg.selected_cover)
            except Exception as exc:
                QMessageBox.critical(self, "保存失败", "写入封面失败：\n%s" % exc)
                return
            if old and old != dlg.selected_cover:
                delete_cover_if_unused(self.db, old)
            self._reload_current()

    def _confirm_delete(self, game_id, title):
        msg = "确定删除这款游戏吗？其截图记录与本地文件也会一并清理。"
        if title:
            msg = "确定删除《%s》吗？其截图记录与本地文件也会一并清理。" % title
        if not ask_yes_no(self, "删除游戏", msg):
            return
        try:
            delete_game_and_files(self.db, game_id)
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self._reload_current()

    def _confirm_delete_many(self, game_ids):
        game_ids = [g for g in game_ids if g is not None]
        if not game_ids:
            return
        msg = "确定删除选中的 %d 款游戏吗？其截图记录与本地文件也会一并清理。" % len(game_ids)
        if not ask_yes_no(self, "批量删除", msg):
            return
        done, errors = 0, []
        for gid in game_ids:
            try:
                delete_game_and_files(self.db, gid)
                done += 1
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            QMessageBox.warning(self, "部分失败",
                                "已删除 %d 条；以下 %d 条删除时报错：\n%s"
                                % (done, len(errors), "\n".join(errors[:12]) or "无"))
        self._reload_current()

    def _delete_selected_games(self):
        ids = [it.data(Qt.UserRole) for it in self.grid.selectedItems()
               if it.data(Qt.UserRole) is not None]
        self._confirm_delete_many(ids)

    def eventFilter(self, obj, event):
        # 桌宠：点气泡本体 / 图标 / 文字 → 随机换一句（✕ 按钮不在此列，仍只负责关闭）
        pet = getattr(self, "assistant_bubble", None)
        if pet is not None and obj in (pet, getattr(self, "_pet_icon", None),
                                       getattr(self, "assistant_text", None)):
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if get_pet_click_random():
                    self._pet_say_random()
                return True
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                return True          # 吞掉按下，避免点到气泡后面的卡片
        if obj is self.grid:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Delete:
                self._delete_selected_games()
                return True
        if obj is self.grid.viewport():
            # 平滑滚轮：替换 IconMode 原生"一格一整屏"的硬跳（只改滚轮，不动其他滚动方式）
            if event.type() == QEvent.Wheel:
                return self._smooth_grid_wheel(event)
            if event.type() == QEvent.ToolTip:
                return self._show_hover(event.globalPos())
            if event.type() == QEvent.Leave:
                self._clear_hover_action()
                self._hide_hover()
            if event.type() == QEvent.MouseMove:
                self._update_hover_action(event.position().toPoint())
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                if self._trigger_heart(event.position().toPoint()):
                    return True
                if self._trigger_hover_action(event.position().toPoint()):
                    return True
        # 选项B：鼠标停在纵向滚动条上滚轮时，走同一套平滑逻辑
        if obj is self.grid.verticalScrollBar() and event.type() == QEvent.Wheel:
            return self._smooth_grid_wheel(event)
        return super().eventFilter(obj, event)

    # ---------- 网格平滑滚轮 ----------
    def _stop_grid_scroll_anim(self, *_args):
        """停掉滚轮缓动（拖动滚动条 / 范围变化时调用；没有动画时是空操作）。"""
        anim = getattr(self, "_grid_scroll_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass

    def _smooth_grid_wheel(self, event) -> bool:
        """把滚轮变成"定步长 + 缓动"的平滑滚动；返回 True 表示事件已消费。

        为什么自己接管：IconMode 下 Qt 原生一格滚轮 = 一整屏（pageStep≈视口高，实测 597px）
        且是瞬间跳变，所以观感"一格一格硬跳"。这里只改滚轮：
        距离固定 120px/格、220ms OutCubic 过渡、连滚按目标累积。
        滚动条拖动 / 翻页按钮 / 键盘 / 触底外抛等行为一律保持原生。
        """
        try:
            dx = int(event.angleDelta().x())
            dy = int(event.angleDelta().y())
        except Exception:
            return False
        if abs(dx) > abs(dy):
            return False                        # Shift+滚轮 = 横向：交还原生处理
        pixel = 0
        try:
            pixel = int(event.pixelDelta().y())
        except Exception:
            pixel = 0
        if pixel:
            delta_px = -pixel                   # 触摸板/高精度滚轮：本身已是细粒度像素
        elif dy:
            delta_px = -(dy / 120.0) * self.GRID_WHEEL_STEP_PX
        else:
            return True
        if not delta_px:
            return True

        bar = self.grid.verticalScrollBar()
        anim = getattr(self, "_grid_scroll_anim", None)
        if anim is None:
            anim = QPropertyAnimation(bar, b"value", self)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.setDuration(self.GRID_WHEEL_ANIM_MS)
            self._grid_scroll_anim = anim
        # 连滚累积：正在缓动时以"动画终点"为基准，否则以当前真实位置为基准
        base = float(bar.value())
        try:
            if anim.state() == QAbstractAnimation.Running and anim.endValue() is not None:
                base = float(anim.endValue())
        except Exception:
            pass
        target = int(round(base + delta_px))
        target = max(bar.minimum(), min(bar.maximum(), target))

        anim.stop()
        anim.setStartValue(bar.value())         # 从当前真实位置起步 → 连滚不丢步、不跳
        anim.setEndValue(target)
        anim.start()

        # 选项A：滚动瞬间收起悬停 CG 预览窗（_hide_hover 是现成函数，其内部逻辑未改动）
        try:
            self._hide_hover()
        except Exception:
            pass
        return True

    # ---------- 卡片悬停按钮（查看详情 / 编辑信息）----------
    def _heart_item_at(self, pos):
        """返回鼠标所在卡片左上角收藏心形对应的 item（不在心形上时返回 None）。"""
        item = self.grid.itemAt(pos)
        if item is None:
            return None
        rect = self._card_delegate.heart_rect(self.grid.visualItemRect(item))
        return item if rect.contains(pos) else None

    def _trigger_heart(self, pos) -> bool:
        """点击心形切换收藏；返回 True 表示事件已被消费。"""
        item = self._heart_item_at(pos)
        if item is None:
            return False
        self._toggle_favorite_items([item])
        return True

    def _toggle_favorite_items(self, items):
        """把给定卡片整体切到"与第一张相反"的收藏状态（只改 favorite 字段）。"""
        items = [it for it in items if it is not None and it.data(Qt.UserRole) is not None]
        if not items:
            return
        new_value = 0 if int(items[0].data(ROLE_FAVORITE) or 0) else 1
        for it in items:
            try:
                self.db.set_favorite(it.data(Qt.UserRole), new_value)
            except Exception as exc:
                QMessageBox.critical(self, "保存失败", "写入收藏状态失败：\n%s" % exc)
                return
            it.setData(ROLE_FAVORITE, new_value)
        self.grid.viewport().update()
        if self._favorite_only():
            self._reload_current()      # "只看收藏"模式下取消收藏后需要把它移出列表

    def _action_at(self, pos):
        """返回 (item, 操作名)；鼠标不在按钮上时返回 (None, "")。"""
        item = self.grid.itemAt(pos)
        if item is None:
            return None, ""
        rects = self._card_delegate.action_rects(self.grid.visualItemRect(item))
        for name, rect in rects.items():
            if rect.contains(pos):
                return item, name
        return None, ""

    def _update_hover_action(self, pos):
        """鼠标在卡片按钮上时高亮（只重绘，不做别的）。"""
        item, name = self._action_at(pos)
        row = self.grid.row(item) if item is not None else -1
        if row != self._card_delegate.action_row or name != self._card_delegate.action_name:
            self._card_delegate.set_hover_action(row, name)
            self.grid.viewport().update()

    def _clear_hover_action(self):
        self._card_delegate.set_hover_action(-1, "")
        self.grid.viewport().update()

    def _trigger_hover_action(self, pos) -> bool:
        """点击卡片上的按钮；返回 True 表示事件已被消费。"""
        item, name = self._action_at(pos)
        if item is None or not name:
            return False
        game_id = item.data(Qt.UserRole)
        if game_id is None:
            return False
        self._clear_hover_action()
        if name == "detail":
            self._open_detail_by_id(game_id)
        elif name == "edit":
            dlg = GameEditDialog(self.db, game_id, self)
            if dlg.exec():
                self._reload_current()
        return True

    def _show_hover(self, global_pos):
        item = self.grid.itemAt(self.grid.viewport().mapFromGlobal(global_pos))
        if not item:
            self._hide_hover()
            return True
        gid = item.data(Qt.UserRole)
        if gid == self._hover_gid and self._hover_popup and self._hover_popup.isVisible():
            return True  # 已在显示，不再重复构建/移动，避免卡顿
        bw, bh = _hover_box_size()
        need_w, need_h = self._hover_pixel_size(bw, bh)
        rows = self.db.get_screenshots(gid, None) if gid else []
        shots = []
        for r in rows:
            path = _hover_frame_path(r["file_path"], need_w, need_h)
            if path:
                shots.append((path, "%s  %s" % (r.get("category", ""),
                                                r.get("upload_time", ""))))
        if not shots:
            # 没有上传 CG：回退显示游戏封面，不显示空白占位
            cover_abs = to_abs(str(item.data(ROLE_COVER) or ""))
            if cover_abs and os.path.isfile(cover_abs):
                shots = [(cover_abs, "封面")]
        if not shots:
            self._hide_hover()
            return False  # 封面也没有时，让默认文字提示显示
        self._ensure_hover_popup()
        self._hover_box.setFixedSize(bw, bh)
        for lbl in (self._hover_imgA, self._hover_imgB):
            lbl.setFixedSize(bw, bh)
        self._hover_shots = shots
        self._hover_pixs = []
        self._hover_caps = []
        for (abs_, cap) in shots[:6]:
            pix = _load_pix_fast(abs_, bw, bh)
            if pix.isNull():
                pix = make_placeholder_pixmap(bw, bh, "无图")
            self._hover_pixs.append(pix)
            self._hover_caps.append(cap)
        self._hover_idx = 0
        self._hover_gid = gid
        self._hover_global = global_pos
        # 字幕胶囊宽度跟随画面（竖版封面时不会拖一条比画面宽很多的字幕条）
        try:
            self._hover_cap.setFixedWidth(max(90, min(bw, self._hover_pixs[0].width())))
        except Exception:
            pass
        # 记录卡片在主窗口里的矩形，供预览窗定位（贴在卡片外侧，不遮挡按钮）
        rect_vp = self.grid.visualItemRect(item)
        self._hover_item_rect = QRect(self.grid.viewport().mapTo(self, rect_vp.topLeft()),
                                      rect_vp.size())
        self._hover_show()
        if len(self._hover_pixs) > 1:
            # 轮播间隔实时读取设置页配置（0.5 ~ 3.0 秒），不写死
            self._hover_timer.start(int(get_hover_interval() * 1000))
        else:
            self._hover_timer.stop()   # 只有一帧（例如封面回退）时无需轮播
        return True

    def _hover_pixel_size(self, box_w: int, box_h: int):
        """悬浮框在屏幕像素下的实际大小，用于判断缩略图是否够清晰。"""
        try:
            dpr = float(self.grid.devicePixelRatioF())
        except Exception:
            dpr = 1.0
        return int(box_w * max(1.0, dpr)), int(box_h * max(1.0, dpr))

    def _ensure_hover_popup(self):
        if self._hover_popup is None:
            pop = QFrame(self)
            pop.setAttribute(Qt.WA_TransparentForMouseEvents)
            pop.setAttribute(Qt.WA_StyledBackground, True)
            pop.setAttribute(Qt.WA_NoSystemBackground, True)
            pop.setAutoFillBackground(False)
            # 悬浮预览窗保持整体透明：只有 CG 图与字幕可见，不带任何底板颜色
            pop.setStyleSheet(
                "*{background:transparent;border:none;}"
                "QFrame{background:transparent;border:none;}"
                "QWidget{background:transparent;border:none;}"
                "QLabel{background:transparent;border:none;}")
            lay = QVBoxLayout(pop)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            self._hover_box = QWidget()
            box = self._hover_box
            box.setAttribute(Qt.WA_TranslucentBackground, True)
            box.setAttribute(Qt.WA_NoSystemBackground, True)
            box.setAutoFillBackground(False)
            box.setFixedSize(260, 190)
            box.setStyleSheet(
                "QWidget{background:transparent;border:none;}"
                "QLabel{background:transparent;border:none;}")
            g = QGridLayout(box)
            g.setContentsMargins(0, 0, 0, 0)
            g.setSpacing(0)
            self._hover_imgA = QLabel()
            self._hover_imgB = QLabel()
            for lbl in (self._hover_imgA, self._hover_imgB):
                lbl.setFixedSize(260, 190)
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setAttribute(Qt.WA_TranslucentBackground, True)
                lbl.setAttribute(Qt.WA_NoSystemBackground, True)
                lbl.setAutoFillBackground(False)
                lbl.setStyleSheet("background-color: transparent;")
                g.addWidget(lbl, 0, 0)
            self._hover_cap = QLabel()
            self._hover_cap.setAlignment(Qt.AlignCenter)
            self._style_hover_cap()
            self._hover_cap.setWordWrap(True)
            lay.addWidget(box)
            lay.addWidget(self._hover_cap, 0, Qt.AlignHCenter)
            self._hover_timer = QTimer(self)
            self._hover_timer.timeout.connect(self._hover_next)
            self._hover_popup = pop

    def _style_hover_cap(self):
        """按当前主题给悬浮预览的字幕胶囊上色。

        深色主题：深底浅字（和以前一致）；
        浅色主题：改为浅底深字 + 浅描边，避免深色胶囊压在浅色背景上显得突兀。
        """
        if getattr(self, "_hover_cap", None) is None:
            return
        if theme_manager.is_dark:
            bg, fg, border = pstr("bg"), pstr("text"), pstr("border", "border_a")
        else:
            bg, fg, border = pstr("card"), pstr("text"), pstr("border", "border_a")
        self._hover_cap.setStyleSheet(
            "background:%s;color:%s;border:1px solid %s;border-radius:8px;"
            "padding:3px 10px;font-size:11px;" % (bg, fg, border))

    def _hover_opacity(self, label):
        eff = label.graphicsEffect()
        if not isinstance(eff, QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(label)
            label.setGraphicsEffect(eff)
        return eff

    def _set_hover_pix(self, pix, animate):
        front = self._hover_imgA if self._frontA else self._hover_imgB
        back = self._hover_imgB if self._frontA else self._hover_imgA
        if animate and self._hover_has_content:
            eff_back = self._hover_opacity(back)
            eff_front = self._hover_opacity(front)
            back.setPixmap(pix)
            eff_back.setOpacity(0.0)
            anim_b = QPropertyAnimation(eff_back, b"opacity")
            anim_b.setStartValue(0.0)
            anim_b.setEndValue(1.0)
            anim_b.setDuration(300)
            anim_b.setEasingCurve(QEasingCurve.InOutQuad)
            anim_f = QPropertyAnimation(eff_front, b"opacity")
            anim_f.setStartValue(1.0)
            anim_f.setEndValue(0.0)
            anim_f.setDuration(300)
            anim_f.setEasingCurve(QEasingCurve.InOutQuad)
            self._hover_anim_b = anim_b
            self._hover_anim_f = anim_f
            old_front = front
            anim_b.finished.connect(lambda: self._hover_fade_done(old_front))
            anim_b.start()
            anim_f.start()
            self._frontA = not self._frontA
        else:
            front.setPixmap(pix)
            self._hover_opacity(front).setOpacity(1.0)
            back.setPixmap(QPixmap())
        self._hover_has_content = True

    def _hover_fade_done(self, old_front):
        old_front.setPixmap(QPixmap())
        new_front = self._hover_imgA if self._frontA else self._hover_imgB
        self._hover_opacity(new_front).setOpacity(1.0)

    def _hover_show(self):
        if not self._hover_pixs:
            return
        idx = self._hover_idx % len(self._hover_pixs)
        self._set_hover_pix(self._hover_pixs[idx], animate=False)
        self._hover_cap.setText(self._hover_caps[idx] if idx < len(self._hover_caps) else "")
        self._hover_popup.adjustSize()
        self._hover_popup.move(self._hover_popup_pos())
        self._hover_popup.raise_()
        self._hover_popup.show()

    def _hover_popup_pos(self) -> QPoint:
        """把悬浮预览窗放在卡片外侧：上下居中，左右按"可见画面"贴齐卡片。

        规划顺序：右侧 → 左侧 → 卡片上方 → 卡片下方。横向贴齐时用的是画面边缘
        而不是窗口边缘：窗口里可能有大片透明留白（例如竖版封面放进横向框，
        两侧各留 60 多像素），按窗口贴齐会让视觉间距显得很远。
        对齐规则：显示在卡片右侧 → 画面左边贴住卡片右边；显示在左侧 → 画面右边
        贴住卡片左边。
        """
        w = self._hover_popup.width()
        h = self._hover_popup.height()
        gap = 10
        margin = 6
        pad = self._hover_content_pad()        # 画面在窗口内的左右透明留白
        rect = self._hover_item_rect
        if rect is None or rect.isNull():      # 兜底：退回跟随鼠标
            local = self.mapFromGlobal(self._hover_global)
            x = local.x() + 24
            y = local.y() + 24
            return QPoint(max(margin, min(x, self.width() - w - margin)),
                          max(margin, min(y, self.height() - h - margin)))

        content_w = max(1, w - pad * 2)
        if rect.right() + gap + content_w <= self.width() - margin:
            x = rect.right() + gap - pad          # 画面左边贴住卡片右边
            y = rect.center().y() - h // 2
        elif rect.left() - gap - content_w >= margin:
            x = rect.left() - gap - w + pad       # 画面右边贴住卡片左边
            y = rect.center().y() - h // 2
        else:
            x = rect.center().x() - w // 2
            y = rect.top() - gap - h
            if y < margin:
                y = rect.bottom() + gap
        # 夹紧时也按画面边界（允许透明留白部分越出窗口）
        x = max(margin - pad, min(x, self.width() - margin - w + pad))
        y = max(margin, min(y, self.height() - h - margin))
        return QPoint(x, y)

    def _hover_content_pad(self) -> int:
        """当前显示的画面在预览窗里的左右透明留白（像素）。"""
        try:
            pix = self._hover_pixs[self._hover_idx % len(self._hover_pixs)]
            return max(0, (self._hover_box.width() - pix.width()) // 2)
        except Exception:
            return 0

    def _hover_next(self):
        if self._hover_pixs and self._hover_popup and self._hover_popup.isVisible():
            self._hover_idx += 1
            idx = self._hover_idx % len(self._hover_pixs)
            self._set_hover_pix(self._hover_pixs[idx], animate=True)
            self._hover_cap.setText(self._hover_caps[idx] if idx < len(self._hover_caps) else "")

    def _hide_hover(self):
        if self._hover_popup:
            self._hover_popup.hide()
            for lbl in (getattr(self, "_hover_imgA", None), getattr(self, "_hover_imgB", None)):
                if lbl is not None:
                    lbl.setPixmap(QPixmap())
        # 立即停掉交叉淡入动画，避免隐藏后还在后台跑
        for anim in (getattr(self, "_hover_anim_b", None), getattr(self, "_hover_anim_f", None)):
            if anim is not None:
                try:
                    anim.stop()
                except Exception:
                    pass
        self._hover_anim_b = None
        self._hover_anim_f = None
        if getattr(self, "_hover_timer", None):
            self._hover_timer.stop()
        self._hover_shots = []
        self._hover_pixs = []
        self._hover_caps = []
        self._hover_gid = None
        self._hover_has_content = False
        self._frontA = True
        QToolTip.hideText()

    def closeEvent(self, event):
        self._hide_hover()
        # 关闭时释放背景位图与 ThemeManager 缓存，避免退出前内存峰值
        self._bd_sharp = None
        self._bd_blur = None
        try:
            theme_manager.clear_background_cache()
        except Exception:
            pass
        self.db.close()
        super().closeEvent(event)


# ============================================================
# 入口
# ============================================================
