# -*- coding: utf-8 -*-
"""多主题管理器：主题/颜色模式/自定义背景解耦，背景图预处理缓存。

只负责“看起来怎样”的数据与缓存，不碰数据库、网络、业务逻辑。
"""

import os
import time

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

import config
import theme_defs

try:
    from PIL import Image, ImageEnhance, ImageOps
except Exception:  # Pillow 缺失时退回 QImageReader，不让主题系统崩溃
    Image = ImageEnhance = ImageOps = None


# 背景处理常量：整体亮度先压低 15%，再按深浅模式叠加遮罩。
_BRIGHTNESS_ALPHA = 38          # 255 * 0.15 ≈ 38
_LIGHT_OVERLAY_ALPHA = 178      # 70% 白色遮罩
_DARK_OVERLAY_ALPHA = 204       # 80% 深蓝黑遮罩

# 遮罩前轻微增强原图，避免“压暗 + 70/80 遮罩”后主题背景完全看不见。
_BG_SATURATION = 1.15
_BG_CONTRAST = 1.08


def _qcolor(hex_color: str, fallback: str = "#000000") -> QColor:
    c = QColor(str(hex_color or ""))
    return c if c.isValid() else QColor(fallback)


def _mix_hex(c1: str, c2: str, t: float) -> str:
    """按比例混合两个颜色，返回 #RRGGBB。"""
    try:
        a, b = _qcolor(c1), _qcolor(c2)
        t = max(0.0, min(1.0, float(t)))
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        ).name()
    except Exception:
        return str(c1 or c2 or "#000000")


def _rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB -> rgba(r,g,b,a)，用于 QSS 透明度。"""
    c = _qcolor(hex_color)
    a = max(0.0, min(1.0, float(alpha)))
    return "rgba(%d,%d,%d,%s)" % (c.red(), c.green(), c.blue(),
                                  ("%.3f" % a).rstrip("0").rstrip("."))


def _luminance(c: QColor) -> float:
    def _lin(v):
        v = max(0.0, min(1.0, v / 255.0))
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(c.red()) + 0.7152 * _lin(c.green()) + 0.0722 * _lin(c.blue())


def readable_text(hex_color: str) -> str:
    """给彩色底选高对比文字色：比较白/深色实际对比度，选更高者。"""
    c = _qcolor(hex_color)
    lum = _luminance(c)
    white_contrast = 1.05 / (lum + 0.05)
    dark_lum = _luminance(QColor("#16121F"))
    dark_contrast = (lum + 0.05) / (dark_lum + 0.05)
    return "#16121F" if dark_contrast >= white_contrast else "#FFFFFF"


def readable_gradient_text(c1: str, c2: str) -> str:
    """主渐变按钮上的文字色：取渐变中点的对比度。"""
    return readable_text(_mix_hex(c1, c2, 0.5))


def build_palette(theme_id: str, mode: str) -> dict:
    """把 9 套静态主题数据展开成完整 QSS 语义色。

    表格里只提供 bg/card/text/accent/gradient；其余全部由这里派生，
    UI 与 QSS 模板只认语义 token，不硬编码颜色。
    """
    item = theme_defs.THEME_DEFS.get(str(theme_id or "")) or theme_defs.THEME_DEFS[theme_defs.DEFAULT_THEME_ID]
    mode = "dark" if str(mode) == "dark" else "light"
    d = item[mode]
    g1, g2 = item["gradient"]

    p = dict(d)
    p["gradient_start"] = g1
    p["gradient_end"] = g2
    p["on_accent"] = readable_text(d["accent"])
    p["on_grad"] = readable_gradient_text(g1, g2)

    p["sidebar"] = _mix_hex(d["bg"], d["card"], 0.40)
    p["card_hover"] = _mix_hex(d["card"], d["accent"], 0.10)
    p["cover_bg"] = _mix_hex(d["bg"], d["card"], 0.35)
    p["input"] = _mix_hex(d["card"], d["bg"], 0.18)
    p["menu"] = d["card"]
    p["row"] = d["card"]
    p["header"] = _mix_hex(d["bg"], d["card"], 0.55)
    p["btn"] = d["card"]
    p["btn_hover"] = _mix_hex(d["card"], d["accent"], 0.12)
    p["btn_press"] = _mix_hex(d["card"], d["bg"], 0.18)
    p["btn_disabled"] = _mix_hex(d["card"], d["bg"], 0.10)

    p["muted"] = _mix_hex(d["text"], d["bg"], 0.34)
    p["muted2"] = _mix_hex(d["text"], d["bg"], 0.18)
    p["accent2"] = g2
    p["pink"] = g1
    p["blue"] = g2
    p["danger"] = theme_defs.DANGER_COLOR
    p["track"] = _mix_hex(d["card"], d["text"], 0.22)

    if mode == "dark":
        p["border_a"], p["border_soft_a"] = 0.10, 0.05
        p["glass_a"], p["chip_a"] = 0.06, 0.07
        p["scrollbar_a"], p["scrollbar_hover_a"] = 0.22, 0.34
        p["disabled_a"], p["shadow_a"] = 0.34, 0.45
        p["panel_a"], p["sidebar_a"], p["bubble_a"] = 0.52, 0.58, 0.84
    else:
        p["border_a"], p["border_soft_a"] = 0.12, 0.06
        p["glass_a"], p["chip_a"] = 0.04, 0.05
        p["scrollbar_a"], p["scrollbar_hover_a"] = 0.18, 0.30
        p["disabled_a"], p["shadow_a"] = 0.30, 0.18
        p["panel_a"], p["sidebar_a"], p["bubble_a"] = 0.62, 0.68, 0.88

    p["border"] = d["text"]
    p["border_soft"] = d["text"]
    p["glass"] = d["text"]
    p["chip"] = d["text"]
    p["grid_line"] = d["text"]
    p["grid_line_a"] = 0.06
    p["scrollbar"] = d["text"]
    p["scrollbar_hover"] = d["text"]
    p["disabled"] = d["text"]
    p["shadow"] = "#000000"
    return p


def _find_theme_asset(theme_name: str, mode_cn: str) -> str:
    """按规范名查找主题背景图：{主题名}_浅色.jpg / {主题名}_深色.jpg。

    统一保留 JPG 一份素材；若未来放回 png/webp，也按同名优先查找。
    """
    base = os.path.join(config.ASSETS_DIR, "themes")
    stem = "%s_%s" % (theme_name, mode_cn)
    candidates = [
        stem + ".jpg",
        stem + ".jpeg",
        stem + ".png",
        stem + ".webp",
    ]
    for name in candidates:
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    return ""


def _blur_pixmap(pm: QPixmap, level: int = 14) -> QPixmap:
    """毛玻璃用快速模糊：降采样后插值放大。"""
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


class ThemeManager(QObject):
    """主题状态与背景缓存的唯一入口。"""

    themeChanged = Signal(str, str)          # theme_id, resolved_mode
    backgroundChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_theme = config.get_theme_id()
        self.color_mode = config.get_color_mode()
        self.custom_background_path = config.get_custom_background_path()
        self._resolved_mode = self._resolve_mode()
        self._palette = build_palette(self.current_theme, self._resolved_mode)
        self._bg_cache = None
        self._bg_key = None
        self._system_listener_started = False
        self._custom_bg_missing = False

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def palette(self) -> dict:
        return self._palette

    @property
    def resolved_mode(self) -> str:
        return self._resolved_mode

    @property
    def is_dark(self) -> bool:
        return self._resolved_mode == "dark"

    def theme_name(self) -> str:
        return theme_defs.theme_name(self.current_theme)

    def _resolve_mode(self) -> str:
        mode = str(self.color_mode or "light")
        if mode in ("light", "dark"):
            return mode
        return config.get_effective_mode()

    # ------------------------------------------------------------------
    # 主题 / 颜色模式 / 强调色
    # ------------------------------------------------------------------
    def set_theme(self, theme_id: str, color_mode: str = None):
        theme_id = str(theme_id or "")
        if theme_id not in theme_defs.THEME_DEFS:
            theme_id = theme_defs.DEFAULT_THEME_ID
        self.current_theme = theme_id
        config.set_theme_id(theme_id)

        if color_mode is not None:
            mode = str(color_mode or "")
            if mode in ("light", "dark", "system"):
                self.color_mode = mode
                config.set_color_mode(mode)

        self._resolved_mode = self._resolve_mode()
        self._palette = build_palette(self.current_theme, self._resolved_mode)
        self.clear_background_cache()
        self.themeChanged.emit(self.current_theme, self._resolved_mode)
        self.backgroundChanged.emit()

    def set_color_mode(self, mode: str):
        mode = str(mode or "")
        if mode not in ("light", "dark", "system"):
            mode = theme_defs.DEFAULT_COLOR_MODE
        self.color_mode = mode
        config.set_color_mode(mode)
        self._resolved_mode = self._resolve_mode()
        self._palette = build_palette(self.current_theme, self._resolved_mode)
        self.clear_background_cache()
        self.themeChanged.emit(self.current_theme, self._resolved_mode)
        self.backgroundChanged.emit()

    def refresh_accent(self):
        """强调色覆盖变化：只换配色，不换背景。"""
        self._palette = build_palette(self.current_theme, self._resolved_mode)
        self.themeChanged.emit(self.current_theme, self._resolved_mode)

    # ------------------------------------------------------------------
    # 自定义背景
    # ------------------------------------------------------------------
    def _resolve_background_source(self):
        """返回 (source_path, is_custom, missing)。

        自定义路径存在但文件丢失时，missing=True，但 source_path 已回退到主题自带图；
        这样 build_backdrop 不会退化成纯色，视觉上优雅降级。
        """
        missing = False
        if self.custom_background_path:
            p = config.to_abs(self.custom_background_path)
            if os.path.isfile(p):
                return p, True, False
            missing = True
        name = theme_defs.theme_name(self.current_theme)
        mode_cn = "浅色" if self._resolved_mode == "light" else "深色"
        return _find_theme_asset(name, mode_cn), False, missing

    def background_path(self) -> str:
        src, _is_custom, missing = self._resolve_background_source()
        self._custom_bg_missing = bool(missing)
        return src

    def background_state_text(self) -> str:
        """设置页显示用：主题背景 / 自定义背景。"""
        if self.custom_background_path:
            if self._custom_bg_missing:
                return "自定义背景（文件丢失，已回退主题背景）"
            return "自定义背景"
        return "主题背景"

    def set_custom_background(self, src_path: str):
        """只改背景图，绝不改变 current_theme / color_mode / palette。"""
        if src_path:
            rel = config.save_custom_background(src_path)
            if not rel:
                return False
            self.custom_background_path = rel
        else:
            self.custom_background_path = ""
        config.set_custom_background_path(self.custom_background_path)
        self._custom_bg_missing = False
        self.clear_background_cache()
        self.backgroundChanged.emit()
        return True

    def set_custom_background_rel(self, rel_path: str):
        """直接使用已在项目内的相对路径作为背景（用于 data/wallpapers 预设）。"""
        self.custom_background_path = str(rel_path or "").strip()
        config.set_custom_background_path(self.custom_background_path)
        self._custom_bg_missing = False
        self.clear_background_cache()
        self.backgroundChanged.emit()
        return True

    def restore_theme_background(self):
        """清自定义背景，回到主题自带背景；主题与配色保持不变。"""
        self.custom_background_path = ""
        config.set_custom_background_path("")
        self._custom_bg_missing = False
        self.clear_background_cache()
        self.backgroundChanged.emit()

    # ------------------------------------------------------------------
    # 背景预处理与缓存
    # ------------------------------------------------------------------
    def clear_background_cache(self):
        """切换主题/模式/背景时必须清掉旧缓存，避免内存持续增长。"""
        self._bg_cache = None
        self._bg_key = None

    def _fallback_image(self, w: int, h: int) -> QImage:
        """无图兜底：用主题背景色纯色填充，不实时算像素。"""
        img = QImage(max(1, int(w)), max(1, int(h)), QImage.Format_ARGB32)
        img.fill(_qcolor(self._palette.get("bg", "#2B3140")))
        return img

    def _enhanced_cover_image(self, src_path: str, tw: int, th: int):
        """用 Pillow 做 cover 裁切 + 饱和度/对比度增强，返回 QImage；失败返回 None。

        只在这里预处理一次，paintEvent 永远只画缓存位图。
        """
        if Image is None or ImageEnhance is None or ImageOps is None:
            return None
        try:
            im = Image.open(src_path)
            im = ImageOps.exif_transpose(im).convert("RGB")
            sw, sh = im.size
            if sw <= 0 or sh <= 0:
                return None
            scale = max(tw / float(sw), th / float(sh))
            nw = max(1, int(round(sw * scale)))
            nh = max(1, int(round(sh * scale)))
            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
            im = im.resize((nw, nh), resample)
            left = max(0, (nw - tw) // 2)
            top = max(0, (nh - th) // 2)
            im = im.crop((left, top, left + tw, top + th))
            im = ImageEnhance.Color(im).enhance(_BG_SATURATION)
            im = ImageEnhance.Contrast(im).enhance(_BG_CONTRAST)
            raw = im.tobytes("raw", "RGB")
            return QImage(raw, im.width, im.height, im.width * 3,
                          QImage.Format_RGB888).copy()
        except Exception:
            return None

    def _render_backdrop(self, src_path: str, w: int, h: int, dpr: float, dark: bool):
        w, h = max(1, int(w)), max(1, int(h))
        dpr = max(1.0, min(3.0, float(dpr or 1.0)))
        pw, ph = int(round(w * dpr)), int(round(h * dpr))

        img = None
        pm = QPixmap()
        if src_path and os.path.isfile(src_path):
            # 优先 Pillow：cover 裁切后先轻微提饱和度/对比度，再压暗和叠加遮罩。
            img = self._enhanced_cover_image(src_path, pw, ph)
            if img is None:
                try:
                    pm = config._load_pix_cover(src_path, pw, ph)
                except Exception:
                    pm = QPixmap()

        should_overlay = True
        if img is None:
            if pm.isNull():
                img = self._fallback_image(pw, ph)
                should_overlay = False
            else:
                img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
                if img.width() != pw or img.height() != ph:
                    img = img.scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        if should_overlay:
            p = QPainter(img)
            # 1) 整体亮度压低 15%
            p.fillRect(img.rect(), QColor(0, 0, 0, _BRIGHTNESS_ALPHA))
            # 2) 浅色 70% 白色 / 深色 80% 深蓝黑
            if dark:
                r, g, b = theme_defs.DARK_OVERLAY
                p.fillRect(img.rect(), QColor(r, g, b, _DARK_OVERLAY_ALPHA))
            else:
                p.fillRect(img.rect(), QColor(255, 255, 255, _LIGHT_OVERLAY_ALPHA))
            p.end()

        sharp = QPixmap.fromImage(img)
        sharp.setDevicePixelRatio(dpr)
        blur = _blur_pixmap(sharp, 14)
        return sharp, blur

    def render_backdrop_for_source(self, src_path: str, w: int, h: int,
                                   dpr: float, dark: bool):
        """兼容旧 build_backdrop 签名：显式指定图源与深浅模式时使用。"""
        return self._render_backdrop(src_path, w, h, dpr, bool(dark))

    def build_backdrop(self, w: int, h: int, dpr: float = 1.0):
        """按“自定义 > 主题自带 > 纯色兜底”取图，并只生成一次缓存。"""
        src = self.background_path()
        try:
            mtime = int(os.stat(src).st_mtime) if src and os.path.isfile(src) else 0
        except Exception:
            mtime = 0
        key = (src, self._resolved_mode, int(w), int(h), round(float(dpr or 1.0), 3), mtime)
        if key == self._bg_key and self._bg_cache is not None:
            return self._bg_cache

        self.clear_background_cache()
        try:
            self._bg_cache = self._render_backdrop(src, w, h, dpr, self.is_dark)
        except Exception:
            self._bg_cache = self._render_backdrop("", w, h, dpr, self.is_dark)
        self._bg_key = key
        return self._bg_cache

    # ------------------------------------------------------------------
    # 跟随系统
    # ------------------------------------------------------------------
    def start_system_listener(self):
        """只监听一次；只在 color_mode == system 时响应。"""
        if not self._system_listener_started:
            self._system_listener_started = True
            app = QApplication.instance()
            if app is not None:
                try:
                    hints = app.styleHints()
                    if hasattr(hints, "colorSchemeChanged"):
                        hints.colorSchemeChanged.connect(
                            lambda _scheme: self._on_system_scheme_changed())
                    else:
                        import darkdetect
                        darkdetect.listener(
                            callback=lambda _is_dark: self._on_system_scheme_changed())
                except Exception:
                    pass
        # QApplication 创建后重新解析一次，避免 system 模式下初始值仍是 light。
        self.refresh_system_mode()

    def refresh_system_mode(self):
        """仅 system 模式：重新读取系统深浅色，变化时更新调色板与背景。"""
        if self.color_mode != "system":
            return
        new_mode = config.get_effective_mode()
        if new_mode != self._resolved_mode:
            self._resolved_mode = new_mode
            self._palette = build_palette(self.current_theme, self._resolved_mode)
            self.clear_background_cache()
            self.themeChanged.emit(self.current_theme, self._resolved_mode)
            self.backgroundChanged.emit()

    def _on_system_scheme_changed(self):
        self.refresh_system_mode()


theme_manager = ThemeManager()


def get_theme_manager() -> ThemeManager:
    return theme_manager
