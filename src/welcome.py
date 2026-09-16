# -*- coding: utf-8 -*-
"""启动页（Welcome Page）：Dashboard 风格的欢迎界面。

设计约束（后续维护务必保持）：
  * 纯 Qt：只用 QVBoxLayout / QHBoxLayout / QGridLayout + QSS + 自定义 paintEvent；
    所有文本走 QLabel.setTextFormat(Qt.PlainText)，不引入任何 Web 引擎或 HTML。
  * 零侵入：不碰数据库结构 / VNDB·Bangumi API / 识图 / 增删改查业务逻辑。
    取数只用现有只读接口（count_games / get_games_page）+ 一条只读 SELECT 聚合。
  * 不影响主界面网格与「缩略图悬停 CG 轮播」：本模块自成一套卡片，
    不复用 GameCardDelegate，也不碰 grid / _hover_* / get_hover_interval()。
  * 颜色全部来自 ThemeManager 调色板（pal/pcolor/pstr/accent_color/glass_alpha），
    不硬编码颜色；背景复用现有"整窗背景层"，本页整体透明，只靠 theme.GlassSurface
    做毛玻璃，不自己贴图（压暗 15% + 遮罩逻辑都在 ThemeManager 里）。
  * 本页只在启动时出现一次：离开后不再返回（由 MainWindow 控制，逻辑不复用）。

第一轮范围：基础类 + WelcomePage 布局组装 + QSS 生成 + 静态数据填充。
第二轮再追加：渐入动画 / 统计数字 roll-up / 台词淡入 / 截图离场动画。
"""

import datetime
import math
import random
from string import Template

from PySide6.QtCore import (
    Qt, QSize, QRect, QRectF, QPoint, QPointF, Property, Signal, QEvent,
    QTimer, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup,
    QSequentialAnimationGroup, QVariantAnimation,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
    QPalette, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSizePolicy, QGraphicsOpacityEffect,
)

from config import (
    APP_NAME, accent_color, accent_hover, fmt_rating,
    get_accent_override, get_pet_lines, PET_LINES,
)
from theme import (
    GlassSurface, app_icon_pixmap, cover_pixmap, glass_alpha, is_dark, pal, pcolor, pstr,
    _mix as _mix_colors,          # 复用主题里已有的颜色混合实现
)
from theme_manager import (
    theme_manager, readable_text, readable_gradient_text,
    _luminance as _wcag_luminance,   # 复用主题里已有的 WCAG 亮度实现
)


# ============================================================
# 通用小工具
# ============================================================
def _rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB -> QSS 用的 rgba(r,g,b,a)。颜色非法时回退黑色。"""
    c = QColor(str(hex_color or ""))
    if not c.isValid():
        c = QColor("#000000")
    a = max(0.0, min(1.0, float(alpha)))
    return "rgba(%d,%d,%d,%s)" % (
        c.red(), c.green(), c.blue(), ("%.3f" % a).rstrip("0").rstrip("."))


def load_quotes() -> list:
    """底部随机台词的句子池。

    唯一来源：config.get_pet_lines()，也就是「设置 → 头像与桌宠 → 桌宠（右下角气泡）→ 句子池」
    里那套句子（存在 data/settings.json 的 pet_lines；未自定义时回退内置 PET_LINES）。
    与桌宠气泡共用同一份文案，不引入第二处来源。
    """
    try:
        lines = [str(s).strip() for s in get_pet_lines()]
        lines = [s for s in lines if s]
        if lines:
            return lines
    except Exception:
        pass
    try:
        return list(PET_LINES)
    except Exception:
        return []


# ============================================================
# 文字取色：全部来自 pal()，并用 WCAG 对比度兜住"浅字压浅底"
# ============================================================
#: Banner 主标题渐变的最小对比度（WCAG 大号文本门槛 3:1；设为 0 则纯主题渐变、不干预）
TITLE_MIN_CONTRAST = 3.0
#: 统计数值渐变的最小对比度（1.5rem 加粗 ≈ 24px，同属 WCAG 大号文本门槛 3:1）
STAT_MIN_CONTRAST = 3.0
#: 次级文字（副标题 / 统计标签 / 台词）的最低对比度
SECONDARY_MIN_CONTRAST = 6.0
#: 更弱的说明文字（12px）的最低对比度
TERTIARY_MIN_CONTRAST = 4.5


def _qc(value, fallback: str = "#000000") -> QColor:
    """宽容地把任意颜色值转成 QColor（str / QColor / 非法值回退 fallback）。

    ⚠️ 必须先判断类型：QColor 直接 str() 会得到 "<PySide6...object at 0x..>"，
       再交给 QColor() 就是非法值 —— 曾经导致对比度整体算反。
    """
    try:
        c = value if isinstance(value, QColor) else QColor(str(value or ""))
    except Exception:
        c = QColor()
    return c if c.isValid() else QColor(fallback)


def _contrast(fg, bg) -> float:
    """WCAG 相对对比度（1.0 ~ 21.0）。"""
    la, lb = _wcag_luminance(_qc(fg)), _wcag_luminance(_qc(bg))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _panel_bg() -> QColor:
    """玻璃面板的近似底色，只用于评估对比度（不参与任何绘制）。

    面板 = 主题 card 色按玻璃透明度压在"背景图"上；背景图明暗不可知，
    这里用 pal() 的 card / bg 混合做温和近似（浅色≈近白、深色≈近黑）。
    """
    p = pal()
    return _mix_colors(_qc(p.get("card"), "#FFFFFF"),
                       _qc(p.get("bg"), "#FFFFFF"), 0.35)


def _muted_at(anchor: QColor, bg: QColor, panel: QColor, min_ratio: float,
              start: float = 0.08, step: float = 0.03, max_t: float = 0.60) -> QColor:
    """以主题文字色为锚、朝背景色方向混合，返回"仍满足 min_ratio 的最浅一档"。

    深浅色通用：浅色模式下 bg 是浅色 → 出深灰；深色模式下 bg 是深色 → 出浅灰。
    一旦不达标就停在上一步，最差只会等于 pal()["text"]，
    因此结构上不可能出现"浅色文字压在浅色面板上"。
    """
    best = QColor(anchor)
    t = float(start)
    while t <= max_t + 1e-6:
        c = _mix_colors(anchor, bg, t)
        if _contrast(c, panel) < min_ratio:
            break
        best = c
        t += step
    return best


def _fit_ratio(color, panel: QColor, min_ratio: float, anchor: QColor) -> QColor:
    """把颜色朝主题文字色（anchor）收敛，直到对面板的对比度达标（用于渐变端点）。"""
    c = _qc(color)
    for _ in range(12):
        if _contrast(c, panel) >= min_ratio:
            break
        c = _mix_colors(c, anchor, 0.12)
    return c


def _text_tokens() -> dict:
    """启动页所有颜色的唯一来源：严格取自 pal()，并按面板对比度收敛。

    ⚠️ 这里不出现任何颜色字面量（黑/白也由 readable_text 从主题 token 推导）；
       浅色模式 = 深字、深色模式 = 亮字，由对比度算法自动保证，无需 if is_dark()。
    """
    p = pal()
    panel = _panel_bg()
    anchor = _qc(p.get("text"), "#000000")      # 主题文字色 = 锚
    bg = _qc(p.get("bg"), "#FFFFFF")

    # 主按钮 / 主标题渐变：与主界面按钮同源（手选强调色优先）
    if get_accent_override():
        g1, g2 = _qc(accent_color()), _qc(accent_hover())
    else:
        g1 = _qc(p.get("gradient_start"), accent_color())
        g2 = _qc(p.get("gradient_end"), accent_hover())
    t1 = _fit_ratio(g1, panel, TITLE_MIN_CONTRAST, anchor)
    t2 = _fit_ratio(g2, panel, TITLE_MIN_CONTRAST, anchor)

    # 统计数值渐变：颜色来源 = 主题主渐变（pal 的 gradient_start / gradient_end），
    # 再按面板对比度收敛（与 Banner 主标题同一套算法）——浅色模式下 24px 数字也清晰。
    sg1 = _qc(p.get("gradient_start"), accent_color())
    sg2 = _qc(p.get("gradient_end"), accent_hover())
    stat_g1 = _fit_ratio(sg1, panel, STAT_MIN_CONTRAST, anchor)
    stat_g2 = _fit_ratio(sg2, panel, STAT_MIN_CONTRAST, anchor)

    on_media = readable_text(_qc(p.get("shadow"), "#000000").name())   # 深色遮罩上的白字
    return {
        # 文字（三层：主文字 → 次级 → 更弱的说明文字，逐级变浅但仍保证对比度）
        "text": anchor.name(),
        "secondary": _muted_at(anchor, bg, panel, SECONDARY_MIN_CONTRAST).name(),
        "tertiary": _muted_at(anchor, bg, panel, TERTIARY_MIN_CONTRAST).name(),
        "on_media": on_media,
        "on_media_soft": _rgba(on_media, 0.86),
        # 强调色与渐变
        "accent": accent_color(),
        "accent_hover": accent_hover(),
        "g1": g1.name(),
        "g2": g2.name(),
        "title_g1": t1.name(),
        "title_g2": t2.name(),
        "on_grad": readable_gradient_text(g1.name(), g2.name()),
        # 统计区专用：标签色 muted2；数值渐变 stat_g1 → stat_g2（来源仍是主题主渐变）
        "muted2": pstr("muted2"),
        "muted": pstr("muted"),          # Banner 右侧问候语用
        "stat_g1": stat_g1.name(),
        "stat_g2": stat_g2.name(),
        # 按钮 / 边框（沿用调色板派生 token）
        "btn": pstr("btn"),
        "btn_hover": pstr("btn_hover"),
        "btn_press": pstr("btn_press"),
        "border": pstr("border", "border_a"),
    }


def _avg_rating(db) -> float:
    """平均评分（只取 rating > 0 的作品）。

    ⚠️ 红线：绝对不为平均分去改 database.py。
      优先对现有连接做只读聚合（不改表结构、不改任何写入逻辑）；
      失败再用现有分页接口把评分拉回 UI 层求平均兜底。
    """
    try:
        cur = db.conn.execute("SELECT AVG(rating) FROM games WHERE rating > 0")
        row = cur.fetchone()
        value = float(row[0]) if row and row[0] is not None else 0.0
        if value > 0:
            return value
    except Exception:
        pass
    try:
        vals = []
        for g in (db.get_games_page(0, 100000) or []):
            try:
                v = float(g.get("rating") or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                vals.append(v)
        return (sum(vals) / len(vals)) if vals else 0.0
    except Exception:
        return 0.0


# ============================================================
# 基础控件
# ============================================================
class ElidedLabel(QLabel):
    """不换行的单行文本：宽度不够时自动截断加省略号（resize 时重算）。

    用于卡片标题 / 台词等"可能很长但绝不能撑破布局"的位置。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setTextFormat(Qt.PlainText)      # 明令禁止 HTML 渲染
        self.setMinimumWidth(50)
        self.set_full_text(text)

    def set_full_text(self, text: str):
        """设置完整文本（内部按当前宽度做省略）。"""
        self._full_text = " ".join(str(text or "").split())
        self.updateGeometry()
        self._apply_elide()

    def full_text(self) -> str:
        return self._full_text

    # ⚠️ 这两个 hint 必须按"完整文本"来算：
    #    否则会出现自反馈——文本被省略后 sizeHint 变小，布局给得更窄，于是永远处于省略状态。
    #    sizeHint  = 完整文本宽度（被 maximumWidth 夹住）→ 布局愿意给足宽度；
    #    minimumSizeHint = 可收缩到 minimumWidth → 空间不够时才省略。
    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self._full_text) + 2
        if self.maximumWidth() < 16777215:
            w = min(w, self.maximumWidth())
        return QSize(max(self.minimumWidth(), w), fm.height() + 2)

    def minimumSizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(self.minimumWidth(), fm.height() + 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self):
        avail = max(0, self.width() - 2)
        shown = self._full_text
        if avail > 0 and self._full_text:
            fm = QFontMetrics(self.font())
            if fm.horizontalAdvance(self._full_text) > avail:
                shown = fm.elidedText(self._full_text, Qt.ElideRight, avail)
        super().setText(shown)


class GradientTitleLabel(QLabel):
    """Banner 主标题：用主题渐变色填充文字（QSS 做不了渐变文字，故自绘）。

    * 纯 Qt：QLinearGradient + QPen(QBrush) + drawText，不涉及任何 HTML / Web。
    * 渐变端点由 _text_tokens() 按面板对比度收紧到 >= TITLE_MIN_CONTRAST（默认 3:1）。
    * 自绘 ⇒ 即使页面样式表整体失效、回退到系统 Fusion 调色板，标题也不会变成白字。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.PlainText)
        self.setText(text)
        self._c1 = QColor("#000000")
        self._c2 = QColor("#000000")

    def set_colors(self, c1, c2):
        """设置渐变两端颜色（浅色模式下会被自动压深，深色模式下基本保持原色）。"""
        self._c1 = _qc(c1)
        self._c2 = _qc(c2)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        fm = QFontMetrics(self.font())
        text = fm.elidedText(str(self.text()), Qt.ElideRight, max(0, self.width()))
        grad = QLinearGradient(0.0, 0.0, float(max(1, self.width())), 0.0)
        grad.setColorAt(0.0, self._c1)
        grad.setColorAt(1.0, self._c2)
        painter.setPen(QPen(QBrush(grad), 0.0))     # 用渐变当"墨"填充文字
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.end()


class RollLabel(QLabel):
    """统计数字标签：0 → 目标值的 roll-up 动画。

    * set_target() 只记录目标并把显示重置为 0 / 空文案（此时整页还是透明的）；
    * play() 由启动页在"渐入动画结束"后调用，驱动 value 属性做 0.8s OutCubic 滚动；
    * target <= 0 时不滚动，直接显示空文案（等待添加 / 暂无通关 / 暂无评分）。
    """

    #: 滚动时长（毫秒）
    ROLL_MS = 800

    def __init__(self, fmt: str = "%d", parent=None):
        super().__init__(parent)
        self._fmt = str(fmt or "%d")
        self._value = 0.0
        self._target = 0.0
        self._empty_text = ""
        self._anim = None
        self.setTextFormat(Qt.PlainText)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._refresh()

    # ---------- Qt 属性（QPropertyAnimation 驱动） ----------
    def _get_value(self) -> float:
        return float(self._value)

    def _set_value(self, value):
        try:
            self._value = float(value)
        except (TypeError, ValueError):
            self._value = 0.0
        self._refresh()

    value = Property(float, _get_value, _set_value)

    # ---------- 对外接口 ----------
    def set_target(self, target, empty_text: str = "", fmt: str = None):
        """记录目标值，并把显示重置为 0 / 空文案。

        target <= 0 时直接显示 empty_text
        （总计=0 → "等待添加"；已通关=0 → "暂无通关"；平均分=0 → "暂无评分"）。
        真正的滚动由 play() 负责（启动页在渐入结束后调用）。
        """
        if fmt:
            self._fmt = str(fmt)
        self._empty_text = str(empty_text or "")
        try:
            self._target = float(target or 0.0)
        except (TypeError, ValueError):
            self._target = 0.0
        self._stop_roll()
        self._value = 0.0
        self._refresh()

    def play(self):
        """0.8s 内从 0 滚到 target（OutCubic）；target<=0 不滚动，只显示空文案。"""
        self._stop_roll()
        if self._target <= 0:
            self._value = 0.0
            self._refresh()
            return
        try:
            anim = QPropertyAnimation(self, b"value", self)
            anim.setDuration(self.ROLL_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(float(self._target))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._anim = anim
        except Exception:
            # 极端情况下（属性注册异常）退化为直接落值，绝不让统计区空着
            self._value = self._target
            self._refresh()

    def _stop_roll(self):
        anim = getattr(self, "_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
            self._anim = None

    def target(self) -> float:
        return float(self._target)

    # ---------- 绘制 ----------
    def _refresh(self):
        if self._target <= 0 and self._empty_text:
            super().setText(self._empty_text)
            self.setProperty("isEmptyStat", True)
            return
        try:
            text = self._fmt % self._value
        except Exception:
            text = str(self._value)
        super().setText(text)
        self.setProperty("isEmptyStat", False)


class GradientRollLabel(RollLabel):
    """统计数值标签：保留 RollLabel 的 0→目标值滚动，数字改用主题渐变自绘。

    设计约束（阶段 A 统计区域专用）：
      * 渐变色来源 = 主题主渐变（由 _apply_welcome_theme 从 _text_tokens() 传入，
        源头是 pal()["gradient_start"] / ["gradient_end"]），绝不硬编码任何颜色；
      * 无数据（target<=0，如"暂无评分"）时不显示 0：改画空文案，颜色取
        pcolor("muted")、字号 1rem，绝不落到"0"或虚构数字；
      * 字体在 paintEvent 内显式设定 —— Qt QSS 不支持 rem 单位，这里按
        1rem = 16px 折算成像素（1.5rem=24px / 1rem=16px）；
      * 自绘 ⇒ 样式表整体失效时数字也不会消失（与 GradientTitleLabel 同一思路）。

    ⚠️ 阶段 A 遗留 Bug 修复（数值显示为空 / "暂无评分"少一个字）：
       QLabel 的 sizeHint 是按 **widget 自己的字体** 算的，而数字是用 24px
       自绘的。两者不一致时布局只肯给 13×16 px 的小方块，24px 的字被裁光；
       "暂无评分"右对齐时左端被裁 ⇒ 只剩"无评分"。
       所以这里用 _sync_font() 把"绘制字体"同步写进 widget 本身，
       并覆写 sizeHint / minimumSizeHint，让布局按真实字号留足空间。
    """

    VALUE_PX = 24      # 数值字号 1.5rem（加粗）
    EMPTY_PX = 16      # 空状态文字字号 1rem
    #: 类属性兜底：RollLabel.__init__ 里就会调用 self._refresh() → _sync_font()，
    #  那一刻实例属性还没赋值，所以状态标记必须是类属性。
    _font_state = None

    def __init__(self, fmt: str = "%d", parent=None):
        super().__init__(fmt, parent)
        self._c1 = QColor()          # 无效色：未设置渐变前回退实色绘制
        self._c2 = QColor()
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._sync_font()

    def set_colors(self, c1, c2):
        """设置渐变两端（由 _apply_welcome_theme 从主题 token 传入）。"""
        self._c1 = _qc(c1)
        self._c2 = _qc(c2)
        self.update()

    def _is_empty(self) -> bool:
        return self.target() <= 0 and bool(getattr(self, "_empty_text", ""))

    # ---------- 字体：绘制字体 == widget 字体（布局才会留足空间） ----------
    def _paint_font(self) -> QFont:
        font = QFont(self.font())
        if self._is_empty():
            font.setPixelSize(self.EMPTY_PX)
            font.setBold(False)
        else:
            font.setPixelSize(self.VALUE_PX)
            font.setBold(True)
        return font

    def _sync_font(self):
        """把绘制字体同步到 widget（best-effort）。

        ⚠️ 全局 QSS 里带 font-size 规则时会覆盖 setFont()，所以尺寸计算与绘制
           都直接走 _paint_font()，绝不依赖 self.font() —— 否则数字会悄悄变小；
           这里 setFont 只是让 widget 自身的高度/基线也跟着对齐。
        """
        state = "empty" if self._is_empty() else "value"
        if state == self._font_state:
            return
        self._font_state = state
        try:
            self.setFont(self._paint_font())
            self.setMinimumHeight(int(self.VALUE_PX * 1.35))
            self.updateGeometry()
            self.update()
        except Exception:
            pass

    def _refresh(self):
        super()._refresh()          # RollLabel 负责设置数字 / 空文案
        self._sync_font()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._paint_font())     # 按"真实绘制字体"算，QSS 覆盖不了
        w = fm.horizontalAdvance(str(self.text() or "")) + 2
        return QSize(max(self.minimumWidth(), w), max(int(self.VALUE_PX * 1.35), fm.height() + 2))

    def minimumSizeHint(self) -> QSize:
        fm = QFontMetrics(self._paint_font())
        return QSize(12, max(int(self.VALUE_PX * 1.35), fm.height() + 2))

    def paintEvent(self, event):
        text = str(self.text() or "")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        font = self._paint_font()   # 显式字号：不受 QSS font-size 影响
        painter.setFont(font)
        fm = QFontMetrics(font)
        avail = max(0, self.width() - 2)
        shown = text if fm.horizontalAdvance(text) <= avail else fm.elidedText(
            text, Qt.ElideRight, avail)

        if self._is_empty():
            # 无数据：实色（主题 muted）+ 更小字号，绝不显示 0
            painter.setPen(pcolor("muted"))
            painter.drawText(self.rect(), self.alignment(), shown)
            painter.end()
            return

        if self._c1.isValid() and self._c2.isValid():
            grad = QLinearGradient(0.0, 0.0, float(max(1, self.width())), 0.0)
            grad.setColorAt(0.0, self._c1)
            grad.setColorAt(1.0, self._c2)
            painter.setPen(QPen(QBrush(grad), 0.0))     # 用渐变当"墨"填充数字
        else:
            # 主题 token 还没送达（首帧）：用主题文字色兜底，绝不出现黑/白硬编码
            painter.setPen(pcolor("text"))
        painter.drawText(self.rect(), self.alignment(), shown)
        painter.end()


class _LegendDot(QWidget):
    """进度条 / 饼图图例圆点：固定 6px 直径，颜色由主题动态派生（不硬编码）。"""

    DIAMETER = 6

    def __init__(self, color=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color = QColor(color) if color is not None else QColor()

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        if not self._color.isValid():
            return                      # 颜色未送达：不画，绝不猜颜色
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(QRectF(0.0, 0.0, float(w), float(h)))
        painter.end()


class StatusSplitBar(QWidget):
    """三段式状态进度条（已通关 / 已搁置 / 未通关），纯 QPainter 自绘。

    * 横向、圆角、三段首尾相连（高 14px，两端胶囊圆角）；
    * 数据全部来自 _load_stats() 的只读统计：已通关 / 已搁置 / 未通关；
    * 绘制顺序：未通关打底 → 已搁置 → 已通关（顶层），
      因此左→右视觉顺序为 已通关 | 已搁置 | 未通关（与外层图例一致）；
    * 三段之和 <= 0 时只画中性轨道：绝不除零、也绝不显示任何虚构占比。
    """

    BAR_H = 14          # 进度条高度（规范：10~16px）
    RADIUS = 7          # = 高度一半 → 两端自然圆角

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.BAR_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._values = (0, 0, 0)                          # 已通关 / 已搁置 / 未通关
        self._colors = (QColor(), QColor(), QColor())     # 主题色未送达前为无效色

    def set_values(self, done, paused, todo):
        """写入三段真实数量（负数/非法值一律按 0，不做任何补偿或猜测）。"""
        def _n(v):
            try:
                return max(0, int(v or 0))
            except (TypeError, ValueError):
                return 0
        self._values = (_n(done), _n(paused), _n(todo))
        self.update()

    def set_colors(self, done, paused, todo):
        """设置三段颜色（由主题动态派生）。"""
        self._colors = (QColor(done), QColor(paused), QColor(todo))
        self.update()

    def paintEvent(self, event):
        w, h = int(self.width()), int(self.height())
        painter = QPainter(self)
        if w <= 0 or h <= 0:
            painter.end()
            return
        painter.setRenderHint(QPainter.Antialiasing, True)      # ★ 规范要求

        radius = min(float(self.RADIUS), h / 2.0, w / 2.0)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0.0, 0.0, float(w), float(h)), radius, radius)
        painter.setClipPath(clip)

        c_done, c_paused, c_todo = self._colors
        if not (c_done.isValid() and c_paused.isValid() and c_todo.isValid()):
            painter.fillRect(self.rect(), pcolor("track"))      # 中性兜底
            painter.end()
            return

        total = self._values[0] + self._values[1] + self._values[2]
        if total <= 0:
            # 总数为 0：只画中性轨道，绝不除零
            painter.fillRect(self.rect(), pcolor("track"))
            painter.end()
            return

        # ① 未通关（底层，铺满整条轨道）
        painter.fillRect(self.rect(), c_todo)
        seg_done = w * (float(self._values[0]) / float(total))
        seg_paused = w * (float(self._values[1]) / float(total))
        # ② 已搁置：紧接在已通关右侧（起点 = seg_done，否则会被下面的已通关整段盖住）
        if seg_paused > 0:
            painter.fillRect(QRectF(seg_done, 0.0, seg_paused, float(h)), c_paused)
        # ③ 已通关（顶层，最左）
        if seg_done > 0:
            painter.fillRect(QRectF(0.0, 0.0, seg_done, float(h)), c_done)
        painter.end()


class _ViewHost(QWidget):
    """无布局的视图宿主：让视图铺满自己，并支持「从中心缩放」的几何动画。

    两个视图（进度条 / 饼图）重叠在同一块区域里做切换，用 QStackedWidget
    无法同时显示两层；这里改成显式几何（和 _stage 同一思路），避免布局在
    动画期间重排。

    ⚠️ 缩放为什么不用 QGraphicsEffect：本环境下 QGraphicsEffect 的 painter
       变换会被 Qt 忽略（painter.isActive() 恒为 False，painter.scale() 直接被
       丢弃、只刷告警），所以按规范「缩放实现成本过高时优先保证 opacity」的授权，
       把缩放交给视图容器的 geometry 动画（围绕中心按比例缩放），透明度仍由
       Qt 原生 QGraphicsOpacityEffect 负责。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._views = {}
        self._scales = {}

    def add_view(self, key, widget):
        widget.setParent(self)
        widget.hide()
        self._views[key] = widget
        self._scales[key] = 1.0
        self.place(key, 1.0)
        return widget

    def place(self, key, scale=1.0):
        """把某个视图按 scale 围绕宿主中心摆放（scale=1.0 即铺满）。"""
        w = self._views.get(key)
        if w is None:
            return
        try:
            s = max(0.05, float(scale))
        except (TypeError, ValueError):
            s = 1.0
        self._scales[key] = s
        r = QRectF(self.rect())
        ww = r.width() * s
        hh = r.height() * s
        w.setGeometry(int(round(r.center().x() - ww / 2.0)),
                      int(round(r.center().y() - hh / 2.0)),
                      max(1, int(round(ww))), max(1, int(round(hh))))

    def scale_of(self, key) -> float:
        return float(self._scales.get(key, 1.0))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for key in list(self._views.keys()):
            self.place(key, self._scales.get(key, 1.0))


class AmbientEffectLayer(QWidget):
    """启动页「氛围特效」背景装饰层（9 套主题共用同一个轻量粒子组件）。

    架构（阶段 B）：
      * 作为 WelcomePage 的**直接子控件**，并被压在 _stage 之下 ——
        永远位于 Logo / 卡片 / 统计 / 按钮之下，不遮挡任何 UI；
      * 不挂任何 QGraphicsEffect（避免上一轮发现的"嵌套 effect 不渲染"问题），
        纯 QTimer + paintEvent 自绘；
      * WA_TransparentForMouseEvents：物理上不拦截任何点击/滚动；
      * 生命周期完全自管：showEvent 起播、hideEvent 停表 ——
        启动页离场（_on_primary_clicked 里 self.hide()）时子控件会收到 Hide 事件，
        特效随即停止，**不存在永久常驻的高频 Timer**；
      * 9 套主题只靠一张参数表区分（effect_type + 数量/速度/尺寸/透明度区间），
        颜色一律从主题系统派生（accent_color / pcolor / pal），零 hex 字面量。

    ⚠️ 本类不改动 start_enter_animation / _on_enter_finished /
       _show_quote_animated / _on_primary_clicked 的任何一行。
    """

    FPS_MS = 33                 # ~30fps（规范要求，不用 60fps）
    MAX_PARTICLES = 20          # 数量上限（本轮按"效果更突出"上调）
    MIN_PARTICLES = 10          # 数量下限

    #: 主题参数表：theme_id -> (effect_type, 数量, 速度区间(屏高/秒), 尺寸区间(px), 透明度区间, 亮度偏移 lift)
    #  尺寸/透明度说明（雨滴）：streak 的线宽 = 尺寸 × 0.55，故 rain 的尺寸区间
    #  取 2.9~4.4 时线宽正好落在 1.6~2.4px。
    #  lift：把粒子基色朝 pcolor("text") 混合的比例（0 = 用原色，不改变观感）。
    #        深色主题的 text 近白 → 提亮；浅色主题的 text 近黑 → 压暗，
    #        因此**同一个数值在深浅模式下都朝"更高对比"方向偏移**，
    #        且不引入任何新颜色（不是第二套颜色表，只是本表多一个数值）。
    #        本轮实测：galaxy/neon_rain/cloud_dawn 基色对比不足（2.9~3.1）→ lift=0.45；
    #        summer_sea 深色下基色够亮但**浅色下只有 1.97**（合成 1.20）→ lift=0.30
    #        （浅色合成 1.30 达标；饱和度和色相几乎不变：S 0.63→0.60、H 200° 保持，
    #          深色下只是更亮一档：S 0.59→0.43、V 0.84→0.93）。
    PARAMS = {
        "sakura_campus":   ("petal",   16, (0.16, 0.34), (3.0, 6.0),  (0.16, 0.40), 0.00),
        "dusk_study":      ("dust",    14, (0.03, 0.10), (2.6, 4.6),  (0.18, 0.34), 0.00),
        "galaxy":          ("star",    18, (0.02, 0.08), (2.2, 3.6),  (0.30, 0.60), 0.45),
        "summer_sea":      ("sparkle", 16, (0.04, 0.12), (1.6, 3.4),  (0.20, 0.34), 0.30),
        "library":         ("dust",    14, (0.03, 0.09), (2.6, 4.6),  (0.18, 0.34), 0.00),
        "cloud_dawn":      ("mist",    12, (0.02, 0.06), (16.0, 34.0), (0.12, 0.20), 0.45),
        "neon_rain":       ("rain",    16, (0.45, 0.85), (2.9, 4.4),  (0.20, 0.36), 0.45),
        "snow_winter":     ("snow",    16, (0.08, 0.22), (2.0, 4.6),  (0.22, 0.52), 0.00),
        "japanese_garden": ("leaf",    14, (0.12, 0.28), (3.0, 6.0),  (0.16, 0.40), 0.00),
    }

    #: 每种特效的运动学（共用一个推进器，只改参数）
    MOTION = {
        "petal":   {"fall": 1.0,  "sway": 1.0, "twinkle": 0.0, "shape": "petal"},
        "snow":    {"fall": 1.0,  "sway": 0.7, "twinkle": 0.0, "shape": "dot"},
        "leaf":    {"fall": 1.0,  "sway": 1.2, "twinkle": 0.0, "shape": "leaf"},
        "rain":    {"fall": 1.0,  "sway": 0.0, "twinkle": 0.0, "shape": "streak", "slant": True},
        "dust":    {"fall": 0.18, "sway": 0.5, "twinkle": 0.4, "shape": "dot"},
        "star":    {"fall": 0.10, "sway": 0.4, "twinkle": 1.0, "shape": "dot"},
        "sparkle": {"fall": 0.26, "sway": 0.4, "twinkle": 0.9, "shape": "dot"},
        "mist":    {"fall": 0.0,  "sway": 0.0, "twinkle": 0.0, "shape": "blob", "horizontal": True},
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)   # 绝不拦截点击
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.NoFocus)
        self._particles = []
        self._etype = ""
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self.FPS_MS)
        self._timer.timeout.connect(self._step)
        parent = parent or self.parent()
        if parent is not None:
            parent.installEventFilter(self)          # 跟随启动页尺寸
            self.setGeometry(0, 0, parent.width(), parent.height())
        try:
            theme_manager.themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass
        self.reload()

    # ------------------------------------------------------------------
    # 生命周期：只有在"显示中"才跑定时器
    # ------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self.reload()
        self._t = 0.0
        if self._particles and not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._stop()

    def _stop(self):
        try:
            if self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass

    def eventFilter(self, obj, event):
        """跟随父页尺寸（不在 WelcomePage 里加任何几何代码）。"""
        try:
            if obj is self.parent() and event.type() in (QEvent.Resize, QEvent.Show):
                self.setGeometry(0, 0, obj.width(), obj.height())
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _on_theme_changed(self, *_args):
        """切换主题：换特效类型/数量/颜色并重绘（运行中继续跑）。"""
        self.reload()
        if self.isVisible() and self._particles and not self._timer.isActive():
            self._timer.start()

    # ------------------------------------------------------------------
    # 粒子：按当前主题重建（一个可复用组件 + 主题参数）
    # ------------------------------------------------------------------
    def reload(self):
        tid = ""
        try:
            tid = str(theme_manager.current_theme or "")
        except Exception:
            tid = ""
        etype, count, speed, size, alpha, lift = self.PARAMS.get(
            tid, self.PARAMS["sakura_campus"])
        self._etype = etype
        self._lift = float(lift or 0.0)          # 该主题的亮度偏移（0 = 保持原色）
        base = self._base_color(etype)
        n = max(self.MIN_PARTICLES, min(self.MAX_PARTICLES, int(count)))
        self._particles = []
        for _ in range(n):
            self._particles.append(self._new_particle(base, speed, size, alpha))
        self.update()

    def _new_particle(self, base: QColor, speed, size, alpha, scatter=True):
        return {
            "x": random.random(),
            "y": random.random() if scatter else -0.08,
            "v": random.uniform(*speed),          # 屏高/秒
            "size": random.uniform(*size),        # px
            "alpha": random.uniform(*alpha),
            "phase": random.uniform(0.0, math.pi * 2.0),
            "sway": random.uniform(0.35, 1.0),
            "color": QColor(base),
        }

    def _base_color(self, etype: str) -> QColor:
        """特效颜色：严格从主题系统派生（规范指定的来源），绝不写死 hex。

        最后统一做一次 lift 偏移：`_mix(基色, pcolor("text"), lift)`。
        深色主题的 text 近白 → 粒子提亮；浅色主题的 text 近黑 → 粒子压暗，
        因此同一个 lift 在深浅模式下都朝"更高对比"方向偏移，且不引入任何新颜色。
        """
        c = QColor()
        try:
            p = pal()
            if etype == "petal":
                c = pcolor("pink")
                if not c.isValid():
                    c = QColor(accent_color())
            elif etype == "star":
                c = QColor(p.get("accent2") or "")
                if not c.isValid():
                    c = QColor(accent_color())
            elif etype == "snow":
                c = pcolor("text")                     # 深色模式近白 / 浅色模式近黑
            elif etype == "rain":
                c = pcolor("blue")
                if not c.isValid():
                    c = QColor(accent_color())
            elif etype == "dust":
                c = pcolor("muted2")
            elif etype == "mist":
                # 从 pcolor("bg") 朝文字色派生：深色模式偏亮、浅色模式偏灰
                c = _mix_colors(pcolor("bg"), pcolor("text"), 0.22)
            elif etype in ("leaf", "sparkle"):
                c = QColor(accent_color())
        except Exception:
            c = QColor()
        if not c.isValid():
            try:
                c = QColor(accent_color())
            except Exception:
                c = QColor()
        # ---- 亮度偏移（主题参数表第 6 位 lift）----
        try:
            lift = max(0.0, min(1.0, float(getattr(self, "_lift", 0.0) or 0.0)))
            if lift > 0.0 and c.isValid():
                c = _mix_colors(c, pcolor("text"), lift)
        except Exception:
            pass
        return c

    # ------------------------------------------------------------------
    # 推进 + 绘制
    # ------------------------------------------------------------------
    def _step(self):
        if not self._particles:
            return
        dt = self.FPS_MS / 1000.0
        m = self.MOTION.get(self._etype, {})
        fall = float(m.get("fall", 1.0))
        sway = float(m.get("sway", 0.0))
        horizontal = bool(m.get("horizontal", False))
        slant = bool(m.get("slant", False))
        self._t += dt
        for p in self._particles:
            self._mark_dirty(p, p["x"], p["y"])      # 旧位置：先标脏，否则会留残影
            if horizontal:
                p["x"] += p["v"] * dt                    # 云雾：几乎只横向漂浮
            else:
                p["y"] += p["v"] * fall * dt
                if sway > 0.0:
                    p["x"] += math.sin(self._t * p["sway"] * 1.6 + p["phase"]) \
                              * sway * 0.012 * dt * 30.0
                if slant:
                    p["x"] += p["v"] * 0.22 * dt
            # 出界回收（回到上/左/右侧重新入场）
            if p["y"] > 1.10:
                p["y"] = -0.08
                p["x"] = random.random()
            if p["x"] > 1.10:
                p["x"] = -0.08
            elif p["x"] < -0.12:
                p["x"] = 1.06
            self._mark_dirty(p, p["x"], p["y"])      # 新位置
        # ⚠️ 刻意不用整页 self.update()：30fps 全页重绘会连带上层 UI 一起重画，
        #    这里每个粒子只刷新自己旧/新位置周围几十像素的小矩形（性能红线）。

    def _mark_dirty(self, p, xf, yf):
        """把某个粒子当前所在的小矩形标脏（含出屏裁剪）。"""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        margin = max(8.0, float(p["size"]) * 4.0)
        self.update(QRect(int(xf * w - margin), int(yf * h - margin),
                          int(margin * 2.0), int(margin * 2.0)))

    def paintEvent(self, event):
        if not self._particles:
            return
        w, h = self.width(), self.height()
        if w <= 4 or h <= 4:
            return
        m = self.MOTION.get(self._etype, {})
        shape = str(m.get("shape", "dot"))
        twinkle = float(m.get("twinkle", 0.0))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for p in self._particles:
            c = QColor(p.get("color"))
            if not c.isValid():
                continue
            a = float(p["alpha"])
            if twinkle > 0.0:
                # 极轻微闪烁：alpha 在 55%~100% 之间缓慢起伏
                a *= 0.55 + 0.45 * (0.5 + 0.5 * math.sin(
                    self._t * 1.6 + p["phase"] * 3.1))
            c.setAlphaF(max(0.0, min(1.0, a)))           # 透明度只在主题色上调 Alpha
            x, y, s = p["x"] * w, p["y"] * h, float(p["size"])
            if shape == "streak":
                pen = QPen(c)
                pen.setWidthF(max(1.0, s * 0.55))
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(QPointF(x, y), QPointF(x - s * 0.35, y + s * 3.0))
                continue
            painter.setPen(Qt.NoPen)
            painter.setBrush(c)
            if shape == "blob":
                painter.drawEllipse(QPointF(x, y), s, s * 0.5)
            elif shape in ("petal", "leaf"):
                painter.save()
                painter.translate(x, y)
                painter.rotate(math.degrees(p["phase"]) + self._t * 40.0)
                if shape == "petal":
                    painter.drawEllipse(QPointF(0.0, 0.0), s * 0.55, s * 0.95)
                else:
                    painter.drawEllipse(QPointF(0.0, 0.0), s * 0.95, s * 0.5)
                painter.restore()
            else:
                painter.drawEllipse(QPointF(x, y), s * 0.5, s * 0.5)
        painter.end()


class StatusDonut(QWidget):
    """环形饼图（Donut）：与 StatusSplitBar 平级，共享同一份数据与颜色。

    * 三段顺序与进度条一致：已通关 → 已搁置 → 未通关，起始 12 点钟方向、顺时针；
    * 小比例（已搁置 2/82 ≈ 2.4%）照实画细弧，绝不放大或篡改比例；
    * 中心挖空后用中心文字（总数量 + 「总收藏」）；
    * 总数 <= 0：画中性灰空环 + 中心「0 / 等待添加」，绝不除零；
    * 颜色由外部（WelcomePage._status_colors）统一注入 —— 与进度条是同一批
      QColor，绝不在这里二次派生。
    """

    MAX_D = 78          # 外径上限 78px（面板不给足空间时自动等比缩小，绝不溢出）
    DEFAULT_HOLE = 30   # 中心挖空直径：需容纳两行中心文字（0.85rem + 0.5rem）
    REF_D = 78.0        # 换算基准：所有比例都相对外径上限

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(40)
        self._values = (0, 0, 0)
        self._total = 0
        self._colors = (QColor(), QColor(), QColor())
        self._g1 = QColor()
        self._g2 = QColor()
        self._center_text = "0"
        self._center_label = "等待添加"
        try:
            theme_manager.themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass

    # ---------- 对外接口 ----------
    def _on_theme_changed(self, *_args):
        """主题变化：立刻重绘（颜色由 WelcomePage 注入，这里只负责刷新）。"""
        self.update()

    def set_values(self, done, paused, todo, total=None):
        def _n(v):
            try:
                return max(0, int(v or 0))
            except (TypeError, ValueError):
                return 0
        self._values = (_n(done), _n(paused), _n(todo))
        self._total = _n(total) if total is not None else sum(self._values)
        self.update()

    def set_colors(self, done, paused, todo):
        """与进度条完全相同的三个 QColor（不重新派生）。"""
        self._colors = (QColor(done), QColor(paused), QColor(todo))
        self.update()

    def set_text_colors(self, g1, g2):
        """中心数字的渐变两端（与统计卡数值同一套 stat_g1 → stat_g2）。"""
        self._g1 = _qc(g1)
        self._g2 = _qc(g2)
        self.update()

    def set_center(self, text, label):
        self._center_text = str(text or "")
        self._center_label = str(label or "")
        self.update()

    # ---------- 绘制 ----------
    def _diameter(self) -> float:
        return float(min(self.MAX_D, self.width(), self.height()))

    def paintEvent(self, event):
        w, h = int(self.width()), int(self.height())
        painter = QPainter(self)
        if w <= 2 or h <= 2:
            painter.end()
            return
        painter.setRenderHint(QPainter.Antialiasing, True)

        d = self._diameter()
        if d <= 4:
            painter.end()
            return
        ring = QRectF(0.0, 0.0, d, d)
        ring.moveCenter(QRectF(self.rect()).center())

        total = self._values[0] + self._values[1] + self._values[2]
        c_done, c_paused, c_todo = self._colors
        valid = c_done.isValid() and c_paused.isValid() and c_todo.isValid()

        if total <= 0 or not valid:
            # 空数据：中性灰空环（绝不除零、绝不假比例）
            painter.setPen(Qt.NoPen)
            painter.setBrush(pcolor("track"))
            painter.drawEllipse(ring)
        else:
            # 起始 12 点钟 = 90*16；span 取负 = 顺时针
            start = 90 * 16
            for value, color in ((self._values[0], c_done),
                                 (self._values[1], c_paused),
                                 (self._values[2], c_todo)):
                if value <= 0:
                    continue
                span = -int(round(360 * 16 * float(value) / float(total)))
                if span == 0:
                    continue
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawPie(ring, start, span)
                start += span

        # 中心挖空（规范：用 pcolor("card") 覆盖）
        hole_d = max(6.0, d * (self.DEFAULT_HOLE / self.REF_D))
        hole = QRectF(0.0, 0.0, hole_d, hole_d)
        hole.moveCenter(ring.center())
        painter.setPen(Qt.NoPen)
        painter.setBrush(pcolor("card"))
        painter.drawEllipse(hole)

        self._paint_center(painter, hole)
        painter.end()

    def _paint_center(self, painter: QPainter, hole: QRectF):
        """中心两行：上方总数量（stat_g1→stat_g2 渐变），下方说明文字（muted2）。"""
        scale = hole.width() / float(self.DEFAULT_HOLE)      # 随洞等比缩放

        f_num = QFont(self.font())
        f_num.setPixelSize(max(9, int(round(13.0 * scale))))  # 0.85rem ≈ 13.6px
        f_num.setBold(True)
        f_lbl = QFont(self.font())
        f_lbl.setPixelSize(max(6, int(round(8.0 * scale))))   # 0.5rem ≈ 8px
        f_lbl.setBold(False)

        fm_num = QFontMetrics(f_num)
        fm_lbl = QFontMetrics(f_lbl)
        # 说明文字太长（如空数据的「等待添加」）时自动缩号，保证不压到环上
        while f_lbl.pixelSize() > 6 and fm_lbl.horizontalAdvance(self._center_label) > hole.width() * 0.92:
            f_lbl.setPixelSize(f_lbl.pixelSize() - 1)
            fm_lbl = QFontMetrics(f_lbl)

        block_h = fm_num.height() + fm_lbl.height()
        top = hole.center().y() - block_h / 2.0

        num_rect = QRectF(hole.left(), top, hole.width(), float(fm_num.height()))
        lbl_rect = QRectF(hole.left(), top + fm_num.height(), hole.width(), float(fm_lbl.height()))

        # 上方：总数量（主题渐变）
        painter.setFont(f_num)
        text_w = min(float(fm_num.horizontalAdvance(self._center_text)), hole.width())
        cx = hole.center().x()
        if self._g1.isValid() and self._g2.isValid():
            grad = QLinearGradient(cx - text_w / 2.0, 0.0, cx + text_w / 2.0, 0.0)
            grad.setColorAt(0.0, self._g1)
            grad.setColorAt(1.0, self._g2)
            painter.setPen(QPen(QBrush(grad), 0.0))
        else:
            painter.setPen(pcolor("text"))
        painter.drawText(num_rect, Qt.AlignCenter, self._center_text)

        # 下方：说明文字
        painter.setFont(f_lbl)
        painter.setPen(pcolor("muted2"))
        painter.drawText(lbl_rect, Qt.AlignCenter, self._center_label)


def _with_alpha(color, alpha: float) -> QColor:
    """取主题色的副本并改 Alpha（透明度只在现有主题色上调整，绝不新增颜色）。"""
    c = QColor(color)
    try:
        c.setAlphaF(max(0.0, min(1.0, float(alpha))))
    except Exception:
        pass
    return c


class _LiquidGlassCard(GlassSurface):
    """液态玻璃统计卡：GlassSurface 毛玻璃底 + 1px 边框 + 内高光。

    按当前主题背景明度自适应两种风格（判断在 WelcomePage._apply_welcome_theme）：
      * B 通透型（亮背景，pcolor("bg").lightness() > 128）：
          底 = card @ 0.38；边框 = card @ 0.35；顶部高光 = card @ 0.45
      * C 高光型（暗背景）：
          底 = card 135° 渐变 @ 0.50→0.35；边框 = border × 1.2；顶部高光 = text @ 0.32；
          底部高光 = accent @ 0.08；左右微高光 = text @ 0.06

    ⚠️ Qt 没有 CSS 的 box-shadow / inset，QSS 也不支持 backdrop-filter；
       高光线只能在 paintEvent 里用 QPainter 画（本类），外投影由外层
       _StatsShadowHost 画在卡片背后（父控件先画、卡片盖上去）。
       所有颜色都来自 pal()/pcolor()/accent_color()，仅 Alpha 是字面量。
    """

    #: 顶部高光渐变的 Alpha 停靠点（左 0 → 15% 0.08 → 50% 0.04 → 85% 0.08 → 右 0）
    TOP_HL_STOPS = ((0.00, 0.00), (0.15, 0.08), (0.50, 0.04),
                    (0.85, 0.08), (1.00, 0.00))

    def __init__(self, parent=None, **kw):
        super().__init__(parent, **kw)
        self._liquid = None

    def set_liquid(self, style: dict):
        """注入风格参数（由 _apply_welcome_theme 每次主题切换时重算）。"""
        self._liquid = dict(style or {})
        # 底色：B 交给 GlassSurface 的 tint/alpha；C 关闭 tint，改由本类自绘渐变
        try:
            self.set_glass(tint_key="card",
                           alpha=float(self._liquid.get("tint_alpha", 0.0)))
        except Exception:
            pass
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)          # ① 毛玻璃背景 + （B 的）半透明底色
        st = self._liquid
        if not st:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if r.width() <= 2 or r.height() <= 2:
            painter.end()
            return
        radius = max(0.0, float(getattr(self, "_g_radius", 0) or 0))
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        # ② C 型：card 渐变底（135°）
        if st.get("use_gradient"):
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            grad.setColorAt(0.0, st.get("grad_a", QColor()))
            grad.setColorAt(1.0, st.get("grad_b", QColor()))
            painter.setPen(Qt.NoPen)
            painter.fillPath(path, QBrush(grad))

        # ③ 1px 边框
        bc = st.get("border")
        if bc is not None and bc.alpha() > 0:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(bc, 1.0))
            painter.drawPath(path)

        # ④⑤⑥ 直线高光：关闭抗锯齿。
        #    原因：1px 直线带 AA 时，若卡片在 dpr=1.5 下落在半个设备像素上
        #    （例如 y=437 → 655.5），线会被摊薄成两条半透明行，导致同一套参数
        #    在不同卡片上"看起来不一致"。直线不需要 AA，关掉即像素级一致。
        painter.setRenderHint(QPainter.Antialiasing, False)

        # ④ 顶部内高光：1px **极细渐变线**（左 0 → 15% .08 → 50% .04 → 85% .08 → 右 0）
        #    之前是一条纯色硬线（α0.32），深色背景下像"缝"；改用水平 Alpha 渐变后
        #    更像玻璃边缘的轻微反光。颜色仍取自主题（B: card / C: text）。
        hl = st.get("hl_top")
        if hl is not None and hl.alpha() > 0:
            x0 = r.left() + radius
            x1 = r.right() - radius
            if x1 > x0:
                grad = QLinearGradient(x0, 0.0, x1, 0.0)
                for frac, a in self.TOP_HL_STOPS:
                    cc = QColor(hl)
                    cc.setAlphaF(max(0.0, min(1.0, float(a))))
                    grad.setColorAt(float(frac), cc)
                painter.setPen(QPen(QBrush(grad), 1.0))
                painter.drawLine(QPointF(x0, 1.0), QPointF(x1, 1.0))
        # ⑤ C 型：底部 accent 高光 + 左右微高光（同样整数像素对齐，保持极淡）
        hb = st.get("hl_bottom")
        if hb is not None and hb.alpha() > 0:
            painter.setPen(QPen(hb, 1.0))
            painter.drawLine(QPointF(r.left() + radius, float(int(r.bottom()) - 1)),
                             QPointF(r.right() - radius, float(int(r.bottom()) - 1)))
        hs = st.get("hl_side")
        if hs is not None and hs.alpha() > 0:
            painter.setPen(QPen(hs, 1.0))
            painter.drawLine(QPointF(1.0, r.top() + radius),
                             QPointF(1.0, r.bottom() - radius))
            painter.drawLine(QPointF(float(int(r.right()) - 1), r.top() + radius),
                             QPointF(float(int(r.right()) - 1), r.bottom() - radius))
        painter.end()


class _StatsShadowHost(QWidget):
    """统计列宿主：在 4 张液态卡背后画一层柔和外投影。

    Qt 的 QSS 不支持 box-shadow，而 QGraphicsDropShadowEffect 会与页面级
    opacity effect 形成嵌套（此前实测会导致渲染异常）。所以这里用最稳的做法：
    父控件先画（本类 paintEvent），卡片随后画在上面 → 只在卡片之间的缝隙里
    露出投影边缘，形成"悬浮"感。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._style = None          # {"color": QColor, "layers": [(spread, alpha)], "dy": int, "glow": QColor|None}

    def set_shadow_style(self, style: dict):
        self._style = dict(style) if style else None
        self.update()

    def paintEvent(self, event):
        st = self._style
        if not st:
            return
        cards = [w for w in self.findChildren(_LiquidGlassCard)]
        if not cards:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        base = st.get("color")
        layers = list(st.get("layers") or [])
        dy = float(st.get("dy", 0) or 0)
        radius = 16.0
        for card in cards:
            if not card.isVisible():
                continue
            gr = QRectF(card.geometry())
            glow = st.get("glow")
            if glow is not None and glow.alpha() > 0:      # C 型：accent 外发光
                for spread, a in ((8, 0.5), (4, 0.5)):
                    cc = QColor(glow)
                    cc.setAlphaF(min(1.0, glow.alphaF() * a))
                    painter.setBrush(cc)
                    painter.drawRoundedRect(
                        gr.adjusted(-spread, -spread + dy * 0.3, spread, spread + dy * 0.3),
                        radius + spread, radius + spread)
            if base is None or not layers:
                continue
            for spread, a in layers:                       # 分层叠加 ≈ 模糊衰减
                cc = QColor(base)
                cc.setAlphaF(max(0.0, min(1.0, float(a))))
                painter.setBrush(cc)
                painter.drawRoundedRect(
                    gr.adjusted(-spread, -spread * 0.55 + dy, spread, spread * 1.15 + dy),
                    radius + spread, radius + spread)
        painter.end()


class _BreakdownCard(_LiquidGlassCard):
    """「收藏状态构成」面板：整块区域可点击切换视图（不放任何图标提示）。

    继承 _LiquidGlassCard → 与三张数据卡共用同一套液态玻璃风格。
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, name="welcomeStatBreakdown", blur=True,
                         alpha=glass_alpha("panel"), tint_key="card", radius=16)
        self.setCursor(Qt.PointingHandCursor)      # 悬停变手型

    def mousePressEvent(self, event):
        # 子控件（QLabel / 自制控件）默认忽略鼠标事件 → 会冒泡到这里，
        # 因此"点面板任意空白处（含图例文字）"都能切换视图。
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class AspectBox(QWidget):
    """比例容器：保证唯一的子控件保持 3:4，并在自身区域内水平 + 垂直居中。

    设计要点（这是"卡片永远不拉伸变形 + 永不挤在顶部"的关键）：
      * 子控件永远拿固定尺寸：由本容器按自己的宽高算出"能塞下的最大 3:4 矩形"，
        所以物理上不可能被布局拉扁 / 拉长。
      * 居中交给 QGridLayout + Qt.AlignCenter：
        行/列 stretch 都设为 1 → 单元格铺满整个容器 → 对齐标志把子控件摆在正中。
      * 不用 heightForWidth()：那套依赖父布局逐级支持，放进 QStackedWidget
        这类首帧不可见的容器里很容易算错，属于不确定性行为；这里改成显式几何计算。
    """

    RATIO = 3.0 / 4.0     # 宽 / 高 = 3:4
    MAX_H = 520           # 卡片最大高度上限（超宽/超高屏幕下不让卡片无限变大）

    def __init__(self, child=None, parent=None, max_h=None):
        super().__init__(parent)
        #: 本实例的高度上限；None = 沿用类属性 MAX_H（对既有调用零影响）
        self._capped = bool(max_h)
        self._max_h = int(max_h) if max_h else int(self.MAX_H)
        self._child = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(0)
        self._grid.setRowStretch(0, 1)
        self._grid.setColumnStretch(0, 1)
        if child is not None:
            self.set_card(child)

    # ⚠️ 必须自己给 hint：子控件被 setFixedSize 后，QGridLayout 会把"这个固定尺寸"
    #    当成容器的最小尺寸，导致容器只能变大不能回缩（棘轮效应：
    #    空状态框 / 小窗口化时尺寸会卡在历史最大值上）。
    #    这里显式返回一个小 hint，让 QHBoxLayout 的 stretch 真正说了算。
    def sizeHint(self) -> QSize:
        # 限高变体（最近添加卡片）：首选尺寸 = 限高后的 3:4 卡片尺寸，
        # 这样放进"两端 stretch + 槽位不拉伸"的卡片行里时，
        # 槽位宽度正好等于卡片宽度（卡片成组居中，且间距就是 layout spacing）；
        # 未限高的旧用法仍返回小 hint（保持原有防棘轮行为不变）。
        if self._capped:
            return QSize(max(40, int(round(self._max_h * self.RATIO))), int(self._max_h))
        return QSize(180, 240)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, 53)

    def card(self):
        return self._child

    def set_card(self, widget):
        """放入 / 替换子控件（传 None 表示清空）。正常卡片与空状态框共用同一入口。"""
        if self._child is not None:
            self._grid.removeWidget(self._child)
            self._child.setParent(None)
            self._child.deleteLater()
            self._child = None
        if widget is None:
            return
        self._child = widget
        self._grid.addWidget(widget, 0, 0, Qt.AlignCenter)
        self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        if self._child is None:
            return
        w, h = self.width(), self.height()
        if w <= 8 or h <= 8:
            return
        ch = min(h, self._max_h)
        cw = int(ch * self.RATIO)
        if cw > w:                      # 窗口偏窄：改成由宽度决定高度
            cw = w
            ch = int(cw / self.RATIO)
        self._child.setFixedSize(max(40, cw), max(53, ch))


class WelcomeGameCard(QFrame):
    """「最近添加」卡片：封面 + 底部深色渐变遮罩 + 白色文字。

    卡片只负责画自己：尺寸由外层 AspectBox 给死，本身不做任何比例计算，
    也不认识数据库/业务，纯展示。
    """

    RADIUS = 16

    def __init__(self, game: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("welcomeCard")
        self.setAttribute(Qt.WA_StyledBackground, False)   # 完全自绘
        self._game = dict(game or {})
        self._cover_rel = str(self._game.get("cover_path") or "")
        self._pix = None
        self._pix_size = QSize()
        self._build_text()

    # ---------- 文本 ----------
    def _meta_text(self) -> str:
        parts = []
        status = str(self._game.get("status") or "").strip()
        if status:
            parts.append(status)
        try:
            rating = float(self._game.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0.0
        parts.append("评分 " + fmt_rating(rating) if rating > 0 else "未评分")
        year = str(self._game.get("release_date") or "").strip()[:4]
        if year.isdigit():
            parts.append(year)
        return " · ".join(parts)

    def _build_text(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 13)
        lay.setSpacing(3)
        lay.addStretch(1)                     # 文字压到底部，上方留白
        self.title_lbl = ElidedLabel(str(self._game.get("title") or "未命名"))
        self.title_lbl.setObjectName("welcomeCardTitle")
        self.meta_lbl = ElidedLabel(self._meta_text())
        self.meta_lbl.setObjectName("welcomeCardMeta")
        lay.addWidget(self.title_lbl)
        lay.addWidget(self.meta_lbl)

    # ---------- 绘制 ----------
    def _ensure_cover(self):
        w, h = self.width(), self.height()
        if w < 8 or h < 8:
            return
        if self._pix is not None and self._pix_size == QSize(w, h):
            return
        try:
            self._pix = cover_pixmap(self._cover_rel, w, h)   # 现成 API：含 dpr 与无封面兜底
        except Exception:
            self._pix = None
        self._pix_size = QSize(w, h)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ensure_cover()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        if w < 4 or h < 4:
            painter.end()
            return
        self._ensure_cover()

        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), self.RADIUS, self.RADIUS)
        painter.setClipPath(path)
        if self._pix is not None and not self._pix.isNull():
            painter.drawPixmap(0, 0, self._pix)

        # 底部深色渐变遮罩：颜色取自调色板 shadow token（不硬编码），保证白字清晰可读
        top = pcolor("shadow")
        top.setAlphaF(0.0)
        bottom = pcolor("shadow")
        bottom.setAlphaF(0.82)
        grad = QLinearGradient(0, h * 0.45, 0, h)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        painter.fillRect(0, 0, w, h, grad)

        # 1px 描边（主题 border token），让卡片边缘与背景分开
        painter.setClipping(False)
        pen = QPen(pcolor("border", "border_a"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()


class EmptyStateBox(GlassSurface):
    """0 款游戏时的空状态引导框：与正常卡片同样的 3:4、同样垂直居中（由 AspectBox 保证）。"""

    def __init__(self, parent=None):
        super().__init__(parent, name="welcomeEmpty", blur=True,
                         alpha=glass_alpha("panel"), tint_key="card", radius=16)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 22)
        lay.setSpacing(10)
        lay.addStretch(1)

        icon = QLabel("＋")
        icon.setObjectName("welcomeEmptyIcon")
        icon.setTextFormat(Qt.PlainText)
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon, 0, Qt.AlignHCenter)

        title = QLabel("这里还没有任何回忆")
        title.setObjectName("welcomeEmptyTitle")
        title.setTextFormat(Qt.PlainText)
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        lay.addWidget(title)

        hint = QLabel("点击下方「添加游戏」，\n把第一部作品写进回忆录吧。")
        hint.setObjectName("welcomeEmptyHint")
        hint.setTextFormat(Qt.PlainText)
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setMaximumWidth(260)
        lay.addWidget(hint, 0, Qt.AlignHCenter)

        lay.addStretch(1)


# ============================================================
# 启动页本体
# ============================================================
_QSS_TEMPLATE = """
/* 基础兜底：任何没被下面规则点名的 QLabel 也都拿主题文字色，绝不落到"系统白字" */
QLabel { color: $text; }

/* 主标题真正由 GradientTitleLabel 自绘渐变，这里的 color 只是兜底 */
QLabel#welcomeTitle { color: $text; font-size: 24px; font-weight: 700; }
QLabel#welcomeSubtitle { color: $secondary; font-size: 13px; }

/* Banner 右侧日期问候（启动时计算一次；颜色随主题，内容为固定信息） */
QLabel#welcomeHello { color: $muted; font-size: 13px; }
QLabel#welcomeDot { color: $muted2; font-size: 13px; }
QLabel#welcomeDate { color: $muted2; font-size: 12px; }
QLabel#welcomeSection { color: $text; font-size: 16px; font-weight: 700; }
QLabel#welcomeNote { color: $tertiary; font-size: 12px; }

QLabel#welcomeCardTitle { color: $on_media; font-size: 15px; font-weight: 700; }
QLabel#welcomeCardMeta { color: $on_media_soft; font-size: 12px; }

QLabel#welcomeQuote { color: $secondary; font-size: 13px; font-style: italic; }

/* 统计卡：图标 + 标签 + 数值。
   数值由 GradientRollLabel 自绘主题渐变，字号在类内常量控制（Qt QSS 不支持 rem），
   所以这里不再给 #welcomeStatValue 设 font-size / color。 */
QLabel#welcomeStatIcon { font-size: 26px; }
QLabel#welcomeStatCap { color: $muted2; font-size: 12px; }
/* 面板标题 0.7rem ≈ 11px；视图图例 0.6~0.64rem ≈ 10px（两种视图共用同一条规则） */
QLabel#welcomeStatLegendTitle { color: $muted2; font-size: 11px; }
QLabel#welcomeStatLegend { color: $secondary; font-size: 10px; }

/* 「最近添加」胶囊容器：完全透明（卡片直接浮在背景图上），无边框、无底色。
   保留 16px 圆角声明（透明底无实际绘制，内容永远不会被裁剪）。 */
QWidget#welcomeRecentPanel {
    background: transparent;
    border: none;
    border-radius: 16px;
}

QLabel#welcomeEmptyIcon { color: $accent; font-size: 32px; font-weight: 700; }
QLabel#welcomeEmptyTitle { color: $text; font-size: 16px; font-weight: 700; }
QLabel#welcomeEmptyHint { color: $tertiary; font-size: 13px; }

QPushButton#welcomePrimary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $g1, stop:1 $g2);
    color: $on_grad;
    border: none;
    border-radius: 14px;
    padding: 12px 34px;
    font-size: 15px;
    font-weight: 700;
}
QPushButton#welcomePrimary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $g2, stop:1 $g1);
}
QPushButton#welcomePrimary:pressed { background: $accent_hover; }
QPushButton#welcomePrimary:disabled { color: $tertiary; }

QPushButton#welcomeSecondary {
    background: $btn;
    color: $text;
    border: 1px solid $border;
    border-radius: 14px;
    padding: 12px 24px;
    font-size: 14px;
}
QPushButton#welcomeSecondary:hover { background: $btn_hover; border-color: $accent; }
QPushButton#welcomeSecondary:pressed { background: $btn_press; }
QPushButton#welcomeSecondary:disabled { color: $tertiary; border-color: $border; }
"""


def _welcome_qss(tokens: dict = None) -> str:
    """按当前主题生成启动页专属 QSS（颜色全部来自 _text_tokens()，零硬编码）。"""
    return Template(_QSS_TEMPLATE).safe_substitute(tokens or _text_tokens())


#: 样式表兜底映射：objectName -> 取哪个 token
#    （页面样式表若被环境拒绝/部分忽略，QLabel 会回落到 QPalette，
#      在系统深色模式下就是"白字压浅底"；这里用同一套颜色显式写进调色板兜住）
_PALETTE_FALLBACK = (
    ("welcomeTitle", "text"),
    ("welcomeSubtitle", "secondary"),
    ("welcomeHello", "muted"),
    ("welcomeDot", "muted2"),
    ("welcomeDate", "muted2"),
    ("welcomeSection", "text"),
    ("welcomeNote", "tertiary"),
    ("welcomeCardTitle", "on_media"),
    ("welcomeCardMeta", "on_media"),
    ("welcomeQuote", "secondary"),
    ("welcomeStatCap", "muted2"),
    ("welcomeStatValue", "accent"),
    ("welcomeStatLegendTitle", "muted2"),
    ("welcomeStatLegend", "secondary"),
    ("welcomeEmptyIcon", "accent"),
    ("welcomeEmptyTitle", "text"),
    ("welcomeEmptyHint", "tertiary"),
)


class WelcomePage(QWidget):
    """启动页：顶部 Banner + 左右分栏（最近添加 / 统计数据）+ 底部操作区 + 随机台词。

    对外信号：
        entered          —— 渐入动画结束（第二轮：触发数字 roll-up）
        leave_finished   —— 离场动画结束（第二轮：MainWindow 收到后切到主界面）
        add_game_clicked —— 点击「添加游戏」
        identify_clicked —— 点击「AI 识图」
    """

    #: 左右分栏的右侧固定宽度（统计数据列）
    STAT_COL_W = 300
    #: 底部台词最大宽度（超长自动截断）
    QUOTE_MAX_W = 760

    # ---- 动画参数（全部集中在这里，方便调）----
    ENTER_MS = 1000         # 渐入时长：整页透明度 + _stage 位移
    SLIDE_PX = 40           # 渐入起点：从下方 40px 处"由下至上"升起
    ROLL_MS = 800           # 统计数字 roll-up 时长（RollLabel 内部使用）
    QUOTE_DELAY_MS = 1000   # 渐入结束后，台词延迟多久开始淡入
    QUOTE_FADE_MS = 400     # 台词淡入时长
    LEAVE_MS = 500          # 离场时长：向内收缩 + 淡出
    LEAVE_SCALE = 0.95      # 离场终点：快照向中心收缩到 95%（宽高各缩 2.5%）

    entered = Signal()
    leave_finished = Signal()
    add_game_clicked = Signal()
    identify_clicked = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._leaving = False

        # 整页透明：背景由 MainWindow.paintEvent 的"整窗背景层"负责，
        # 本页绝不自己贴图 / 画底色（这样才能复用主题背景与自定义背景）。
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setObjectName("welcomeRoot")

        # 无 layout 的顶层 + 手动定位的 _stage：
        # "由下至上"动画需要直接驱动 _stage.pos，只有不被布局管理的控件才能安全地动 pos。
        self._stage = QWidget(self)
        self._stage.setAttribute(Qt.WA_StyledBackground, False)
        self._build_ui()

        # ---- 启动氛围特效层（阶段 B）----
        # 作为本页直接子控件创建，并把 _stage 抬到它上面：
        # 视觉层次 = 整窗背景 → 氛围特效 → Logo/卡片/统计/按钮。
        # 特效层靠自身 showEvent / hideEvent 起停，不改动任何原动画代码。
        try:
            self._ambient = AmbientEffectLayer(self)
            self._stage.raise_()
        except Exception:
            self._ambient = None

        # ---- 动画资源 ----
        self._entering = False
        self._enter_started = False
        self._enter_group = None
        self._leave_group = None
        self._snap = None
        # 整页淡入：用 QGraphicsOpacityEffect 做 0→1（初始 0，等动画把它点亮）
        self._enter_effect = QGraphicsOpacityEffect(self)
        self._enter_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._enter_effect)
        # 台词淡入：独立效果（初始 0，等"渐入完成后 1 秒"再淡入）
        self._quote_effect = QGraphicsOpacityEffect(self.quote_lbl)
        self._quote_effect.setOpacity(0.0)
        self.quote_lbl.setGraphicsEffect(self._quote_effect)
        self._quote_timer = QTimer(self)
        self._quote_timer.setSingleShot(True)
        self._quote_timer.timeout.connect(self._show_quote_animated)

        self.reload()                       # 读数据：最近 3 款 + 三项统计 + 一句台词
        self._apply_welcome_theme()
        try:
            theme_manager.themeChanged.connect(self._apply_welcome_theme)
        except Exception:
            pass
        # 渐入动画播完后，把已经完成使命的页面级 opacity effect 退休（见方法内说明）。
        # ⚠️ 只挂在公开信号 entered 上，不改任何锁定动画方法；entered 只在正常播完时发出，
        #    若用户在入场动画中途点离场，effect 保持启用，离场逻辑照常。
        try:
            self.entered.connect(self._retire_enter_effect)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 入场 effect 退休（幂等）
    # ------------------------------------------------------------------
    def _retire_enter_effect(self):
        """渐入动画结束后关闭页面级 QGraphicsOpacityEffect。

        为什么需要（2026-09 实测定位）：
          * 该 effect 在 opacity=1.0 时对画面已无作用，但**依然处于"活动"状态**，
            于是页面下**任何一次重绘**都会让 Qt 重新渲染 effect source，而这条
            管线在本环境是坏的 —— 每次重绘固定刷 7 条 QPainter 告警；
          * 更严重的是它会连坐页面内子控件自己的 QGraphicsOpacityEffect：
            子控件 opacity 一旦离开 1.0 就**完全不渲染**（视图切换因此出现
            "缩没 → 空一下 → 冒出来"）。
        关闭它即可同时消除这两件事；实测告警 420 → 0，子控件 0.2/0.5/0.75
        全部恢复正常渲染。

        * 用 setEnabled(False) 而不是 setGraphicsEffect(None)：effect 对象保留，
          离场 _on_primary_clicked 里对它的 setOpacity(1.0) 仍是合法调用；
        * 幂等：重复调用无副作用。
        """
        try:
            eff = getattr(self, "_enter_effect", None)
            if eff is not None and eff.isEnabled():
                eff.setEnabled(False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 渐入动画（由 showEvent 用 singleShot(0) 起播）
    # ------------------------------------------------------------------
    def showEvent(self, event):
        """首次显示时启动渐入；singleShot(0) 是为了等 main.py 的 _apply_bg()
        把毛玻璃层算好、布局稳定后再起播（否则前几帧玻璃会闪）。"""
        super().showEvent(event)
        if self._enter_started or self._leaving:
            return
        self._enter_started = True
        QTimer.singleShot(0, self.start_enter_animation)

    def start_enter_animation(self):
        """整页透明度 0→1 + _stage 从 (0,+40) 升到 (0,0)，1s / OutCubic。"""
        if self._leaving or self._enter_group is not None:
            return
        self._entering = True
        self._enter_effect.setOpacity(0.0)
        self._stage.move(0, self.SLIDE_PX)

        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self._enter_effect, b"opacity", group)
        fade.setDuration(self.ENTER_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        slide = QPropertyAnimation(self._stage, b"pos", group)
        slide.setDuration(self.ENTER_MS)
        slide.setStartValue(QPoint(0, self.SLIDE_PX))
        slide.setEndValue(QPoint(0, 0))
        for anim in (fade, slide):
            anim.setEasingCurve(QEasingCurve.OutCubic)

        group.finished.connect(self._on_enter_finished)
        self._enter_group = group
        group.start()

    def _on_enter_finished(self):
        """渐入结束：归位 → 数字 roll-up → 台词延迟计时 → 发 entered 信号。"""
        self._entering = False
        try:
            self._stage.setGeometry(0, 0, self.width(), self.height())
        except Exception:
            pass
        self._start_stat_rollups()
        if self.QUOTE_DELAY_MS > 0:
            self._quote_timer.start(self.QUOTE_DELAY_MS)
        else:
            self._show_quote_animated()
        self.entered.emit()

    def _start_stat_rollups(self):
        """三项统计数字：0 → 目标值（0.8s / OutCubic；目标为 0 时只显示空文案）。"""
        for lbl in (getattr(self, "stat_total", None),
                    getattr(self, "stat_cleared", None),
                    getattr(self, "stat_avg", None)):
            if lbl is not None:
                try:
                    lbl.play()
                except Exception:
                    pass

    def _show_quote_animated(self):
        """台词：延迟结束后 0.4s 淡入（0→1）。"""
        if self._leaving or self.quote_lbl is None:
            return
        try:
            self._refresh_quote()               # 每次启动随机取一句
            self._quote_effect.setOpacity(0.0)
            anim = QPropertyAnimation(self._quote_effect, b"opacity", self)
            anim.setDuration(self.QUOTE_FADE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._quote_anim = anim
        except Exception:
            try:
                self._quote_effect.setOpacity(1.0)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # UI 组装
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self._stage)
        root.setContentsMargins(36, 26, 36, 20)
        root.setSpacing(14)

        root.addWidget(self._build_banner())

        # 中段：左右分栏，stretch=1 吃掉除 Banner / 操作区 / 台词以外的全部高度，
        # 左侧卡片因此永远是"垂直居中"，不会挤在顶部留出大片空白。
        main = QHBoxLayout()
        main.setSpacing(22)
        main.addWidget(self._build_recent_column(), 1)
        main.addWidget(self._build_stats_column(), 0)
        root.addLayout(main, 1)

        root.addLayout(self._build_actions())

        self.quote_lbl = ElidedLabel("")
        self.quote_lbl.setObjectName("welcomeQuote")
        self.quote_lbl.setAlignment(Qt.AlignCenter)
        self.quote_lbl.setMaximumWidth(self.QUOTE_MAX_W)
        self.quote_lbl.setMinimumHeight(20)
        root.addWidget(self.quote_lbl, 0, Qt.AlignHCenter)

    def _build_banner(self) -> GlassSurface:
        """顶部 Banner：55x55 圆角图标 + 标题 / 副标题。玻璃拟态，无任何切换按钮。"""
        banner = GlassSurface(name="welcomeBanner", blur=True,
                              alpha=glass_alpha("panel"), tint_key="card", radius=18)
        banner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        banner.setFixedHeight(96)

        lay = QHBoxLayout(banner)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(16)

        logo = QLabel()
        logo.setObjectName("welcomeLogo")
        logo.setFixedSize(55, 55)
        logo.setPixmap(app_icon_pixmap(55, radius=14))
        lay.addWidget(logo, 0, Qt.AlignVCenter)

        box = QVBoxLayout()
        box.setSpacing(2)
        title = GradientTitleLabel(APP_NAME)
        title.setObjectName("welcomeTitle")
        self.banner_title = title
        subtitle = QLabel("你的私人视觉小说收藏馆")
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setTextFormat(Qt.PlainText)
        box.addWidget(title)
        box.addWidget(subtitle)
        lay.addLayout(box, 1)

        # ---- 右侧：日期问候（启动时计算一次，内容固定；颜色随主题）----
        hello_text, date_text = self._greeting_parts()
        self.when_hello = QLabel(hello_text)
        self.when_hello.setObjectName("welcomeHello")
        self.when_hello.setTextFormat(Qt.PlainText)
        self.when_dot = QLabel("·")
        self.when_dot.setObjectName("welcomeDot")
        self.when_dot.setTextFormat(Qt.PlainText)
        self.when_date = QLabel(date_text)
        self.when_date.setObjectName("welcomeDate")
        self.when_date.setTextFormat(Qt.PlainText)

        when = QHBoxLayout()
        when.setSpacing(0)
        when.addWidget(self.when_hello, 0, Qt.AlignVCenter)
        when.addSpacing(10)                      # 问候语 ↔ 分隔符 10px
        when.addWidget(self.when_dot, 0, Qt.AlignVCenter)
        when.addSpacing(10)                      # 分隔符 ↔ 日期 10px（左右对称）
        when.addWidget(self.when_date, 0, Qt.AlignVCenter)
        self.when_lbl = self.when_hello          # 兼容旧引用
        lay.addLayout(when, 0)                   # 右对齐（左侧 box 已占 stretch=1）

        self.banner = banner
        return banner

    @staticmethod
    def _greeting_parts():
        """Banner 右侧日期问候：启动时计算一次（不实时刷新、不随主题变化）。

        问候语按系统小时：05~09 早上好 / 09~12 上午好 / 12~18 下午好 /
        18~24 晚上好 / 00~05 夜深了；日期 = YYYY-MM-DD · 周X（中文）。
        """
        now = datetime.datetime.now()
        h = now.hour
        if 5 <= h < 9:
            hello = "早上好"
        elif 9 <= h < 12:
            hello = "上午好"
        elif 12 <= h < 18:
            hello = "下午好"
        elif 18 <= h < 24:
            hello = "晚上好"
        else:
            hello = "夜深了"
        week = "一二三四五六日"[now.weekday()]      # weekday(): 周一=0
        return hello, "%s · 周%s" % (now.strftime("%Y-%m-%d"), week)

    #: 「最近添加」卡片高度上限（3:4 → 225×300）；容器内不再撑满
    RECENT_CARD_MAX_H = 300

    def _build_recent_column(self) -> QWidget:
        """左栏（占主要宽度）：一个**去虚化**的半透明胶囊容器，内含「标题 + 三张卡片」。

        布局（本轮最终版）：
          * 容器 = 普通 QWidget + QSS（`#welcomeRecentPanel`）：**半透明纯色底**
            （pcolor("card") + alpha 0.78）+ **1px 描边** + 圆角 16，与右侧毛玻璃卡区分；
            ⚠️ 不用 GlassSurface(blur=False)：它仍会先画一张**清晰壁纸**再叠 tint，
               得不到"纯色底"，而且 GlassSurface 本身没有全边框（只有 edge_top/right 单边线）。
          * 容器 stretch=1 填满 main 行 → 与右侧统计列**顶/底齐平**；
          * 内边距 左右 20 / 上下 16；
          * 「标题 + 卡片」作为一个整体在容器内**上下居中**（两端 addStretch(1)），
            标题与卡片间距保持 12px；
          * 卡片 = 225×300（限高 300 的 3:4），间距 24，成组水平居中。
        """
        panel = QWidget()
        panel.setObjectName("welcomeRecentPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)   # QSS 背景生效
        col = QVBoxLayout(panel)
        col.setContentsMargins(20, 16, 20, 16)      # 内边距 左右 20 / 上下 16
        col.setSpacing(12)                           # 标题 ↔ 卡片 间距 12

        head = QHBoxLayout()
        head.setSpacing(8)
        head.setContentsMargins(12, 0, 12, 0)        # 标题行左右各缩进 12px（离开容器边缘）
        sec = QLabel("最近添加")
        sec.setObjectName("welcomeSection")
        sec.setTextFormat(Qt.PlainText)
        head.addWidget(sec)
        head.addStretch(1)
        self.recent_note = QLabel("")
        self.recent_note.setObjectName("welcomeNote")
        self.recent_note.setTextFormat(Qt.PlainText)
        head.addWidget(self.recent_note)

        row = QHBoxLayout()
        row.setSpacing(24)                           # 卡片间距 24
        row.addStretch(1)
        self._recent_boxes = []
        for _ in range(3):
            box = AspectBox(max_h=self.RECENT_CARD_MAX_H)
            self._recent_boxes.append(box)
            row.addWidget(box, 0)                    # 槽位按首选尺寸（225），不拉伸 → 成组居中
        row.addStretch(1)

        col.addStretch(1)                            # ★ 上留白
        col.addLayout(head, 0)                       # 标题
        col.addLayout(row, 0)                        # 卡片（不再占满剩余高度）
        col.addStretch(1)                            # ★ 下留白 → 整体垂直居中
        self._recent_row = row
        self._recent_panel = panel
        return panel

    def _build_stats_column(self) -> QWidget:
        """右栏（固定宽度）：四块面板等分高度（每块 stretch=1），与左侧内容区上下齐平。

        结构（阶段 A 最终版）：
            📚 总数量   |   ✅ 已通关   |   ⭐ 平均评分   |   收藏状态构成（图例 + 三段进度条）

        * 不再放「统计数据」大标题：4 块面板本身就是一列，顶部/底部与左侧齐平；
        * 三张统计卡继续沿用 stat_total / stat_cleared / stat_avg 这三个属性名，
          因此 _start_stat_rollups()（原启动动画里的数字滚动）无需任何改动。
        """
        holder = _StatsShadowHost()
        self._stat_shadow_host = holder
        holder.setFixedWidth(self.STAT_COL_W)
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        card_total, self.stat_total = self._make_stat_card("📚", "总数量", "%d")
        card_cleared, self.stat_cleared = self._make_stat_card("✅", "已通关", "%d")
        card_avg, self.stat_avg = self._make_stat_card("⭐", "平均评分", "%.1f")
        card_breakdown = self._make_breakdown_card()

        # ★ 四块 flex:1 —— 均分整个可用高度
        for card in (card_total, card_cleared, card_avg, card_breakdown):
            col.addWidget(card, 1)
        self._stat_cards = [card_total, card_cleared, card_avg, card_breakdown]
        return holder

    def _make_stat_card(self, icon: str, caption: str, fmt: str):
        """单张统计卡：图标 + 标签 + 数值，内容垂直居中，数值走主题渐变自绘 + 0→目标值滚动。"""
        card = _LiquidGlassCard(name="welcomeStat", blur=True,
                                alpha=glass_alpha("panel"), tint_key="card", radius=16)
        card.setMinimumHeight(84)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)      # 内边距 18px 20px
        lay.setSpacing(0)

        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("welcomeStatIcon")
        icon_lbl.setTextFormat(Qt.PlainText)

        cap = QLabel(caption)
        cap.setObjectName("welcomeStatCap")
        cap.setTextFormat(Qt.PlainText)

        value = GradientRollLabel(fmt)
        value.setObjectName("welcomeStatValue")

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(icon_lbl, 0, Qt.AlignVCenter)
        row.addWidget(cap, 0, Qt.AlignVCenter)
        row.addStretch(1)
        row.addWidget(value, 0, Qt.AlignVCenter | Qt.AlignRight)

        lay.addStretch(1)               # ① 内容垂直居中
        lay.addLayout(row)
        lay.addStretch(1)               # ②
        return card, value

    #: 图例圆点直径（规范：6px）
    LEGEND_DOT_PX = 6

    def _make_legend_row(self):
        """图例行：●已通关 27 ●已搁置 2 ●未通关 53。

        进度条视图与饼图视图各有一行，共用这一份实现（不新造第二套逻辑）；
        颜色/数字在 _load_stats() 与 _apply_status_colors() 里统一注入。
        返回 (layout, labels, dots)。
        """
        row = QHBoxLayout()
        row.setSpacing(9)
        labels, dots = [], []
        for _ in self._legend_names:
            dot = _LegendDot()
            lbl = QLabel("")
            lbl.setObjectName("welcomeStatLegend")
            lbl.setTextFormat(Qt.PlainText)
            labels.append(lbl)
            dots.append(dot)
            row.addWidget(dot, 0, Qt.AlignVCenter)
            row.addWidget(lbl, 0, Qt.AlignVCenter)
            row.addStretch(1)
        return row, labels, dots

    def _make_breakdown_card(self):
        """第 4 块面板：收藏状态构成（标题 + 可点击切换的「进度条 / 饼图」两个视图）。

        * 默认显示进度条视图；
        * 点击面板任意空白处切换（不放任何 ⇄ 图标），悬停变手型；
        * 两个视图共享同一份数字与同一批 QColor；切换只换画法，不换数据/配色。
        """
        card = _BreakdownCard()
        card.setMinimumHeight(96)
        card.clicked.connect(self._toggle_breakdown_view)
        self._breakdown_card = card

        self._legend_names = ("已通关", "已搁置", "未通关")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)      # 面板内边距 10px 12px
        lay.setSpacing(4)

        title = QLabel("收藏状态构成")
        title.setObjectName("welcomeStatLegendTitle")
        title.setTextFormat(Qt.PlainText)
        title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # 标题固定高度：无论视图多高都不许被压缩/遮挡（0.7rem ≈ 11px）
        title.setFixedHeight(15)
        self._breakdown_title = title

        # ---------- 视图宿主（两个视图重叠在同一区域） ----------
        self._view_host = _ViewHost()

        # 视图 1：三段进度条
        self.bar_view = QWidget()
        bl = QVBoxLayout(self.bar_view)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        bar_legend, self._legend_labels, self._legend_dots = self._make_legend_row()
        self.status_bar = StatusSplitBar()
        bl.addStretch(1)
        bl.addLayout(bar_legend)
        bl.addWidget(self.status_bar, 0)
        bl.addStretch(1)

        # 视图 2：环形饼图
        self.donut_view = QWidget()
        dl = QVBoxLayout(self.donut_view)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(2)
        self.status_donut = StatusDonut()
        donut_legend, self._donut_legend_labels, self._donut_legend_dots = self._make_legend_row()
        dl.addWidget(self.status_donut, 1)
        dl.addLayout(donut_legend, 0)

        self._view_host.add_view("bar", self.bar_view)
        self._view_host.add_view("donut", self.donut_view)

        # ---------- 切换动画资源 ----------
        self._view_mode = "bar"          # 默认：进度条视图
        self._switching = False          # 闸门：动画期间连点无效
        self._view_effects = {}          # key -> QGraphicsOpacityEffect（Qt 原生）
        for key, view in (("bar", self.bar_view), ("donut", self.donut_view)):
            try:
                eff = QGraphicsOpacityEffect(view)
                eff.setOpacity(1.0)
                view.setGraphicsEffect(eff)
                self._view_effects[key] = eff
            except Exception:
                pass
        self.bar_view.show()
        self.donut_view.hide()

        lay.addWidget(title, 0)
        lay.addWidget(self._view_host, 1)       # 视图区域 flex:1，填满剩余高度
        return card

    # ------------------------------------------------------------------
    # 视图切换：进度条 ⇄ 饼图（渐出 250ms + 渐入 250ms，共 500ms / OutCubic）
    # ------------------------------------------------------------------
    def _toggle_breakdown_view(self):
        """点击面板空白处切换视图；动画期间由 _switching 闸门挡住连点。"""
        if getattr(self, "_switching", False):
            return
        bar_view = getattr(self, "bar_view", None)
        donut_view = getattr(self, "donut_view", None)
        if bar_view is None or donut_view is None:
            return
        cur = "donut" if str(getattr(self, "_view_mode", "bar")) == "donut" else "bar"
        nxt = "donut" if cur == "bar" else "bar"
        out_view = bar_view if cur == "bar" else donut_view
        in_view = donut_view if nxt == "donut" else bar_view
        effects = getattr(self, "_view_effects", {})
        out_eff = effects.get(cur)
        in_eff = effects.get(nxt)

        host = getattr(self, "_view_host", None)
        if out_eff is None or in_eff is None or host is None:
            # 效果器不可用：直接切换，绝不把界面卡死
            out_view.hide()
            in_view.show()
            if host is not None:
                host.place(nxt, 1.0)
            self._view_mode = nxt
            return

        self._switching = True
        try:
            # ★ 两个视图都先显示：新视图从 opacity=0 起就"在场"（不可见）。
            #   这样进入渐入段时它早已完成布局与贴图，**250ms 边界不再做任何
            #   show()/hide()/复位**——那正是上一版"跳一下"的来源
            #   （QSequentialAnimationGroup 顺延下一段的内部处理先于 g_out.finished，
            #     导致 g_in 已开始推进后我才 show()，新视图首个可见帧被吃掉一截）。
            out_view.show()
            in_view.show()
            out_eff.setOpacity(1.0)                 # 当前视图：opacity 1.0 / scale 1.00
            host.place(cur, 1.0)
            in_eff.setOpacity(0.0)                  # 新视图：opacity 0.0 / scale 1.15
            host.place(nxt, 1.15)

            # ---- 渐出：opacity 1→0 + 容器 geometry 1.00→0.85（250ms） ----
            g_out = QParallelAnimationGroup(self)
            a_op = QPropertyAnimation(out_eff, b"opacity")
            a_op.setDuration(250)
            a_op.setStartValue(1.0)
            a_op.setEndValue(0.0)
            a_sc = QVariantAnimation()
            a_sc.setDuration(250)
            a_sc.setStartValue(1.0)
            a_sc.setEndValue(0.85)
            a_sc.valueChanged.connect(lambda v, k=cur: host.place(k, float(v)))
            for anim in (a_op, a_sc):
                anim.setEasingCurve(QEasingCurve.OutCubic)
                g_out.addAnimation(anim)

            # ---- 渐入：opacity 0→1 + 容器 geometry 1.15→1.00（250ms） ----
            g_in = QParallelAnimationGroup(self)
            b_op = QPropertyAnimation(in_eff, b"opacity")
            b_op.setDuration(250)
            b_op.setStartValue(0.0)
            b_op.setEndValue(1.0)
            b_sc = QVariantAnimation()
            b_sc.setDuration(250)
            b_sc.setStartValue(1.15)
            b_sc.setEndValue(1.0)
            b_sc.valueChanged.connect(lambda v, k=nxt: host.place(k, float(v)))
            for anim in (b_op, b_sc):
                anim.setEasingCurve(QEasingCurve.OutCubic)
                g_in.addAnimation(anim)

            seq = QSequentialAnimationGroup(self)
            seq.addAnimation(g_out)
            seq.addAnimation(g_in)

            def _done():
                try:
                    self._view_mode = nxt
                    out_view.hide()          # 已淡出到 0，收起它（保持"静止时只有当前视图可见"）
                    in_eff.setOpacity(1.0)
                    host.place(nxt, 1.0)
                    host.place(cur, 1.0)        # 归位，供下次切换
                except Exception:
                    pass
                finally:
                    self._switching = False

            seq.finished.connect(_done)
            self._switch_seq = seq
            seq.start()
        except Exception:
            # 极端情况下退化为直接切换（绝不让界面卡住）
            self._switching = False
            try:
                out_view.hide()
                in_view.show()
                host.place(nxt, 1.0)
                self._view_mode = nxt
            except Exception:
                pass

    def _build_actions(self) -> QHBoxLayout:
        """底部操作区：主按钮「翻开回忆录」+ 副按钮「添加游戏」「AI 识图」，水平居中。"""
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addStretch(1)

        self.primary_btn = QPushButton("翻开回忆录")
        self.primary_btn.setObjectName("welcomePrimary")
        self.primary_btn.setCursor(Qt.PointingHandCursor)
        self.primary_btn.clicked.connect(self._on_primary_clicked)

        self.add_btn = QPushButton("添加游戏")
        self.add_btn.setObjectName("welcomeSecondary")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self.add_game_clicked.emit)

        self.identify_btn = QPushButton("AI 识图")
        self.identify_btn.setObjectName("welcomeSecondary")
        self.identify_btn.setCursor(Qt.PointingHandCursor)
        self.identify_btn.clicked.connect(self.identify_clicked.emit)

        for btn in (self.primary_btn, self.add_btn, self.identify_btn):
            row.addWidget(btn)
        row.addStretch(1)

        # 离场时"立即禁用整页所有按钮"，这里留好清单（第二轮防抖使用）
        self._buttons = [self.primary_btn, self.add_btn, self.identify_btn]
        return row

    # ------------------------------------------------------------------
    # 数据填充（只读；本轮为静态，不带动画）
    # ------------------------------------------------------------------
    def reload(self):
        """重新读取展示数据：最近 3 款 + 三项统计 + 一句台词。"""
        self._load_recent()
        self._load_stats()
        self._refresh_quote()
        # 空状态框等控件可能是本次新建的，兜底调色板要跟着补一遍
        if getattr(self, "_tokens", None):
            self._apply_palette_fallback()

    def _load_recent(self):
        try:
            games = self.db.get_games_page(0, 3) or []      # ORDER BY id DESC = 最近添加
        except Exception:
            games = []
        games = [g for g in games if isinstance(g, dict)][:3]

        for idx, box in enumerate(self._recent_boxes):
            if idx < len(games):
                box.set_card(WelcomeGameCard(games[idx]))
            elif not games and idx == 1:
                box.set_card(EmptyStateBox())               # 空状态放中间槽位 → 视觉居中
            else:
                box.set_card(None)                          # 保持 3 个槽位结构稳定

    def _load_stats(self):
        """读取真实统计数据：总数量 / 已通关 / 平均评分 + 三段状态构成。

        状态映射（用户最终裁定；全部来自现有 STATUS_OPTIONS 的 5 个状态，不猜测、不改数据）：
            已通关 = 通关
            已搁置 = 搁置 + 放弃
            未通关 = 想玩 + 正在玩
        守恒：已通关 + 已搁置 + 未通关 = 总数量（当前库 27 + 2 + 53 = 82）。
        """
        total = cleared = paused = todo = 0
        try:
            total = int(self.db.count_games() or 0)
            cleared = int(self.db.count_games("通关") or 0)
            paused = int(self.db.count_games("搁置") or 0) + int(self.db.count_games("放弃") or 0)
            todo = int(self.db.count_games("想玩") or 0) + int(self.db.count_games("正在玩") or 0)
        except Exception:
            total = cleared = paused = todo = 0

        self.stat_total.set_target(total, "等待添加")
        self.stat_cleared.set_target(cleared, "暂无通关")
        self.stat_avg.set_target(_avg_rating(self.db), "暂无评分", fmt="%.1f")

        # 三段数据：进度条视图与饼图视图**共享同一份数字**（只在这里读一次）
        # ⚠️ 若将来库里出现 STATUS_OPTIONS 之外的未知状态（当前为 0 条），三段之和会小于
        #    total —— 此时也绝不把差额塞进“未通关”（数据层红线），两种视图都按三段自身
        #    总和绘制，总数量卡/饼图中心仍显示真实总数。
        values = (cleared, paused, todo)
        names = getattr(self, "_legend_names", ())

        bar = getattr(self, "status_bar", None)
        if bar is not None:
            bar.set_values(*values)
        donut = getattr(self, "status_donut", None)
        if donut is not None:
            donut.set_values(cleared, paused, todo, total)
            donut.set_center(str(total) if total > 0 else "0",
                             "总收藏" if total > 0 else "等待添加")

        # 两个视图各自的图例（同一份数字）
        for group in (getattr(self, "_legend_labels", []),
                      getattr(self, "_donut_legend_labels", [])):
            for lbl, name, val in zip(group, names, values):
                try:
                    lbl.setText("%s %d" % (name, val))
                except Exception:
                    pass

        self.recent_note.setText("馆内共 %d 款作品" % total if total > 0 else "还没有作品")

    def _refresh_quote(self):
        lines = load_quotes()
        if lines:
            try:
                line = random.choice(lines)
            except Exception:
                line = lines[0]
        else:
            line = "愿每一段故事，都被好好记住。"
        self.quote_lbl.set_full_text(line)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def _apply_welcome_theme(self, *_args):
        """主题变化：重建 QSS + 主标题渐变，并同步玻璃面板透明度 / 重绘自绘卡片。"""
        tokens = _text_tokens()
        self._tokens = tokens
        try:
            self.setStyleSheet(_welcome_qss(tokens))
        except Exception:
            pass
        self._apply_palette_fallback(tokens)
        try:
            alpha = glass_alpha("panel")
            for surface in self.findChildren(GlassSurface):
                # 液态玻璃卡片的底色由 _apply_liquid_style() 单独设置（B 0.38 / C 渐变），
                # 不能被这里统一重置回 glass_alpha("panel")
                if isinstance(surface, _LiquidGlassCard):
                    continue
                surface.set_glass(alpha=alpha)
        except Exception:
            pass
        # 液态玻璃（按主题背景明度自适应 B 通透型 / C 高光型）
        self._apply_liquid_style()
        title = getattr(self, "banner_title", None)
        if title is not None:
            title.set_colors(tokens.get("title_g1"), tokens.get("title_g2"))
        # 统计数值渐变（stat_g1 → stat_g2）：卡片数值与饼图中心数字共用同一对颜色
        self._stat_grad = (tokens.get("stat_g1"), tokens.get("stat_g2"))
        for lbl in (getattr(self, "stat_total", None),
                    getattr(self, "stat_cleared", None),
                    getattr(self, "stat_avg", None)):
            if lbl is not None and hasattr(lbl, "set_colors"):
                try:
                    lbl.set_colors(tokens.get("stat_g1"), tokens.get("stat_g2"))
                except Exception:
                    pass
        # 状态构成：进度条 + 饼图 + 两套图例圆点 一起重算颜色（同一批 QColor）
        self._apply_status_colors()
        for card in self.findChildren(WelcomeGameCard):
            card.update()

    # ------------------------------------------------------------------
    # 液态玻璃统计卡：按主题背景明度自适应 B 通透型 / C 高光型
    # ------------------------------------------------------------------
    def _liquid_style(self) -> dict:
        """返回当前主题该用的液态玻璃参数（全部由主题 token + Alpha 派生，无 hex）。

        判据：pcolor("bg").lightness() > 128 → 亮背景用 B 通透型，否则用 C 高光型。
        ⚠️ Qt 无 CSS backdrop-filter / box-shadow / inset：模糊强度沿用现有
           ThemeManager 的毛玻璃（blur(20/24)、saturate 无法在不改主题系统的前提下调整），
           边框与内高光由 _LiquidGlassCard.paintEvent 自绘，外投影由 _StatsShadowHost 自绘。
        """
        light_bg = False
        try:
            light_bg = pcolor("bg").lightness() > 128
        except Exception:
            light_bg = not is_dark()
        shadow = pcolor("shadow")            # 主题阴影 token（设计上就是黑）
        if light_bg:
            # ---- B 通透型 ----
            #        B/C 的顶部高光现在用同一套渐变停靠点（TOP_HL_STOPS），
            #        这里只提供"颜色"（alpha 交给渐变），避免死白。
            white = pcolor("card")           # 亮主题下 card≈白，用它当"白高光"
            return {
                "mode": "B",
                "tint_alpha": 0.38,          # 底：rgba(card, 0.38)
                "use_gradient": False,
                "border": _with_alpha(white, 0.35),
                "hl_top": _with_alpha(white, 1.0),
                "hl_bottom": None,
                "hl_side": None,
                "shadow": {
                    "color": _with_alpha(shadow, 1.0),
                    "layers": [(7, 0.030), (5, 0.040), (3, 0.050)],   # ≈ 0 8px 24px rgba(0,0,0,.12)
                    "dy": 8,
                    "glow": None,
                },
            }
        # ---- C 高光型 ----
        card = pcolor("card")
        border = pcolor("border", "border_a")
        try:
            border = _with_alpha(border, min(1.0, border.alphaF() * 1.2))   # 1.2 × alpha
        except Exception:
            pass
        return {
            "mode": "C",
            "tint_alpha": 0.0,               # 关闭 GlassSurface 纯色底，改自绘渐变
            "use_gradient": True,
            "grad_a": _with_alpha(card, 0.50),
            "grad_b": _with_alpha(card, 0.35),
            "border": border,
            "hl_top": _with_alpha(pcolor("text"), 1.0),         # 暗背景下 text 近白（alpha 由渐变给）
            "hl_bottom": _with_alpha(QColor(accent_color()), 0.08),
            "hl_side": _with_alpha(pcolor("text"), 0.06),
            "shadow": {
                "color": _with_alpha(shadow, 1.0),
                "layers": [(8, 0.090), (6, 0.110), (4, 0.150)],   # ≈ 0 8px 28px rgba(0,0,0,.35)
                "dy": 8,
                "glow": _with_alpha(QColor(accent_color()), 0.05),
            },
        }

    def _apply_liquid_style(self):
        """把当前主题的液态玻璃参数下发给 4 张统计卡与投影宿主。"""
        try:
            style = self._liquid_style()
        except Exception:
            return
        self._liquid_mode = style.get("mode")
        for card in self.findChildren(_LiquidGlassCard):
            try:
                card.set_liquid(style)
            except Exception:
                pass
        host = getattr(self, "_stat_shadow_host", None)
        if host is not None:
            try:
                host.set_shadow_style(style.get("shadow"))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 状态构成配色（全部由主题动态派生，绝不硬编码颜色）
    # ------------------------------------------------------------------
    def _status_colors(self):
        """返回三段状态色 (已通关, 已搁置, 未通关)，进度条与饼图**共用同一批 QColor**。

        * 已通关：stat_g1（= 主题主渐变起点 pal()["gradient_start"] 经对比度收敛，
                  与统计卡数值同色；token 未就绪时回退 gradient_start / accent_color()）；
        * 已搁置：theme._mix(pcolor("text"), pcolor("bg"), 0.60)
                  —— 取用户允许区间 0.6~0.7 中对比度更高的一档，深浅模式都清晰；
        * 未通关：theme._mix(pcolor("bg"), pcolor("text"), 0.15)
                  —— 浅色模式得浅灰、深色模式得深灰的中性色。
        """
        p = pal()
        grad = getattr(self, "_stat_grad", None)
        done = QColor(grad[0]) if grad and grad[0] else QColor()
        if not done.isValid():
            done = QColor(p.get("gradient_start") or accent_color())
        if not done.isValid():
            done = QColor(accent_color())
        paused = _mix_colors(pcolor("text"), pcolor("bg"), 0.60)
        todo = _mix_colors(pcolor("bg"), pcolor("text"), 0.15)
        return done, paused, todo

    def _apply_status_colors(self):
        """把同一批三段颜色同步到进度条、饼图和两套图例圆点（主题切换时调用）。"""
        try:
            colors = self._status_colors()
        except Exception:
            return
        bar = getattr(self, "status_bar", None)
        if bar is not None:
            try:
                bar.set_colors(*colors)
            except Exception:
                pass
        donut = getattr(self, "status_donut", None)
        if donut is not None:
            try:
                donut.set_colors(*colors)                       # 与进度条同一批颜色
                grad = getattr(self, "_stat_grad", None)
                if grad:
                    donut.set_text_colors(grad[0], grad[1])     # 中心数字渐变
            except Exception:
                pass
        for group in (getattr(self, "_legend_dots", []),
                      getattr(self, "_donut_legend_dots", [])):
            for dot, col in zip(group, colors):
                try:
                    dot.set_color(col)
                except Exception:
                    pass

    def _apply_palette_fallback(self, tokens: dict = None):
        """样式表失效兜底：把同一套颜色显式写进 QPalette。

        如果页面样式表被环境拒绝 / 被部分忽略，QLabel 会回落到 QPalette；
        而系统处于深色模式时 QPalette 的 WindowText 就是白色 —— 那就会出现
        "浅色主题 + 白字"这种最难查的故障。这里给关键标签兜一层：
        样式表生效时 QSS 的 color 优先级更高、视觉完全一致；样式表失效时由它保底。
        """
        tokens = tokens or getattr(self, "_tokens", None) or _text_tokens()
        try:
            for obj_name, key in _PALETTE_FALLBACK:
                color = _qc(tokens.get(key), "#000000")
                for lbl in self.findChildren(QLabel, obj_name):
                    pal_ = lbl.palette()
                    pal_.setColor(QPalette.WindowText, color)
                    pal_.setColor(QPalette.Text, color)
                    pal_.setColor(QPalette.ButtonText, color)
                    lbl.setPalette(pal_)
                    lbl.setForegroundRole(QPalette.WindowText)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 交互：离场（防抖 + 快照向内收缩淡出）
    # ------------------------------------------------------------------
    def _on_primary_clicked(self):
        """「翻开回忆录」：抓图 → 禁用整页 → 隐藏 → 快照 0.5s 向内收缩(0.95) + 淡出。

        ⚠️ 切页只挂在离场动画的 finished 上（对外发 leave_finished），
           绝不用固定时长的 QTimer 强行切页。
        """
        if self._leaving:
            return
        self._leaving = True

        # ⓪ 若在"渐入 / 台词淡入"还没结束时就被点击：先把这两段动画落定。
        #    原因：QWidget.grab()/render() 会忽略 QGraphicsEffect（Qt 文档行为），
        #    半透明的页面会被拍成完全不透明、还没淡入的台词会被拍成满不透明，
        #    快照一出现就会"跳"一下。落定后快照 = 完全进场的样子，视觉连续。
        try:
            if self._enter_group is not None:
                self._enter_group.stop()
            self._entering = False
            self._enter_effect.setOpacity(1.0)
            self._stage.setGeometry(0, 0, self.width(), self.height())
        except Exception:
            pass
        try:
            self._quote_timer.stop()
            anim = getattr(self, "_quote_anim", None)
            if anim is not None:
                anim.stop()             # 正在淡入的动画也要停，否则它会继续覆盖透明度
            self._quote_effect.setOpacity(1.0)
        except Exception:
            pass

        # ① 先抓快照：此刻按钮还是正常态，快照里不会出现"禁用后的灰按钮"
        try:
            snap_pix = self.grab()
        except Exception:
            snap_pix = QPixmap()

        # ② 立即禁用整页所有按钮（防抖；用户看不到灰态，因为马上换成快照）
        self.setEnabled(False)
        for btn in getattr(self, "_buttons", []):
            try:
                btn.setEnabled(False)
            except Exception:
                pass

        # 快照要贴在整个窗口上，先算好它在窗口坐标里的位置（hide() 前算最稳）
        host = self.window() or self
        rect = QRect(self.mapTo(host, QPoint(0, 0)), self.size())

        # ③ 隐藏真页面
        self.hide()

        if snap_pix.isNull() or host is None:
            self.leave_finished.emit()      # 抓图失败也别卡住流程
            return

        # ④ 在窗口上贴快照：向中心收缩到 0.95 倍 + 淡出（"像被吸入"）
        snap = QLabel(host)
        snap.setObjectName("welcomeSnapshot")
        snap.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        snap.setAttribute(Qt.WA_StyledBackground, False)
        snap.setScaledContents(True)        # 让位图跟着 geometry 一起缩放
        snap.setAlignment(Qt.AlignCenter)
        snap.setPixmap(snap_pix)
        snap.setGeometry(rect)
        eff = QGraphicsOpacityEffect(snap)
        eff.setOpacity(1.0)
        snap.setGraphicsEffect(eff)
        snap.show()
        snap.raise_()
        self._snap = snap

        w = max(1, int(round(rect.width() * self.LEAVE_SCALE)))
        h = max(1, int(round(rect.height() * self.LEAVE_SCALE)))
        shrink = QRect(rect.center().x() - w // 2, rect.center().y() - h // 2, w, h)

        group = QParallelAnimationGroup(self)
        geo = QPropertyAnimation(snap, b"geometry", group)
        geo.setDuration(self.LEAVE_MS)
        geo.setStartValue(QRect(rect))
        geo.setEndValue(shrink)
        fade = QPropertyAnimation(eff, b"opacity", group)
        fade.setDuration(self.LEAVE_MS)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        for anim in (geo, fade):
            anim.setEasingCurve(QEasingCurve.OutCubic)

        def _done():
            try:
                snap.hide()
                snap.deleteLater()          # 效果器随快照一起销毁
            except Exception:
                pass
            self._snap = None
            group.deleteLater()
            self.leave_finished.emit()

        group.finished.connect(_done)
        self._leave_group = group
        group.start()

    # ------------------------------------------------------------------
    # 几何
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_stage()

    def _layout_stage(self):
        """让 _stage 铺满整页。

        渐入动画正在驱动 _stage.pos 时只改尺寸、不覆盖 pos，
        否则任何一次 resizeEvent 都会把位移动画打断（表现为"卡片闪一下"）。
        """
        if self._stage is None:
            return
        if self._entering:
            self._stage.resize(self.width(), self.height())
        else:
            self._stage.setGeometry(0, 0, self.width(), self.height())


# ============================================================
# 单页预览（只用于开发时肉眼检查，不参与正式启动流程）
#     python src/welcome.py
# ============================================================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    from config import DB_PATH, ensure_directories
    from database import Database
    from theme import _apply_theme

    ensure_directories()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _apply_theme()
    demo_db = Database(DB_PATH)
    page = WelcomePage(demo_db)
    page.resize(1360, 820)
    page.show()
    sys.exit(app.exec())
