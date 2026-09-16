# -*- coding: utf-8 -*-
"""随机 CG 预览窗（PySide6 原生版）。

独立模块，不修改主窗口；确认无误后再在 widgets.py 里加侧边栏按钮。
"""

import os
import sys
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import (
    Qt, QEvent, QObject, QPoint, QSize, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter,
    QPen, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

import config
from random_cg_api import CGResult, RandomCGFetcher
from theme import TopComboBox, app_icon_pixmap, pstr
from theme_manager import theme_manager

import cg_library


def _rgba(hex_color: str, alpha: float) -> str:
    """本地小工具：QSS rgba()。"""
    from PySide6.QtGui import QColor
    c = QColor(hex_color)
    if not c.isValid():
        c = QColor("#000000")
    a = max(0.0, min(1.0, float(alpha)))
    return "rgba(%d,%d,%d,%s)" % (c.red(), c.green(), c.blue(),
                                  ("%.3f" % a).rstrip("0").rstrip("."))


class _WorkerSignals(QObject):
    done = Signal(object)


class _WorkerThread(threading.Thread):
    """把网络请求放到后台线程，结果通过 Qt Signal 回主线程。"""

    def __init__(self, func, signals: _WorkerSignals, *args, **kwargs):
        super().__init__(daemon=True)
        self._func = func
        self._signals = signals
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            value = self._func(*self._args, **self._kwargs)
        except Exception as exc:  # 兜底，UI 统一当失败处理
            value = exc
        try:
            self._signals.done.emit(value)
        except RuntimeError:
            # 窗口已经销毁，信号目标不存在时忽略
            pass


class _ViewerComboBox(TopComboBox):
    """预览窗专用下拉框：固定朝下、限制弹窗高度、超出后内部滚动。"""

    def __init__(self, parent=None, popup_height: int = 300):
        super().__init__(parent)
        self._popup_height = int(popup_height)
        self.setMaxVisibleItems(10)
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view().setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def _apply_combo_theme(self):
        """基类主题之上，补一条弹窗内部滚动指示条的底色规则。

        当下拉项超过 maxVisibleItems 时，Qt 会在弹窗顶部/底部各放一个自绘的
        滚动指示条 QComboBoxPrivateScroller；基类只给外层容器和 QListView
        上了底色，这个内部控件仍用系统默认的浅色调色板绘制，于是列表上下
        各出现一条白条。这里只给本预览窗的弹窗补背景色，不改动全局样式。
        """
        super()._apply_combo_theme()
        try:
            pop = self.view().parentWidget()
            if pop is None:
                return
            menu = QColor(pstr("menu")).name()
            pop.setStyleSheet(
                "%sQComboBoxPrivateScroller { background: %s; border: none; }"
                % (pop.styleSheet(), menu))
        except Exception:
            pass

    def showPopup(self):
        super().showPopup()
        # 去掉 Windows 原生弹窗可能带的白边/阴影框
        try:
            pop = self.view().window()
            if pop is not None:
                pop.setWindowFlags(
                    pop.windowFlags()
                    | Qt.FramelessWindowHint
                    | Qt.NoDropShadowWindowHint
                )
                pop.show()
        except Exception:
            pass
        QTimer.singleShot(0, self._limit_popup)

    def _limit_popup(self):
        try:
            view = self.view()
            pop = view.window()
            if pop is None:
                return
            count = max(1, self.count())
            row_h = view.sizeHintForRow(0)
            if row_h <= 0:
                row_h = 28
            content_h = row_h * count + 12
            h = max(72, min(self._popup_height, content_h))
            w = max(self.width(), 160)
            pop.setFixedWidth(w)
            pop.setFixedHeight(h)
            # 强制列表铺满弹窗，避免上下留出容器底色（在系统样式下会表现为白边）
            pop.setContentsMargins(0, 0, 0, 0)
            lay = pop.layout()
            if lay is not None:
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(0)
            view.setFixedSize(max(40, w), max(40, h))
            view.move(0, 0)
            # 去掉 Windows 11 给弹窗绘制的原生 DWM 白边
            self._strip_windows_dwm_border(pop)
            # 固定贴回控件正下方，不跟随当前选项上下浮动
            pop.move(self.mapToGlobal(QPoint(0, self.height())))
        except Exception:
            pass

    @staticmethod
    def _strip_windows_dwm_border(pop):
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            hwnd = int(pop.winId())
            # DWMWA_BORDER_COLOR = 34, DWMWA_COLOR_NONE = 0xFFFFFFFE
            val = ctypes.c_uint(0xFFFFFFFE)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass


# 右侧历史栏尺寸：手册要求约 120～140px，这里固定 140px
# 缩略图宽度按实测可用宽度取值：140 - 面板边框 2 - 面板内边距 16 - 滚动条 10
#   - 条目内边距 10 - 条目边框 2 = 100，保证条目与缩略图都不横向溢出。
_HISTORY_PANEL_WIDTH = 140
_HISTORY_THUMB_W = 100
_HISTORY_THUMB_H = 70
_HISTORY_MAX = 20

# 展开 / 收起历史栏时的窗口最小尺寸
_MIN_SIZE_WITH_HISTORY = (948, 560)
_MIN_SIZE_NO_HISTORY = (760, 560)

# 已列进图源下拉、但尚未接入的图源：可 hover / 可键盘导航 / 可选中，
# 选中后只给明确提示，不取图、不发请求、不偷偷回退其它图源。
# （B3 起 UapiPro、B5 起 LoliAPI 都已接入，当前为空；机制保留备用）
_PENDING_LABELS = {}

# 图源显示名（状态栏 / 历史栏里的「图源」，与顶栏下拉同一套名字）
_SOURCE_LABELS = {
    "illlights": "illlights",
    "dmoe": "dmoe",
    "uapipro": "UapiPro",
    "loliapi": "LoliAPI",
    "local": "本地图库",
}

# 各图源模式下「预期」命中的图源：不一致即代表这次是降级取到的
_EXPECTED_SOURCE = {
    "auto": "illlights",
    "first": "illlights",
    "second": "dmoe",
    "local": "local",
}


def _is_degraded(source_mode: str, source: str) -> bool:
    """这次取图是否走了降级（取到图的那一刻判定一次并记进历史，避免回看时重拼）。"""
    expected = _EXPECTED_SOURCE.get(str(source_mode or ""), "")
    return bool(source) and bool(expected) and expected != source


def _make_thumb(display_bytes: bytes):
    """由预览字节生成历史栏缩略图；失败返回 None。"""
    if not display_bytes:
        return None
    pm = QPixmap()
    try:
        if not pm.loadFromData(display_bytes):
            return None
        return pm.scaled(_HISTORY_THUMB_W, _HISTORY_THUMB_H,
                         Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        return None


@dataclass(eq=False)
class _HistoryItem:
    """历史栏里的一条记录（只存内存；不保存 raw_bytes / download_bytes）。"""

    thumb: object = None
    display_bytes: bytes = b""
    source: str = ""
    source_label: str = ""
    category: str = ""
    width: int = 0
    height: int = 0
    fmt: str = ""
    local_path: str = ""
    url: str = ""
    degraded: bool = False

    def title_text(self) -> str:
        """历史栏里的「来源 / 作品名」。"""
        return "%s\n%s" % (self.source_label or self.source or "未知图源",
                           self.category or "暂无")

    def status_text(self) -> str:
        """状态栏：分辨率 · 格式 · 图源（有分类 / 降级再追加）。"""
        text = "%d × %d · %s · %s" % (
            self.width, self.height, self.fmt or "未知",
            self.source_label or self.source or "未知图源")
        if self.category:
            text += " · %s" % self.category
        if self.degraded:
            text += " · 已降级"
        return text

    def tooltip(self) -> str:
        return self.local_path or self.url or self.status_text()


def _make_history_item(result: CGResult, source_mode: str,
                       category_label: str) -> _HistoryItem:
    """把一次取图结果转成历史项（丢掉 raw_bytes / download_bytes）。"""
    category = result.game_name or category_label or ""
    return _HistoryItem(
        thumb=_make_thumb(result.display_bytes),
        display_bytes=result.display_bytes,
        source=result.source,
        source_label=_SOURCE_LABELS.get(result.source,
                                        result.source or "未知图源"),
        category=str(category),
        width=result.width,
        height=result.height,
        fmt=result.fmt,
        local_path=result.local_path,
        url=result.url,
        degraded=_is_degraded(source_mode, result.source),
    )


class _HistoryItemWidget(QFrame):
    """历史栏单条记录：缩略图 + 来源/作品名，点击回看。"""

    def __init__(self, item: _HistoryItem, on_click, parent=None):
        super().__init__(parent)
        self.item = item
        self._on_click = on_click
        self.setObjectName("cgHistoryItem")
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("selected", False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(4)

        self.thumb_lbl = QLabel()
        self.thumb_lbl.setObjectName("cgHistoryThumb")
        self.thumb_lbl.setAlignment(Qt.AlignCenter)
        self.thumb_lbl.setFixedHeight(_HISTORY_THUMB_H)
        # 让点击穿透到整条记录
        self.thumb_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if item.thumb is not None and not item.thumb.isNull():
            self.thumb_lbl.setPixmap(item.thumb)
        else:
            self.thumb_lbl.setText("无缩略图")
        lay.addWidget(self.thumb_lbl)

        self.text_lbl = QLabel(item.title_text())
        self.text_lbl.setObjectName("cgHistoryText")
        self.text_lbl.setWordWrap(True)
        self.text_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.text_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.text_lbl)

        self.setToolTip(item.tooltip())

    def set_selected(self, on: bool):
        on = bool(on)
        if bool(self.property("selected")) == on:
            return
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click is not None:
            self._on_click(self.item)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class RandomCGViewer(QDialog):
    """随机 CG 预览窗口。"""

    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.setWindowTitle("随机 CG 预览")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        # 右侧历史栏固定 140px：展开时最小宽度要相应加大
        self.setMinimumSize(*_MIN_SIZE_WITH_HISTORY)
        self.resize(1000, 700)
        self.setFont(self._pick_font())

        self._alive = True
        self._request_id = 0
        self._db = db
        # 「本地图库」的分类要按游戏归类，需要 games / screenshots 两张表的信息
        self._library_index = self._build_library_index(db)
        # 第三级降级：本地 CG 根目录 + 旧版 data/screenshots
        local_roots = []
        try:
            local_roots.append(config.get_cg_root())
        except Exception:
            pass
        local_roots.append(os.path.join(config.DATA_DIR, "screenshots"))
        self._fetcher = RandomCGFetcher(
            local_roots=local_roots, library_index=self._library_index)
        self._filling_combos = False
        # 当前图源模式的分类下拉是否已经准备就绪
        self._categories_ready = False
        self._history = []              # list[_HistoryItem]，只存内存
        self._history_index = -1        # 当前显示的是第几条历史
        self._history_widgets = []
        self._pending = {}              # request_id -> (source_mode, 分类文案)
        self._current = None
        self._download_fresh = None     # 刚取回那张的原始下载字节（只留当前一张）
        self._pixmap_original = None
        self._pixmap_scaled = None
        self._drag_pos = None

        # 线程 / 信号引用池，防止被 GC
        self._threads = []
        self._signal_pool = []

        # 加载动画
        self._loading_dots = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(380)
        self._loading_timer.timeout.connect(self._tick_loading)

        # 缩放防抖
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._apply_current_pixmap)

        self._build_ui()
        self._apply_style()
        self._bind_shortcuts()

        try:
            theme_manager.themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass

        self._refresh_category_combo()
        self._rebuild_history_ui()
        self.fetch_new()
        if parent is not None:
            QTimer.singleShot(0, self._center_on_parent)

    @staticmethod
    def _build_library_index(db):
        """从数据库读取 games / screenshots，构造本地 CG 的游戏索引。

        读不到（没传 db / 还没建表）时返回空索引：本地图片会全部归入
        「未分类」，不会影响窗口正常打开。
        """
        if db is None:
            return cg_library.LibraryIndex()
        try:
            games = db.get_all_games()
            shots = db.get_all_screenshots()
        except Exception:
            return cg_library.LibraryIndex()
        try:
            return cg_library.build_index(
                games, shots,
                path_resolver=config.to_abs,
                reserved_names=config.CATEGORY_OPTIONS)
        except Exception:
            return cg_library.LibraryIndex()

    # ------------------------------------------------------------------
    # 基础 UI
    # ------------------------------------------------------------------
    def _pick_font(self) -> QFont:
        if sys.platform.startswith("win"):
            family = "Microsoft YaHei UI"
        elif sys.platform == "darwin":
            family = "PingFang SC"
        else:
            family = "DejaVu Sans"
        f = QFont(family)
        f.setPointSize(10)
        return f

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName("viewerCard")
        root.addWidget(self.card)

        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        # ---- 自定义标题栏 ----
        self.title_bar = QWidget()
        self.title_bar.setObjectName("viewerTitleBar")
        self.title_bar.setFixedHeight(42)
        tb = QHBoxLayout(self.title_bar)
        tb.setContentsMargins(14, 0, 10, 0)
        tb.setSpacing(8)

        # 左上角用 assets 里的应用图标，不再仿 macOS 三个圆点
        self.title_icon = QLabel()
        self.title_icon.setObjectName("viewerTitleIcon")
        self.title_icon.setFixedSize(24, 24)
        self.title_icon.setPixmap(app_icon_pixmap(24, radius=7))
        tb.addWidget(self.title_icon)
        tb.addSpacing(4)

        self.title_lbl = QLabel("随机 CG 预览")
        self.title_lbl.setObjectName("viewerTitle")
        tb.addWidget(self.title_lbl)
        tb.addStretch(1)

        # 右上角关闭：自绘一个小 X，避免依赖可能缺失的字体字形
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("viewerClose")
        self.close_btn.setText("")
        self.close_btn.setIconSize(QSize(14, 14))
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("关闭")
        self.close_btn.clicked.connect(self.close)
        tb.addWidget(self.close_btn)
        card_lay.addWidget(self.title_bar)

        # ---- 顶栏：[图源 ▼] [分类 ▼] [刷新图库信息] ----
        toolbar = QWidget()
        toolbar.setObjectName("viewerToolbar")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(16, 12, 16, 6)
        tl.setSpacing(8)

        tl.addWidget(QLabel("图源："))
        self.source_combo = _ViewerComboBox(popup_height=260)
        self.source_combo.setMinimumWidth(170)
        # (模式, 显示名, 提示)；UapiPro / LoliAPI 尚未接入：
        # 仍可 hover / 可键盘导航 / 可选中，选中后只给提示，不取图也不回退。
        for mode, label, tip in (
            ("auto", "自动",
             "先试 illlights，失败自动切 dmoe，最后才用本地图库"),
            ("local", "本地图库",
             "只用本地 CG，分类 = 作品名"),
            ("first", "illlights",
             "在线图库，支持按作品名 / 分辨率分类"),
            ("second", "dmoe",
             "在线图库，接口没有分类参数"),
            ("uapipro", "UapiPro",
             "在线图库，支持按分类选择（二次元 / 风景 / 壁纸 / 表情包 / AI绘画）"),
            ("loliapi", "LoliAPI",
             "在线图库，支持按分类选择（PC端 / 移动端）"),
        ):
            self.source_combo.addItem(label, mode)
            idx = self.source_combo.count() - 1
            self.source_combo.setItemData(idx, tip, Qt.ToolTipRole)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        tl.addWidget(self.source_combo)

        tl.addSpacing(6)
        tl.addWidget(QLabel("分类："))
        self.category_combo = _ViewerComboBox(popup_height=360)
        self.category_combo.setMinimumWidth(260)
        self.category_combo.setMaxVisibleItems(14)
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        tl.addWidget(self.category_combo)

        self.refresh_btn = QPushButton("↻ 刷新图库信息")
        self.refresh_btn.setObjectName("viewerBtn")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(lambda: self._refresh_source_info(force=True))
        tl.addWidget(self.refresh_btn)
        tl.addStretch(1)
        card_lay.addWidget(toolbar)

        # ---- 中间：左侧 CG 预览区 + 右侧历史栏 ----
        middle = QHBoxLayout()
        middle.setContentsMargins(16, 0, 16, 0)
        middle.setSpacing(10)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(0)

        self.image_area = QLabel("准备中…")
        self.image_area.setObjectName("cgImageArea")
        self.image_area.setAlignment(Qt.AlignCenter)
        self.image_area.setMinimumSize(680, 400)
        self.image_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_col.addWidget(self.image_area, 1)

        # 错误时的重试按钮
        self.retry_btn = QPushButton("🔄 重试")
        self.retry_btn.setObjectName("viewerBtn")
        self.retry_btn.setCursor(Qt.PointingHandCursor)
        self.retry_btn.clicked.connect(self.fetch_new)
        self.retry_btn.hide()
        retry_wrap = QHBoxLayout()
        retry_wrap.setContentsMargins(0, 4, 0, 4)
        retry_wrap.addStretch(1)
        retry_wrap.addWidget(self.retry_btn)
        retry_wrap.addStretch(1)
        left_col.addLayout(retry_wrap)
        middle.addLayout(left_col, 1)

        self._build_history_panel()
        middle.addWidget(self.history_panel)
        card_lay.addLayout(middle, 1)

        # ---- 底部按钮 ----
        btns = QHBoxLayout()
        btns.setContentsMargins(16, 8, 16, 4)
        btns.setSpacing(8)
        self.download_btn = self._make_button("⬇ 下载图片", self.download_current)
        self.next_btn = self._make_button("🔄 换一张", self.fetch_new)
        self.open_btn = self._make_button("↗ 打开原图", self.open_original)
        self.copy_btn = self._make_button("🔗 复制地址", self.copy_url)
        self.history_btn = QPushButton("📜 历史")
        self.history_btn.setObjectName("viewerBtn")
        self.history_btn.setCursor(Qt.PointingHandCursor)
        self.history_btn.setCheckable(True)
        self.history_btn.setChecked(True)
        self.history_btn.setToolTip("收起右侧历史栏")
        self.history_btn.toggled.connect(self._set_history_visible)
        for b in (self.download_btn, self.next_btn, self.open_btn,
                  self.copy_btn, self.history_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        card_lay.addLayout(btns)

        # ---- 状态栏 ----
        self.status_lbl = QLabel("就绪")
        self.status_lbl.setObjectName("viewerStatus")
        self.status_lbl.setWordWrap(True)
        card_lay.addWidget(self.status_lbl)

        # 让标题栏支持拖动
        self.title_bar.installEventFilter(self)
        self.title_icon.installEventFilter(self)
        self.title_lbl.installEventFilter(self)

    def _build_history_panel(self):
        """右侧历史栏（固定 140px）：缩略图 + 来源/作品名 + 清除历史。"""
        self.history_panel = QFrame()
        self.history_panel.setObjectName("cgHistoryPanel")
        self.history_panel.setFixedWidth(_HISTORY_PANEL_WIDTH)
        self.history_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        lay = QVBoxLayout(self.history_panel)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(8)

        title = QLabel("历史记录")
        title.setObjectName("cgHistoryTitle")
        lay.addWidget(title)

        self.history_scroll = QScrollArea()
        self.history_scroll.setObjectName("cgHistoryScroll")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QFrame.NoFrame)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.history_list = QWidget()
        self.history_list.setObjectName("cgHistoryList")
        self.history_lay = QVBoxLayout(self.history_list)
        self.history_lay.setContentsMargins(0, 0, 0, 0)
        self.history_lay.setSpacing(6)

        self.history_empty = QLabel("暂无历史")
        self.history_empty.setObjectName("cgHistoryEmpty")
        self.history_empty.setAlignment(Qt.AlignCenter)
        self.history_empty.setWordWrap(True)
        self.history_lay.addWidget(self.history_empty)
        self.history_lay.addStretch(1)

        self.history_scroll.setWidget(self.history_list)
        lay.addWidget(self.history_scroll, 1)

        self.clear_history_btn = QPushButton("清除历史")
        self.clear_history_btn.setObjectName("viewerBtn")
        self.clear_history_btn.setCursor(Qt.PointingHandCursor)
        self.clear_history_btn.setEnabled(False)
        self.clear_history_btn.clicked.connect(self.clear_history)
        lay.addWidget(self.clear_history_btn)

    def _make_button(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("viewerBtn")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _make_close_icon(self, size: int = 14) -> QIcon:
        """自绘小 X 图标，颜色跟随主题文字色。"""
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QColor(theme_manager.palette.get("text", "#FFFFFF"))
        pen = QPen(c)
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = max(2, int(size * 0.28))
        p.drawLine(m, m, size - m, size - m)
        p.drawLine(size - m, m, m, size - m)
        p.end()
        return QIcon(pm)

    # ------------------------------------------------------------------
    # 样式 / 主题
    # ------------------------------------------------------------------
    def _apply_style(self):
        p = theme_manager.palette
        qss = """
        QFrame#viewerCard { background: %(bg)s; border: 1px solid %(border)s;
                            border-radius: 14px; }
        QWidget#viewerTitleBar { background: %(card)s;
                                 border-top-left-radius: 14px;
                                 border-top-right-radius: 14px; }
        QLabel#viewerTitle { color: %(text)s; font-weight: 700; font-size: 14px; }
        QPushButton#viewerClose { background: transparent; border: none;
                                  border-radius: 8px; padding: 0; }
        QPushButton#viewerClose:hover { background: %(btn_hover)s; }
        QWidget#viewerToolbar { background: transparent; }
        QLabel#cgImageArea { background: %(card)s; border: 1px solid %(border_soft)s;
                             border-radius: 12px; color: %(muted)s;
                             font-size: 14px; }
        QPushButton#viewerBtn { background: %(btn)s; color: %(text)s;
                                border: 1px solid %(border)s; border-radius: 8px;
                                padding: 7px 14px; }
        QPushButton#viewerBtn:hover { background: %(btn_hover)s;
                                      border-color: %(accent)s; }
        QPushButton#viewerBtn:checked { background: %(btn_hover)s;
                                        border-color: %(accent)s; }
        QPushButton#viewerBtn:disabled { color: %(muted)s; }
        QLabel#viewerStatus { color: %(muted)s; font-size: 12px;
                              padding: 6px 16px 12px 16px; }
        QComboBox { background: %(input)s; color: %(text)s;
                    border: 1px solid %(border)s; border-radius: 8px;
                    padding: 5px 10px; min-height: 22px; }
        QComboBox:hover { border-color: %(accent)s; }
        QComboBox[pending="true"] { color: %(muted)s; }
        QFrame#cgHistoryPanel { background: %(card)s;
                                border: 1px solid %(border_soft)s;
                                border-radius: 12px; }
        QLabel#cgHistoryTitle { color: %(muted)s; font-size: 11px; font-weight: 700; }
        QScrollArea#cgHistoryScroll { background: transparent; border: none; }
        QWidget#cgHistoryList { background: transparent; }
        QLabel#cgHistoryEmpty { color: %(muted)s; font-size: 11px; padding: 12px 2px; }
        QFrame#cgHistoryItem { background: %(input)s; border: 1px solid %(border_soft)s;
                               border-radius: 8px; }
        QFrame#cgHistoryItem:hover { border-color: %(accent)s; }
        QFrame#cgHistoryItem[selected="true"] { border-color: %(accent)s;
                                                background: %(btn_hover)s; }
        QLabel#cgHistoryThumb { background: transparent; color: %(muted)s;
                                font-size: 10px; }
        QLabel#cgHistoryText { color: %(muted)s; font-size: 11px; }
        """ % {
            "bg": p["bg"], "card": p["card"], "text": p["text"],
            "muted": p["muted"], "border": p["border"],
            "border_soft": _rgba(p["border"], p.get("border_a", 0.1)),
            "btn": p["btn"], "btn_hover": p["btn_hover"],
            "accent": p["accent"], "danger": p["danger"],
            "pink": p.get("pink", p["accent"]), "input": p["input"],
        }
        self.setStyleSheet(qss)
        if getattr(self, "close_btn", None) is not None:
            self.close_btn.setIcon(self._make_close_icon(14))
        if getattr(self, "source_combo", None) is not None:
            self._apply_source_combo_pending_style()

    def _apply_source_combo_pending_style(self):
        """未接入图源的视觉处理：文字用 muted 色，但仍可 hover / 键盘导航 / 选中。

        弹窗项用小写 muted 的 QBrush 走 ForegroundRole（可覆盖弹窗 QSS）；
        关闭状态下选中项的底色文字由 QComboBox[pending="true"] 规则接管。
        """
        brush = QBrush(QColor(theme_manager.palette.get("muted", "#888888")))
        model = self.source_combo.model()
        for i in range(self.source_combo.count()):
            if self.source_combo.itemData(i) not in _PENDING_LABELS:
                continue
            item = model.item(i) if hasattr(model, "item") else None
            if item is not None:
                item.setForeground(brush)
        pending = self._current_source_mode() in _PENDING_LABELS
        self.source_combo.setProperty("pending", "true" if pending else "false")
        self.source_combo.style().unpolish(self.source_combo)
        self.source_combo.style().polish(self.source_combo)

    def _on_theme_changed(self, *_args):
        if not self._alive:
            return
        self._apply_style()
        self._apply_current_pixmap()

    # ------------------------------------------------------------------
    # 分类下拉（完全由当前图源决定，UI 不自己猜）
    #
    #   auto   自动      -> 置灰（跨图源，没有可用的分类维度）
    #   local  本地图库  -> 全部作品 + 本地作品名（沿用现有本地扫描结果）
    #   first  illlights -> 全部 + 作品名 + 作品名·分辨率（沿用现有 /v1/img/info）
    #   second dmoe      -> 置灰（接口没有分类参数）
    #   uapipro          -> UapiProProvider.categories() 自己声明的分类
    #   loliapi          -> LoliApiProvider.categories() 自己声明的分类（PC端 / 移动端）
    # ------------------------------------------------------------------
    def _current_source_mode(self) -> str:
        try:
            return str(self.source_combo.currentData() or "auto")
        except Exception:
            return "auto"

    def _set_filter_placeholder(self, combo, text: str = "无"):
        """把分类下拉设成「无」并禁用（当前图源没有分类时用）。"""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(text, None)
        combo.setCurrentIndex(0)
        combo.setEnabled(False)
        combo.blockSignals(False)

    def _find_category_index(self, data) -> int:
        """按数据找回分类下拉的选中项（数据统一是 (作品名, 分辨率) 元组）。"""
        if data is None:
            return -1
        for i in range(self.category_combo.count()):
            if self.category_combo.itemData(i) == data:
                return i
        return -1

    @staticmethod
    def _parse_category(data):
        """分类数据统一是 (作品名/游戏名, 分辨率)；没有分类时返回 (None, None)。"""
        if isinstance(data, (tuple, list)) and len(data) == 2:
            name, size = data
            return (str(name) if name else None, str(size) if size else None)
        return (None, None)

    @staticmethod
    def _category_label(name, size) -> str:
        """分类的显示文案（取图后写进历史记录用）。"""
        if name and size:
            return "%s · %s" % (name, size)
        return str(name or "")

    def _refresh_category_combo(self, force: bool = False):
        """按当前图源重建分类下拉；当前图源不支持分类时一律置灰。"""
        self._categories_ready = False
        mode = self._current_source_mode()

        if mode == "first":
            # illlights：沿用现有 /v1/img/info（不新增任何外部请求）；
            # 信息回来之前先禁用，避免拿着上一个图源的残留选项去筛选
            self.category_combo.setEnabled(False)
            self._load_info_async(force)
            return

        if mode == "local":
            # 本地图库：分类 = 图片归属的游戏名（沿用现有本地扫描）
            self.category_combo.setEnabled(False)
            self._load_local_names_async(force)
            return

        if mode == "uapipro":
            # UapiPro：分类由 Provider 自己声明（纯静态列表，无需联网）
            self._fill_uapipro_categories()
            return

        if mode == "loliapi":
            # LoliAPI：分类由 Provider 自己声明（PC端 / 移动端，纯静态）
            self._fill_loliapi_categories()
            return

        # auto / second：不提供分类
        self._set_filter_placeholder(self.category_combo, "无")
        self._categories_ready = True

    def _fill_loliapi_categories(self):
        """把 LoliApiProvider.categories() 的显示名填进分类下拉。

        分类提交值是设备标识字符串（"pc" / "pe"），原样存进 itemData。
        """
        provider = getattr(self._fetcher, "providers", {}).get("loliapi")
        items = []
        if provider is not None:
            try:
                items = list(provider.categories() or [])
            except Exception:
                items = []

        old = self.category_combo.currentData()
        self._filling_combos = True
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for label, value in items:
            self.category_combo.addItem(str(label), value)
        if self.category_combo.count():
            idx = self._find_category_index(old)
            self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.category_combo.blockSignals(False)
        self.category_combo.setEnabled(bool(self.category_combo.count()))
        self._filling_combos = False
        self._categories_ready = True

    def _fill_uapipro_categories(self):
        """把 UapiProProvider.categories() 的显示名填进分类下拉。

        分类提交值是参数字典（{"category": ..., "type": ...}），
        原样存进 itemData，取图时再交给 Provider。
        """
        provider = getattr(self._fetcher, "providers", {}).get("uapipro")
        items = []
        if provider is not None:
            try:
                items = list(provider.categories() or [])
            except Exception:
                items = []

        old = self.category_combo.currentData()
        self._filling_combos = True
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for label, params in items:
            self.category_combo.addItem(str(label), dict(params or {}))
        if self.category_combo.count():
            idx = self._find_category_index(old)
            self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.category_combo.blockSignals(False)
        self.category_combo.setEnabled(bool(self.category_combo.count()))
        self._filling_combos = False
        self._categories_ready = True

    def _reload_library_index(self):
        """数据库可能刚被“整理图库”改过，重建游戏索引并清掉本地扫描缓存。"""
        if self._db is None:
            return
        try:
            self._library_index = self._build_library_index(self._db)
            self._fetcher.library_index = self._library_index
            self._fetcher.reset_local_cache()
        except Exception:
            pass

    def _refresh_source_info(self, force: bool = False):
        """「刷新图库信息」按钮：按当前图源重新拉取对应的分类信息。"""
        self._reload_library_index()
        self._refresh_category_combo(force)
        if self._current_source_mode() in ("auto", "second"):
            self.status_lbl.setText("当前图源（自动 / dmoe）不提供分类。")

    # ---- illlights：远端 /v1/img/info ----
    def _load_info_async(self, force: bool = False):
        signals = _WorkerSignals()
        signals.done.connect(self._on_remote_info_loaded)
        self._signal_pool.append(signals)
        thread = _WorkerThread(self._fetcher.get_info, signals, force)
        self._threads.append(thread)
        self._threads = self._threads[-10:]
        thread.start()
        self.status_lbl.setText("正在读取主图库筛选信息…" if force else "正在加载主图库信息…")

    def _on_remote_info_loaded(self, value):
        # 用户可能在等待期间切换了图源，结果只对「illlights」生效
        if not self._alive or self._current_source_mode() != "first":
            return
        if not isinstance(value, dict):
            self.status_lbl.setText("illlights 分类信息读取失败，分类暂不可用。")
            self._set_filter_placeholder(self.category_combo, "无")
            self._categories_ready = True
            return
        self._fill_combos(value)

    def _fill_combos(self, info: dict):
        """把现有 /v1/img/info 填进分类下拉（other 不是可查询值，必须过滤掉）。"""
        names = [str(n) for n in (info.get("names") or []) if str(n).strip()]
        by_name_size = list(info.get("by_name_size") or [])

        # 每个作品可用的分辨率（过滤掉 other）
        self._by_name_size = {}
        for row in by_name_size:
            n = str(row.get("name") or "")
            s = str(row.get("size") or "")
            if n and s and s.lower() != "other":
                sizes = self._by_name_size.setdefault(n, [])
                if s not in sizes:
                    sizes.append(s)

        old = self.category_combo.currentData()
        self._filling_combos = True
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("全部", (None, None))
        for n in names:
            self.category_combo.addItem(n, (n, None))
        for n in names:
            for s in self._by_name_size.get(n, []):
                self.category_combo.addItem("%s · %s" % (n, s), (n, s))
        idx = self._find_category_index(old)
        self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.category_combo.blockSignals(False)
        self.category_combo.setEnabled(True)
        self._filling_combos = False
        self._categories_ready = True

    # ---- 本地图库：本地作品名 ----
    def _load_local_names_async(self, force: bool = False):
        signals = _WorkerSignals()
        signals.done.connect(self._on_local_names_loaded)
        self._signal_pool.append(signals)
        thread = _WorkerThread(self._fetcher.local_game_names, signals, force)
        self._threads.append(thread)
        self._threads = self._threads[-10:]
        thread.start()
        self.status_lbl.setText("正在扫描本地 CG 图库…" if force else "正在加载本地图库信息…")

    def _on_local_names_loaded(self, value):
        # 用户可能已经切回别的图源，过期的扫描结果直接丢弃
        if not self._alive or self._current_source_mode() != "local":
            return
        failed = isinstance(value, Exception)
        names = [] if failed else list(value or [])

        old = self.category_combo.currentData()
        self._filling_combos = True
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem(cg_library.ALL_GAMES_LABEL, (None, None))
        for n in names:
            self.category_combo.addItem(str(n), (str(n), None))
        idx = self._find_category_index(old)
        self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.category_combo.blockSignals(False)
        self.category_combo.setEnabled(True)
        self._filling_combos = False
        self._categories_ready = True

        if failed:
            self.status_lbl.setText("本地图库扫描失败：%s" % value)
        elif self._current is None:
            self.status_lbl.setText("本地图库：%d 个作品分类" % len(names))

    def _on_source_changed(self, _idx):
        if self._filling_combos:
            return
        self._apply_source_combo_pending_style()
        self._refresh_category_combo()
        if self._current_source_mode() in _PENDING_LABELS:
            # 未接入图源：只给提示，不取图、不发请求、不回退其它图源
            self._show_pending_source()
            return
        self.fetch_new()

    def _on_category_changed(self, _idx):
        if self._filling_combos or not self._categories_ready:
            return
        self.fetch_new()

    # ------------------------------------------------------------------
    # 取图
    # ------------------------------------------------------------------
    def fetch_new(self):
        if not self._alive:
            return
        if self._current_source_mode() in _PENDING_LABELS:
            # 未接入图源：换一张 / Space / 重试 也只给提示，绝不取图、不回退
            self._show_pending_source()
            return
        self._request_id += 1
        rid = self._request_id
        source_mode = self._current_source_mode()

        raw_category = self.category_combo.currentData()
        name, size = self._parse_category(raw_category)
        category_label = self._category_label(name, size)

        # 只有 illlights 支持服务端筛选；本地图库的作品名只用于挑本地文件
        if source_mode == "first":
            pass
        elif source_mode == "local":
            size = None
        elif source_mode == "uapipro":
            # UapiPro 的分类数据是参数字典 {"category": ..., "type": ...}；
            # 沿用现有 name / size 两个槽位承载 category / type，不改 fetch_random 签名
            if isinstance(raw_category, dict):
                name = raw_category.get("category") or None
                size = raw_category.get("type") or None
            else:
                name = None
                size = None
            category_label = self.category_combo.currentText()
        elif source_mode == "loliapi":
            # LoliAPI 的分类数据是设备标识字符串（"pc" / "pe"）；
            # 沿用 name 槽位承载，size 不用
            name = raw_category if isinstance(raw_category, str) else None
            size = None
            category_label = self.category_combo.currentText()
        else:
            name = None
            size = None
            category_label = ""

        # 记住本次请求的分类文案，结果回来后按 request_id 配对写进历史
        self._pending[rid] = (source_mode, category_label)
        if len(self._pending) > 8:
            for key in sorted(self._pending)[:-8]:
                self._pending.pop(key, None)

        self.retry_btn.hide()
        self._set_loading(True)
        self.status_lbl.setText("正在加载随机 CG…")

        signals = _WorkerSignals()
        signals.done.connect(self._on_worker_done)
        self._signal_pool.append(signals)
        thread = _WorkerThread(self._fetcher.fetch_random, signals,
                               name, size, rid, source_mode)
        self._threads.append(thread)
        self._threads = self._threads[-10:]
        thread.start()

    def _on_worker_done(self, value):
        if not self._alive:
            return
        if isinstance(value, CGResult):
            self._on_fetch_result(value)
        elif isinstance(value, Exception):
            self.status_lbl.setText("网络请求失败：%s" % value)
        else:
            self.status_lbl.setText("收到未知返回类型：%s" % type(value).__name__)

    def _on_fetch_result(self, result: CGResult):
        if not self._alive:
            return
        if result.request_id != self._request_id:
            return
        self._set_loading(False)

        if result.ok:
            # 如果在历史中间重新取图，丢掉后面的旧历史
            if self._history_index >= 0 and self._history_index < len(self._history) - 1:
                del self._history[self._history_index + 1:]
            source_mode, category_label = self._pending.pop(
                result.request_id, (self._current_source_mode(), ""))
            item = _make_history_item(result, source_mode, category_label)
            self._history.append(item)
            if len(self._history) > _HISTORY_MAX:
                self._history = self._history[-_HISTORY_MAX:]
            self._history_index = len(self._history) - 1
            # 只有「刚取回的这张」保留原始下载字节；历史项里不存
            self._download_fresh = (result.download_bytes, result.download_ext)
            self._rebuild_history_ui()
            self._display_item(item, fresh=True)
            self._scroll_history_to(item)
            return

        if result.no_match:
            self._show_error(result.message, allow_retry=False)
        else:
            self._show_error(result.message or "加载失败，请重试。", allow_retry=True)

    def _display_item(self, item, fresh: bool = False):
        """把一条历史项显示到主预览区（回看历史时不重新请求任何接口）。"""
        self._current = item
        if not fresh:
            # 回看历史：不再保留「刚取回」的原始字节，下载走本地文件 / 预览字节
            self._download_fresh = None
        pm = QPixmap()
        if item.display_bytes:
            pm.loadFromData(item.display_bytes)
        if pm.isNull():
            self._current = None
            self._show_error("图片解码失败。", allow_retry=True)
            self._sync_history_selection()
            return
        self._pixmap_original = pm
        self._apply_current_pixmap()
        self.status_lbl.setText(item.status_text())
        self.image_area.setToolTip(item.tooltip())
        self._update_buttons()
        self._sync_history_selection()

    def _show_error(self, message: str, allow_retry: bool = True):
        self._pixmap_original = None
        self._pixmap_scaled = None
        self.image_area.setPixmap(QPixmap())
        self.image_area.setText("加载失败\n%s" % (message or ""))
        self.retry_btn.setVisible(bool(allow_retry))
        self.status_lbl.setText(message or "加载失败")
        self._update_buttons()

    def _show_pending_source(self):
        """未接入图源：主预览区与状态栏给明确提示。

        不取图、不发任何请求、不伪造结果、也不偷偷回退其它图源。
        """
        label = _PENDING_LABELS.get(self._current_source_mode(), "该图源")
        msg = "%s：该图源将在后续阶段接入。" % label
        # 作废可能还在路上的旧请求，避免旧图源的结果盖掉提示
        self._request_id += 1
        self._set_loading(False)
        self._current = None
        self._download_fresh = None
        self._pixmap_original = None
        self._pixmap_scaled = None
        self.image_area.setPixmap(QPixmap())
        self.image_area.setText(msg)
        self.image_area.setToolTip("")
        self.retry_btn.hide()
        self.status_lbl.setText(msg)
        self._update_buttons()
        self._sync_history_selection()

    def _set_loading(self, loading: bool):
        if loading:
            self._loading_dots = 0
            self.image_area.setPixmap(QPixmap())
            self.image_area.setText("加载中")
            self._loading_timer.start()
            self.retry_btn.hide()
        else:
            self._loading_timer.stop()

    def _tick_loading(self):
        self._loading_dots = (self._loading_dots + 1) % 4
        self.image_area.setText("加载中" + "." * self._loading_dots)

    # ------------------------------------------------------------------
    # 图片缩放
    # ------------------------------------------------------------------
    def _apply_current_pixmap(self):
        if self._pixmap_original is None or self._pixmap_original.isNull():
            return
        area = self.image_area.size()
        # 留一点内边距，避免贴边
        tw = max(80, area.width() - 16)
        th = max(80, area.height() - 16)
        pm = self._pixmap_original.scaled(tw, th, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation)
        self._pixmap_scaled = pm
        self.image_area.setPixmap(pm)
        self.image_area.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap_original is not None:
            self._resize_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_current_pixmap)

    def _center_on_parent(self):
        p = self.parentWidget()
        if p is None:
            return
        center = p.geometry().center()
        self.move(center.x() - self.width() // 2,
                  center.y() - self.height() // 2)

    # ------------------------------------------------------------------
    # 历史 / 操作
    # ------------------------------------------------------------------
    def _rebuild_history_ui(self):
        """按 self._history 重建右侧历史栏（最多 20 条，重建成本可忽略）。"""
        for w in self._history_widgets:
            self.history_lay.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._history_widgets = []
        for item in self._history:
            w = _HistoryItemWidget(item, self._on_history_item_clicked,
                                   self.history_list)
            self._history_widgets.append(w)
            # 插到末尾 stretch 之前
            self.history_lay.insertWidget(self.history_lay.count() - 1, w)
        self.history_empty.setVisible(not self._history)
        self.clear_history_btn.setEnabled(bool(self._history))
        self._sync_history_selection()

    def _sync_history_selection(self):
        cur = self._current
        for w in self._history_widgets:
            w.set_selected(w.item is cur)

    def _scroll_history_to(self, item):
        for w in self._history_widgets:
            if w.item is item:
                try:
                    self.history_scroll.ensureWidgetVisible(w, 0, 0)
                except Exception:
                    pass
                return

    def _on_history_item_clicked(self, item):
        """点击历史项：主预览区直接跳回该图片，不重新请求任何接口。"""
        for i, it in enumerate(self._history):
            if it is item:
                self._history_index = i
                break
        self._display_item(item)
        self._scroll_history_to(item)

    def show_history_prev(self):
        """Left 快捷键：回看上一条历史（不重新请求）。"""
        if not self._history or self._history_index <= 0:
            return
        self._history_index -= 1
        item = self._history[self._history_index]
        self._display_item(item)
        self._scroll_history_to(item)

    def clear_history(self):
        """清除历史：只清内存列表，不影响当前预览。"""
        self._history = []
        self._history_index = -1
        self._download_fresh = None
        self._rebuild_history_ui()

    def _set_history_visible(self, show: bool):
        """展开 / 收起右侧历史栏（历史按钮联动）。"""
        show = bool(show)
        self.history_panel.setVisible(show)
        self.setMinimumSize(*(_MIN_SIZE_WITH_HISTORY if show else _MIN_SIZE_NO_HISTORY))
        self.history_btn.setToolTip("收起右侧历史栏" if show else "展开右侧历史栏")
        if show:
            QTimer.singleShot(0, self._apply_current_pixmap)

    def _download_payload(self):
        """返回当前图片的 (下载字节, 扩展名)。"""
        if self._download_fresh is not None:
            return self._download_fresh
        item = self._current
        if item is None:
            return (b"", ".jpg")
        # 本地图：直接读原文件，保真且不联网
        if item.local_path and os.path.isfile(item.local_path):
            try:
                with open(item.local_path, "rb") as f:
                    return (f.read(),
                            os.path.splitext(item.local_path)[1] or ".jpg")
            except Exception:
                pass
        # 回看的在线图：只有预览字节可存
        return (item.display_bytes, ".jpg")

    def download_current(self):
        if self._current is None:
            return
        data, ext = self._download_payload()
        if not data:
            return
        default_name = "random_cg_%s%s" % (time.strftime("%Y%m%d_%H%M%S"), ext)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存随机 CG", default_name,
            "图片文件 (*.jpg *.png *.webp *.gif *.bmp);;所有文件 (*.*)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ext
        try:
            with open(path, "wb") as f:
                f.write(data)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.status_lbl.setText("已保存：%s" % path)

    def open_original(self):
        if self._current is None:
            return
        if self._current.local_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._current.local_path))
        elif self._current.url:
            QDesktopServices.openUrl(QUrl(self._current.url))

    def copy_url(self):
        if self._current is None:
            return
        text = self._current.local_path or self._current.url
        if text:
            QApplication.clipboard().setText(text)
            self.status_lbl.setText("已复制地址：%s" % text)

    def _update_buttons(self):
        has_img = self._current is not None
        for b in (self.download_btn, self.open_btn, self.copy_btn):
            b.setEnabled(bool(has_img))
        self.clear_history_btn.setEnabled(bool(self._history))

    # ------------------------------------------------------------------
    # 快捷键 / 拖动 / 关闭
    # ------------------------------------------------------------------
    def _bind_shortcuts(self):
        self._shortcuts = []
        for seq, slot in (
            ("Space", self.fetch_new),
            ("Ctrl+S", self.download_current),
            ("Ctrl+C", self.copy_url),
            ("Esc", self.close),
            ("Left", self.show_history_prev),
        ):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

    def eventFilter(self, obj, event):
        # 无边框窗口：按住标题栏拖动
        if obj in (getattr(self, "title_bar", None),
                   getattr(self, "title_icon", None),
                   getattr(self, "title_lbl", None)):
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.MouseMove and self._drag_pos is not None:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                return True
            if event.type() == QEvent.MouseButtonRelease:
                self._drag_pos = None
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self._alive = False
        self._loading_timer.stop()
        self._resize_timer.stop()
        # 历史只存内存：关窗即清空
        self._history = []
        self._history_index = -1
        self._download_fresh = None
        try:
            self._rebuild_history_ui()
        except Exception:
            self._history_widgets = []
        try:
            theme_manager.themeChanged.disconnect(self._on_theme_changed)
        except Exception:
            pass
        for sig in getattr(self, "_signal_pool", []):
            try:
                sig.done.disconnect()
            except Exception:
                pass
        super().closeEvent(event)


# 独立运行：直接弹出预览窗口，方便先测试再接入主程序
if __name__ == "__main__":
    app = QApplication(sys.argv)
    from theme import _apply_theme
    _apply_theme()
    win = RandomCGViewer()
    win.show()
    sys.exit(app.exec())
