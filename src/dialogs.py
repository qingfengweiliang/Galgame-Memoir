# -*- coding: utf-8 -*-
"""????????/???????????????????????"""

import os
import re
import csv
import random
import io
import zipfile
import time
import shutil
import hashlib
import urllib.parse
from xml.etree import ElementTree as ET

from PIL import Image

from PySide6.QtCore import Qt, QTimer, QSize, QPoint, QUrl, QRect, QRectF, QThread, Signal, QFileSystemWatcher
from PySide6.QtGui import QPixmap, QIcon, QFont, QImage, QPainter, QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QSpinBox, QDoubleSpinBox, QTextEdit,
    QListWidget, QListWidgetItem, QFrame, QDialogButtonBox, QMessageBox, QFileDialog,
    QScrollArea, QSizePolicy, QToolButton, QAbstractItemView, QListView, QPlainTextEdit,
    QProgressBar, QMenu, QTableWidget, QTableWidgetItem, QHeaderView, QToolTip,
    QGraphicsOpacityEffect, QGroupBox, QInputDialog, QSlider, QCheckBox, QTabWidget,
    QRadioButton, QButtonGroup, QStyle,
)

import config
from config import (
    get_theme, set_theme, set_accent, get_accent, ACCENT_PRESETS, accent_color,
    accent_hover, accent_soft, get_sgdb_key, set_sgdb_key, get_bgm_token, set_bgm_token,
    set_bgm_username, set_bgm_nickname, get_bgm_username, get_bgm_nickname,
    get_cg_root, set_cg_root, get_hover_interval, set_hover_interval, get_hover_size,
    set_hover_size, get_bg_image, set_bg_image, get_sauce_key, set_sauce_key,
    get_theme_id, set_theme_id, get_color_mode, set_color_mode, get_effective_mode,
    get_accent_override, set_accent_override, get_custom_background_path,
    STATUS_OPTIONS, CATEGORY_OPTIONS, IMAGE_EXTENSIONS, DB_PATH, BANGUMI_UA, COVERS_DIR,
    to_abs, normalize_rel, now_str, fmt_rating, make_placeholder_pixmap,
    load_thumb_qpixmap, load_cover_icon, thumbs_rel_path, _load_pix_fast, _load_pix_cover,
    _transpose,
    ask_yes_no, _orphan_worker, delete_game_and_files, delete_cover_if_unused, _hover_box_size,
    APP_NAME, APP_SUBTITLE, APP_VERSION,
    PET_LINES, get_pet_lines, set_pet_lines, get_pet_click_random,
    set_pet_click_random, get_pet_auto_minutes, set_pet_auto_minutes,
    get_assistant_hidden, set_assistant_hidden,
    set_user_image, clear_user_image, get_user_image,
    set_avatar_image, set_pet_image, get_avatar_image,
    get_preset_dir, list_presets, preset_rel_path,
)
from database import Database
import cg_library
import net
from net import (
    _bangumi_search, _vndb_search, _steam_search, _sgdb_search, _search_by_source,
    _download_cover, _split_rating, _map_bgm_status, _identify_image, _name_key,
)
import workers
from workers import (
    ImageSearchWorker, ThumbLoaderWorker, BangumiSearchWorker, VndbSearchWorker,
    SteamSearchWorker, SgdbSearchWorker, BangumiLoginWorker, BangumiCollectionWorker,
    CoverDownloadWorker, CoverPreviewWorker, BatchImportWorker, RecognizeWorker,
    ScreenshotImportWorker, DetailFetchWorker,
)
from theme import (
    TopComboBox, PlainHeaderButton, ThemeToggleSwitch, CollapsibleSection, draw_icon,
    _apply_theme, _apply_bg, SectionCard, chip_label, set_chip_color, FlowLayout,
    rounded_cover_pixmap, rounded_pixmap, status_color, pstr, app_icon_pixmap,
)
from theme_defs import THEME_DEFS, THEME_ORDER, theme_name
from theme_manager import theme_manager

class SubjectSelectDialog(QDialog):
    """让用户从搜索结果中选择一条。"""

    def __init__(self, results: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("%s · 选择搜索结果" % APP_NAME)
        self.setMinimumSize(520, 380)
        self.selected = None
        self.results = results

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("请选择最匹配的游戏条目："))
        self.list_widget = QListWidget()
        for it in results:
            label = it["name_cn"] or it["name"]
            if it["name"] and it["name"] != it["name_cn"]:
                label = f"{label}  ({it['name']})"
            if it["date"]:
                label += f"   ·  {it['date']}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, it)
            self.list_widget.addItem(item)
        lay.addWidget(self.list_widget)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("确定")
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.accepted.connect(self._accept_ok)
        btn_box.rejected.connect(self.reject)
        lay.addWidget(btn_box)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(lambda _: self._accept_ok())

    def _accept_ok(self):
        cur = self.list_widget.currentItem()
        if cur:
            self.selected = cur.data(Qt.UserRole)
        self.accept()


class CategoryDialog(QDialog):
    """多选图片后，为每个文件选择一个分类。"""

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("%s · 选择截图分类" % APP_NAME)
        self.setMinimumSize(500, 420)
        self.resize(520, 520)
        self.files = files
        self.combos = []

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("请为以下图片分别选择分类："))
        # 统一设置分类：一个下拉框 + 应用到全部按钮
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("统一分类："))
        self.batch_combo = TopComboBox()
        self.batch_combo.addItems(CATEGORY_OPTIONS)
        self.batch_combo.setCurrentText("其他")
        batch_row.addWidget(self.batch_combo, 1)
        apply_btn = QPushButton("应用到全部")
        apply_btn.clicked.connect(self._apply_all)
        batch_row.addWidget(apply_btn)
        lay.addLayout(batch_row)

        # 文件列表放入滚动区，避免文件多时挤压/超出屏幕
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(2)
        for f in files:
            combo = TopComboBox()
            combo.addItems(CATEGORY_OPTIONS)
            combo.setCurrentText("其他")
            self.combos.append(combo)
            form.addRow(os.path.basename(f), combo)
        inner.setLayout(form)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("确定")
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        lay.addWidget(btn_box)

    def _apply_all(self):
        for c in self.combos:
            c.setCurrentText(self.batch_combo.currentText())

    def get_categories(self) -> list:
        return [c.currentText() for c in self.combos]


# ============================================================
# 智能填充 / 每栏 🔎
#   把 detail（VNDB / Bangumi 统一结构）映射到表单字段。
# ============================================================

# (key, 显示名, 分组, 控件属性名, 类型)
#   text  = 单行文本          list = 列表，写入时用 ", " 连接
#   lines = 列表，写入时每行一条   int  = 数值
_DETAIL_FIELDS = (
    ("title",        "标题",     "basic", "title_edit",      "text"),
    ("title_jp",     "原名",     "basic", "title_jp_edit",   "text"),
    ("developer",    "开发商",   "basic", "developer_edit",  "text"),
    ("release_date", "发售日",   "basic", "release_edit",    "text"),
    ("publisher",    "发行商",   "extra", "publisher_edit",  "text"),
    ("genres",       "类型",     "extra", "genres_edit",     "list"),
    ("tags",         "标签",     "extra", "tags_edit",       "list"),
    ("summary",      "简介",     "extra", "summary_edit",    "text"),
    ("characters",   "角色",     "extra", "characters_edit", "lines"),
    ("voices",       "声优",     "extra", "voice_edit",      "list"),
    ("staff",        "制作人员", "extra", "staff_edit",      "lines"),
    ("play_time",    "游玩时长", "extra", "playtime_spin",   "int"),
)

_DETAIL_GROUP_TITLE = {"basic": "基本信息", "extra": "剧情与制作"}

# 这些字段列表可能很长：默认不勾，展开后逐项挑
_DETAIL_BIG_FIELDS = ("characters", "voices", "staff")

# 字段 -> 控件属性名
_DETAIL_ATTR = {key: attr for key, _t, _g, attr, _k in _DETAIL_FIELDS}

# 字段 -> 显示名（提示文案用）
_DETAIL_LABEL = {key: title for key, title, _g, _a, _k in _DETAIL_FIELDS}

# 该数据源「结构上永远没有」的字段：点 🔎 时直接提示，不触发搜索。
#   只登记与条目无关、恒定缺失的字段；条目级偶发缺失只能搜完才知道。
_SOURCE_NO_FIELD = {
    "vndb": {"publisher"},      # VNDB 没有发行商概念
    "bangumi": {"play_time"},   # Bangumi 没有游玩时长字段
}


def _shift_held() -> bool:
    """当前是否按住 Shift（🔎 用于强制重新搜索）。"""
    try:
        return bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)
    except Exception:
        return False


def _detail_items(detail: dict, key: str) -> list:
    """把列表型字段拆成可逐项勾选的 [{label, value, checked}]；非列表返回 []。"""
    d = detail or {}
    if key == "characters":
        items = []
        for c in d.get("characters") or []:
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            cv = str(c.get("cv") or "").strip()
            # 展开时把声优一起显示，方便挑人；写入表单时只写角色名
            items.append({"label": ("%s（%s）" % (name, cv)) if cv else name,
                          "value": name, "checked": True})
        return items
    if key == "staff":
        items = []
        for s in d.get("staff") or []:
            name = str(s.get("name") or "").strip()
            if not name:
                continue
            text = "%s：%s" % (str(s.get("role") or "").strip(), name)
            items.append({"label": text, "value": text, "checked": True})
        return items
    if key in ("genres", "tags", "voices"):
        return [{"label": str(x), "value": str(x), "checked": True}
                for x in (d.get(key) or []) if str(x).strip()]
    return []


def _detail_value(detail: dict, key: str):
    """字段原始值：列表字段 -> list[str]；游玩时长 -> int；其它 -> str。"""
    if key in ("characters", "staff", "genres", "tags", "voices"):
        return [it["value"] for it in _detail_items(detail, key)]
    if key == "play_time":
        try:
            return int((detail or {}).get("play_time") or 0)
        except (TypeError, ValueError):
            return 0
    return str((detail or {}).get(key) or "").strip()


def _detail_preview(key: str, value) -> str:
    """一行预览文字（截断）。"""
    if isinstance(value, list):
        if not value:
            return ""
        head = "、".join(value[:4])
        if len(value) > 4:
            head += " …"
        return "共 %d 项：%s" % (len(value), head)
    s = str(value or "").strip()
    return s if len(s) <= 70 else s[:70] + "…"


class _PickerRow(QWidget):
    """二级菜单的一行：勾选框 + 真实值预览 +（可选）展开后逐项勾选。"""

    def __init__(self, key: str, title: str, value, available: bool = True,
                 checked: bool = True, items: list = None, note: str = "",
                 parent=None):
        super().__init__(parent)
        self.key = key
        self._value = value
        self._items = items or []
        self.available = available
        self._list = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 3, 0, 3)
        root.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.check = QCheckBox(title)
        self.check.setChecked(bool(checked) and bool(available))
        self.check.setEnabled(bool(available))
        self.check.setMinimumWidth(84)
        head.addWidget(self.check, 0)

        self.preview = QLabel(note or _detail_preview(key, value))
        self.preview.setObjectName("hint")
        self.preview.setToolTip(str(value) if not isinstance(value, list) else "、".join(map(str, value)))
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head.addWidget(self.preview, 1)

        self.expand_btn = None
        if self._items or (isinstance(value, str) and len(value) > 70):
            self.expand_btn = QToolButton()
            self.expand_btn.setText("展开")
            self.expand_btn.setCheckable(True)
            self.expand_btn.setAutoRaise(True)
            self.expand_btn.toggled.connect(self._on_expand)
            head.addWidget(self.expand_btn, 0)
        root.addLayout(head)

        self.body = self._build_body()
        if self.body is not None:
            self.body.setVisible(False)
            root.addWidget(self.body)

    def _build_body(self):
        if self._items:
            lst = QListWidget()
            lst.setMaximumHeight(150)
            lst.setSelectionMode(QAbstractItemView.NoSelection)
            for it in self._items:
                li = QListWidgetItem(str(it.get("label") or it.get("value")))
                li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
                li.setCheckState(Qt.Checked if it.get("checked") else Qt.Unchecked)
                li.setData(Qt.UserRole, it.get("value"))
                lst.addItem(li)
            self._list = lst
            return lst
        if isinstance(self._value, str) and len(self._value) > 70:
            view = QPlainTextEdit()
            view.setPlainText(self._value)
            view.setReadOnly(True)
            view.setMaximumHeight(110)
            return view
        return None

    def _on_expand(self, on):
        if self.body is not None:
            self.body.setVisible(bool(on))
        if self.expand_btn is not None:
            self.expand_btn.setText("收起" if on else "展开")

    def is_checked(self) -> bool:
        return bool(self.available) and self.check.isChecked()

    def selected_value(self):
        """勾选生效时应写入的值；没有内容返回 None。"""
        if self._items:
            if self._list is None:
                return None
            vals = [self._list.item(i).data(Qt.UserRole)
                    for i in range(self._list.count())
                    if self._list.item(i).checkState() == Qt.Checked]
            vals = [v for v in vals if str(v or "").strip()]
            return vals or None
        if isinstance(self._value, list):
            return self._value or None
        if self.key == "play_time":
            try:
                return int(self._value or 0) or None
            except (TypeError, ValueError):
                return None
        return str(self._value or "").strip() or None


class FieldPickerDialog(QDialog):
    """智能填充的二级菜单：勾选要把哪些栏目写进表单。"""

    def __init__(self, detail: dict, parent=None):
        super().__init__(parent)
        self.detail = detail or {}
        self.rows = {}
        src = str(self.detail.get("source") or "").lower()
        self.src_name = {"vndb": "VNDB", "bangumi": "Bangumi"}.get(src, src or "?")
        self.setWindowTitle("%s · 智能填充" % APP_NAME)
        self.setMinimumSize(640, 600)
        self._build_ui()

    # ---------- 构建 ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QLabel("数据源：%s · %s · %s" % (
            self.src_name, self.detail.get("id", ""),
            self.detail.get("title") or self.detail.get("title_jp") or ""))
        head.setWordWrap(True)
        head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(head)
        root.addWidget(QLabel("勾选要填充进去的栏目；点「展开」可以逐项挑选。"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(2)

        zh_summary = bool(self.detail.get("has_summary_zh"))
        cur_group = None
        for key, title, group, _attr, _kind in _DETAIL_FIELDS:
            if group != cur_group:
                cur_group = group
                col.addSpacing(8)
                gl = QLabel(_DETAIL_GROUP_TITLE.get(group, group))
                gf = gl.font()
                gf.setBold(True)
                gl.setFont(gf)
                col.addWidget(gl)

            value = _detail_value(self.detail, key)
            items = _detail_items(self.detail, key)
            if isinstance(value, list):
                available = bool(value)
            elif key == "play_time":
                available = bool(value)
            else:
                available = bool(str(value or "").strip())

            checked = available
            if key in _DETAIL_BIG_FIELDS:
                checked = False          # 角色/声优/制作人员默认不勾
            if key == "summary" and not zh_summary:
                checked = False          # VNDB 是英文简介，默认不填

            row = _PickerRow(key, title, value, available=available,
                             checked=checked, items=items,
                             note="" if available else "（该数据源没有这项数据）")
            self.rows[key] = row
            col.addWidget(row)

        # 封面单独一行（走下载，不参与 _DETAIL_FIELDS 的文本写入）
        col.addSpacing(8)
        gl = QLabel("封面")
        gf = gl.font()
        gf.setBold(True)
        gl.setFont(gf)
        col.addWidget(gl)
        cover_url = str(self.detail.get("cover") or "")
        self.cover_row = _PickerRow("cover", "下载封面", cover_url,
                                    available=bool(cover_url),
                                    checked=bool(cover_url),
                                    note="" if cover_url else "（该数据源没有封面）")
        col.addWidget(self.cover_row)

        col.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        mode_row.addWidget(QLabel("已有内容时："))
        self.rb_keep = QRadioButton("只填空缺")
        self.rb_over = QRadioButton("直接覆盖")
        self.rb_keep.setChecked(True)
        self.rb_keep.setToolTip("只写进还空着的栏目，已有的内容一律保留")
        self.rb_over.setToolTip("用新抓到的内容覆盖已有内容")
        mode_row.addWidget(self.rb_keep)
        mode_row.addWidget(self.rb_over)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        all_btn = QPushButton("全选")
        none_btn = QPushButton("全不选")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn.clicked.connect(lambda: self._set_all(False))
        btns.addWidget(all_btn)
        btns.addWidget(none_btn)
        btns.addStretch(1)
        box = QDialogButtonBox()
        ok_btn = box.addButton("填充选中项", QDialogButtonBox.AcceptRole)
        cancel_btn = box.addButton("取消", QDialogButtonBox.RejectRole)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(box)
        root.addLayout(btns)

    # ---------- 交互 ----------
    def _set_all(self, on: bool):
        for row in self.rows.values():
            if row.available:
                row.check.setChecked(on)
        if self.cover_row.available:
            self.cover_row.check.setChecked(on)

    def overwrite_mode(self) -> bool:
        return self.rb_over.isChecked()

    def selection(self) -> dict:
        """{字段 key: 值}，只含被勾选且有内容的项。"""
        out = {}
        for key, row in self.rows.items():
            if not row.is_checked():
                continue
            val = row.selected_value()
            if val is None:
                continue
            out[key] = val
        if self.cover_row.is_checked():
            out["cover"] = str(self.detail.get("cover") or "")
        return out


# ============================================================
# 添加 / 编辑 游戏对话框
# ============================================================
class GameEditDialog(QDialog):
    """用于添加或编辑一款游戏，支持 Bangumi 自动填充。"""

    def __init__(self, db: Database, game_id: int = None, parent=None,
                 save_to_db: bool = True, initial_data: dict = None):
        super().__init__(parent)
        self.db = db
        self.game_id = game_id
        self.save_to_db = save_to_db
        self.initial_data = initial_data
        self.result_data = None
        self.subject = None
        self.downloaded_cover = ""   # 新下载封面的相对路径
        self.original_cover = ""     # 编辑旧封面，保存后若无人引用则清理
        self.search_worker = None
        self.cover_worker = None
        self._phase = "idle"         # idle / searching / filling / ready
        self._searched_title = ""    # 最近一次检索使用的标题
        # 智能填充 / 每栏 🔎 的状态（与上面的「自动填充」完全独立，互不影响）
        self._fill_btns = {}         # {字段 key: 🔎 按钮}
        self.current_detail = None   # 最近一次智能填充/🔎 用的 detail（有缓存就秒填）
        self.current_subject = None  # 对应的搜索结果条目
        self._pending_field = None   # 🔎 正在等检索结果的那个字段
        self._smart_search = None
        self._detail_worker = None
        self._cover_pending = False   # 封面是否正在下载（避免重复触发）
        # 🔎 走缓存时的状态提示：5 秒后自动消失，期间被别的提示覆盖则不误清
        self._hint_text = ""
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._clear_status_if_hint)

        if save_to_db is False and initial_data is not None:
            self.setWindowTitle("%s · 编辑条目（批量预览）" % APP_NAME)
        elif game_id:
            self.setWindowTitle("%s · 编辑游戏" % APP_NAME)
        else:
            self.setWindowTitle("%s · 添加游戏" % APP_NAME)
        self.setMinimumSize(560, 640)
        self._build_ui()
        if initial_data is not None:
            self._prefill_data(initial_data)
        elif game_id:
            self._load_existing(game_id)

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(12)
        outer.addWidget(scroll, 1)

        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        # ===== 基本信息 =====
        base_card = SectionCard("基本信息")
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        base_card.body().addLayout(form)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("例如：CLANNAD")
        self.title_edit.returnPressed.connect(self._on_title_enter)
        self.title_edit.textChanged.connect(self._on_title_changed)
        form.addRow("标题 (*)", self._fill_row(self.title_edit, "title"))

        # 自动填充行（可选择数据源：VNDB 直连 / Bangumi 需梯子）
        self.source_combo = TopComboBox()
        self.source_combo.addItem("VNDB（直连）", "vndb")
        self.source_combo.addItem("Bangumi（需梯子）", "bangumi")
        self.source_combo.addItem("Steam（需梯子）", "steam")
        self.source_combo.setToolTip("选择自动抓取信息的数据库。VNDB 无需梯子，可直连。")
        self.auto_btn = QPushButton("自动填充")
        self.auto_btn.setToolTip("根据上方标题自动抓取信息并下载封面")
        self.auto_btn.clicked.connect(self.on_auto_fill)
        self.auto_label = QLabel("")
        auto_row = QHBoxLayout()
        auto_row.addWidget(self.source_combo)
        auto_row.addWidget(self.auto_btn)
        auto_row.addWidget(self.auto_label, 1)
        form.addRow("自动填充", auto_row)

        # 智能填充：一级选游戏 -> 二级勾字段（复用上面的数据源下拉，不改动「自动填充」）
        self.smart_btn = QPushButton("智能填充")
        self.smart_btn.setToolTip("先搜索并确认游戏，再勾选要把哪些栏目填进去")
        self.smart_btn.clicked.connect(self.on_smart_fill)
        self.smart_label = QLabel("")
        smart_row = QHBoxLayout()
        smart_row.addWidget(self.smart_btn)
        smart_row.addWidget(self.smart_label, 1)
        form.addRow("智能填充", smart_row)

        self.title_jp_edit = QLineEdit()
        form.addRow("原名（日/英）", self._fill_row(self.title_jp_edit, "title_jp"))
        self.developer_edit = QLineEdit()
        form.addRow("开发商", self._fill_row(self.developer_edit, "developer"))
        self.release_edit = QLineEdit()
        self.release_edit.setPlaceholderText("例如：2004-04-28")
        form.addRow("发售日", self._fill_row(self.release_edit, "release_date"))

        self.status_combo = TopComboBox()
        self.status_combo.addItems(STATUS_OPTIONS)
        form.addRow("状态", self.status_combo)

        # ===== 评分与备注（加分制，满分10）=====
        rate_card = SectionCard("评分与备注", hint="加分制，满分 10")
        sc_lay = QGridLayout()
        sc_lay.addWidget(QLabel("剧本与叙事(0-5)"), 0, 0)
        self.story_spin = QDoubleSpinBox()
        self.story_spin.setRange(0, 5)
        self.story_spin.setSingleStep(0.5)
        self.story_spin.setDecimals(1)
        self.story_spin.valueChanged.connect(self._on_score_changed)
        sc_lay.addWidget(self.story_spin, 0, 1)
        sc_lay.addWidget(QLabel("角色塑造(0-3)"), 0, 2)
        self.char_spin = QDoubleSpinBox()
        self.char_spin.setRange(0, 3)
        self.char_spin.setSingleStep(0.5)
        self.char_spin.setDecimals(1)
        self.char_spin.valueChanged.connect(self._on_score_changed)
        sc_lay.addWidget(self.char_spin, 0, 3)
        sc_lay.addWidget(QLabel("视听演出(0-2)"), 0, 4)
        self.audio_spin = QDoubleSpinBox()
        self.audio_spin.setRange(0, 2)
        self.audio_spin.setSingleStep(0.5)
        self.audio_spin.setDecimals(1)
        self.audio_spin.valueChanged.connect(self._on_score_changed)
        sc_lay.addWidget(self.audio_spin, 0, 5)
        self.total_label = QLabel("总分：0 / 10")
        self.total_label.setObjectName("starLabel")
        sc_lay.addWidget(self.total_label, 0, 6)
        sc_lay.addWidget(QLabel("这游戏好在哪（短评）："), 1, 0)
        self.review_edit = QLineEdit()
        self.review_edit.setPlaceholderText("例如：剧情反转超强、音乐封神、人设出彩…")
        sc_lay.addWidget(self.review_edit, 1, 1, 1, 5)
        rate_card.body().addLayout(sc_lay)
        form2 = QFormLayout()
        form2.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.playtime_spin = QSpinBox()
        self.playtime_spin.setRange(0, 99999)
        self.playtime_spin.setSuffix(" 小时")
        form2.addRow("游玩时长", self._fill_row(self.playtime_spin, "play_time"))

        self.cover_preview = QLabel()
        self.cover_preview.setObjectName("coverPreview")
        self.cover_preview.setFixedSize(130, 180)
        self.cover_preview.setAlignment(Qt.AlignCenter)
        self.cover_preview.setPixmap(make_placeholder_pixmap(130, 180, "封面预览"))
        form2.addRow("封面", self.cover_preview)

        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(90)
        form2.addRow("个人备注", self.notes_edit)
        rate_card.body().addLayout(form2)

        # ===== 剧情与制作（字段扩展轮新增）=====
        extra_card = SectionCard("剧情与制作", hint="资料展示页会读取这些内容")
        form3 = QFormLayout()
        form3.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.publisher_edit = QLineEdit()
        form3.addRow("发行商", self._fill_row(self.publisher_edit, "publisher"))
        self.genres_edit = QLineEdit()
        self.genres_edit.setPlaceholderText("多个用逗号分隔，例如：恋爱, 校园, 催泪")
        form3.addRow("类型", self._fill_row(self.genres_edit, "genres"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("多个用逗号分隔，例如：全年龄, 治愈")
        form3.addRow("标签", self._fill_row(self.tags_edit, "tags"))
        self.favorite_check = QCheckBox("加入收藏")
        form3.addRow("收藏", self.favorite_check)
        extra_card.body().addLayout(form3)

        self.summary_edit = QTextEdit()
        self.summary_edit.setFixedHeight(82)
        self.summary_edit.setPlaceholderText("剧情简介…")
        extra_card.body().addWidget(self._text_head("简介", "summary"))
        extra_card.body().addWidget(self.summary_edit)
        self.characters_edit = QTextEdit()
        self.characters_edit.setFixedHeight(64)
        self.characters_edit.setPlaceholderText("每行一个角色，例如：枢都夏莲")
        extra_card.body().addWidget(self._text_head("角色", "characters"))
        extra_card.body().addWidget(self.characters_edit)
        form4 = QFormLayout()
        form4.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.voice_edit = QLineEdit()
        self.voice_edit.setPlaceholderText("多个用逗号分隔，例如：南条爱乃, 中村绘里子")
        form4.addRow("声优", self._fill_row(self.voice_edit, "voices"))
        extra_card.body().addLayout(form4)
        self.staff_edit = QTextEdit()
        self.staff_edit.setFixedHeight(64)
        self.staff_edit.setPlaceholderText("每行一位，例如：原画：X / 音乐：Y")
        extra_card.body().addWidget(self._text_head("制作人员", "staff"))
        extra_card.body().addWidget(self.staff_edit)

        col.addWidget(base_card)
        col.addWidget(rate_card)
        col.addWidget(extra_card)
        col.addStretch(1)

        scroll.setWidget(inner)
        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_btn = btn_box.button(QDialogButtonBox.Save)
        save_btn.setText("保存")
        save_btn.setAutoDefault(False)
        save_btn.setDefault(False)
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)
        outer.addWidget(btn_box)

    def _load_existing(self, game_id: int):
        g = self.db.get_game(game_id)
        if not g:
            return
        self.title_edit.setText(g.get("title", ""))
        self.title_jp_edit.setText(g.get("title_jp", ""))
        self.developer_edit.setText(g.get("developer", ""))
        self.release_edit.setText(g.get("release_date", ""))
        if g.get("status") in STATUS_OPTIONS:
            self.status_combo.setCurrentText(g["status"])
        self._set_dims_score(g)
        self.playtime_spin.setValue(int(g.get("play_time", 0) or 0))
        self.notes_edit.setPlainText(g.get("notes", ""))
        # 字段扩展轮新增内容（老数据取不到时回落到空值）
        self.publisher_edit.setText(str(g.get("publisher", "") or ""))
        self.genres_edit.setText(str(g.get("genres", "") or ""))
        self.tags_edit.setText(str(g.get("tags", "") or ""))
        self.favorite_check.setChecked(bool(g.get("favorite", 0) or 0))
        self.summary_edit.setPlainText(str(g.get("summary", "") or ""))
        self.characters_edit.setPlainText(str(g.get("characters", "") or ""))
        self.voice_edit.setText(str(g.get("voice_actors", "") or ""))
        self.staff_edit.setPlainText(str(g.get("staff", "") or ""))
        if g.get("cover_path"):
            self.downloaded_cover = g["cover_path"]
            self.original_cover = g["cover_path"]
            pix = load_thumb_qpixmap(g["cover_path"], QSize(130, 180))
            self.cover_preview.setPixmap(rounded_pixmap(pix, 10))

    def _prefill_data(self, data: dict):
        """用外部数据（如批量导入的一行）预填表单。"""
        self.title_edit.setText(str(data.get("title", "") or ""))
        self.title_jp_edit.setText(str(data.get("title_jp", "") or ""))
        self.developer_edit.setText(str(data.get("developer", "") or ""))
        self.release_edit.setText(str(data.get("release_date", "") or ""))
        if data.get("status") in STATUS_OPTIONS:
            self.status_combo.setCurrentText(data["status"])
        self._set_dims_score(data)
        self.playtime_spin.setValue(int(float(data.get("play_time", 0) or 0)))
        self.notes_edit.setPlainText(str(data.get("notes", "") or ""))
        self.publisher_edit.setText(str(data.get("publisher", "") or ""))
        self.genres_edit.setText(str(data.get("genres", "") or ""))
        self.tags_edit.setText(str(data.get("tags", "") or ""))
        self.favorite_check.setChecked(bool(data.get("favorite", 0) or 0))
        self.summary_edit.setPlainText(str(data.get("summary", "") or ""))
        self.characters_edit.setPlainText(str(data.get("characters", "") or ""))
        self.voice_edit.setText(str(data.get("voice_actors", "") or ""))
        self.staff_edit.setPlainText(str(data.get("staff", "") or ""))
        cover = data.get("cover") or data.get("cover_path") or ""
        if cover:
            self.downloaded_cover = cover
            self.cover_preview.setPixmap(
                rounded_pixmap(load_thumb_qpixmap(cover, QSize(130, 180)), 10))
        self._phase = "ready"

    def _set_dims_score(self, g: dict):
        """按三维维度填充评分；若老数据只有总评分，则按比例拆成三维避免归零。"""
        story = float(g.get("score_story", 0) or 0)
        char = float(g.get("score_char", 0) or 0)
        audio = float(g.get("score_audio", 0) or 0)
        if story == 0 and char == 0 and audio == 0:
            r = float(g.get("rating", 0) or 0)
            if r > 0:
                story = round(min(5, r * 0.5), 1)
                char = round(min(3, r * 0.3), 1)
                audio = round(min(2, r * 0.2), 1)
        self.story_spin.setValue(story)
        self.char_spin.setValue(char)
        self.audio_spin.setValue(audio)
        self.review_edit.setText(str(g.get("review", "") or ""))
        self._on_score_changed()

    def _on_score_changed(self):
        total = round(self.story_spin.value() + self.char_spin.value()
                      + self.audio_spin.value(), 1)
        self.total_label.setText("总分：%s / 10" % (fmt_rating(total) if total > 0 else "0"))

    # ========================================================
    # 智能填充 / 每栏 🔎（与上面的「自动填充」完全独立）
    # ========================================================

    _FILL_TIP = "从数据源搜索并填充此栏\nShift+点击 = 重新搜索"

    def _make_fill_btn(self, key, tip=None):
        """一个 🔎 按钮：普通点击优先用缓存填，Shift+点击强制重新搜索。"""
        btn = QToolButton()
        btn.setObjectName("fieldFillBtn")
        btn.setText("🔎")
        btn.setToolTip(tip or self._FILL_TIP)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        # 点击瞬间读修饰键：按住 Shift 就跳过缓存
        btn.clicked.connect(
            lambda _=False, k=key: self.on_field_fill(k, force=_shift_held()))
        self._fill_btns[key] = btn
        return btn

    def _fill_row(self, edit, key, tip=None):
        """把输入框包一层：输入框 + 右侧 🔎 按钮。"""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(edit, 1)
        lay.addWidget(self._make_fill_btn(key, tip), 0)
        return box

    def _text_head(self, title, key, hint=""):
        """给 QTextEdit 这类块级字段做一个「标题 + 🔎」的头。"""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(QLabel(title))
        if hint:
            hl = QLabel(hint)
            hl.setObjectName("hint")
            lay.addWidget(hl)
        lay.addStretch(1)
        lay.addWidget(self._make_fill_btn(key))
        return box

    def _source_name(self, source) -> str:
        return {"vndb": "VNDB", "bangumi": "Bangumi", "steam": "Steam"}.get(
            str(source or "").lower(), str(source or ""))

    def _make_search_worker(self, keyword, source):
        if source == "vndb":
            return VndbSearchWorker(keyword, None)
        if source == "steam":
            return SteamSearchWorker(keyword, None)
        return BangumiSearchWorker(keyword, None)

    def _detail_supported(self) -> bool:
        return self.source_combo.currentData() in ("vndb", "bangumi")

    # ---------- 一级：搜索 ----------

    def on_smart_fill(self):
        """智能填充：搜索 -> 选条目 -> 抓详情 -> 二级菜单勾字段。"""
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "提示", "请先在“标题”框中输入要搜索的游戏名。")
            return
        if not self._detail_supported():
            QMessageBox.information(
                self, "提示",
                "「智能填充」目前支持 VNDB 与 Bangumi，请先把数据源切到这两个之一。\n\n"
                "（Steam 只有基础信息，用原来的「自动填充」即可。）")
            return
        source = self.source_combo.currentData()
        self.smart_btn.setEnabled(False)
        self.smart_label.setText("正在%s搜索…" % self._source_name(source))
        self._pending_field = None
        self._smart_search = self._make_search_worker(title, source)
        self._smart_search.finished_ok.connect(self._on_smart_search_done)
        self._smart_search.failed.connect(self._on_smart_search_fail)
        _orphan_worker(self._smart_search)
        self._smart_search.start()

    def _on_smart_search_fail(self, msg: str):
        self.smart_btn.setEnabled(True)
        self.smart_label.setText("")
        QMessageBox.warning(self, "网络错误", "搜索失败，请检查网络后重试。\n\n详情：%s" % msg)

    def _on_smart_search_done(self, results: list):
        self.smart_btn.setEnabled(True)
        self.smart_label.setText("")
        if not results:
            QMessageBox.information(self, "提示", "未找到相关游戏，请检查标题或切换数据源。")
            return
        dlg = SubjectSelectDialog(results, self)
        if not dlg.exec() or not dlg.selected:
            return
        self.current_subject = dlg.selected
        self._fetch_detail(dlg.selected, self._open_field_picker)

    # ---------- 详情（带缓存） ----------

    def _fetch_detail(self, sub: dict, callback):
        """取 detail：缓存命中直接回调，否则后台抓取（不卡界面）。"""
        source = str(sub.get("source") or self.source_combo.currentData() or "").lower()
        sid = sub.get("id")
        cached = net.peek_detail(source, sid)
        if cached is not None:
            callback(cached)
            return
        self.smart_label.setText("正在读取 %s 详情…" % self._source_name(source))
        self._detail_worker = DetailFetchWorker(source, sid, None)

        def _ok(detail):
            self.smart_label.setText("")
            callback(detail)

        self._detail_worker.done.connect(_ok)
        self._detail_worker.failed.connect(self._on_detail_fail)
        _orphan_worker(self._detail_worker)
        self._detail_worker.start()

    def _on_detail_fail(self, msg: str):
        self.smart_btn.setEnabled(True)
        self.smart_label.setText("")
        QMessageBox.warning(self, "读取详情失败",
                            "没能拿到该条目的详情，换个数据源或稍后重试。\n\n详情：%s" % msg)

    # ---------- 二级：勾字段 ----------

    def _open_field_picker(self, detail: dict):
        self.current_detail = detail
        dlg = FieldPickerDialog(detail, self)
        if not dlg.exec():
            return
        sel = dlg.selection()
        if not sel:
            QMessageBox.information(self, "提示", "没有勾选任何要填充的内容。")
            return
        n = self._apply_detail_fields(sel, overwrite=dlg.overwrite_mode())
        if n:
            self._phase = "ready"
            self.smart_label.setText("已填充 %d 个栏目" % n)
        else:
            self.smart_label.setText("没有可填的内容")
            QMessageBox.information(
                self, "提示",
                "勾选的栏目都已有内容，没有改动。\n\n"
                "想覆盖的话，在二级菜单里选「直接覆盖」再试一次。")

    # ---------- 写入表单 ----------

    def _get_field_ctrl(self, key: str):
        attr = _DETAIL_ATTR.get(key)
        return getattr(self, attr, None) if attr else None

    def _field_is_empty(self, key: str) -> bool:
        if key == "play_time":
            return self.playtime_spin.value() <= 0
        ctrl = self._get_field_ctrl(key)
        if ctrl is None:
            return True
        if isinstance(ctrl, QTextEdit):
            return not ctrl.toPlainText().strip()
        if isinstance(ctrl, QSpinBox):
            return ctrl.value() <= 0
        return not str(ctrl.text()).strip()

    def _field_current_text(self, key: str) -> str:
        if key == "play_time":
            return str(self.playtime_spin.value())
        ctrl = self._get_field_ctrl(key)
        if ctrl is None:
            return ""
        if isinstance(ctrl, QTextEdit):
            return ctrl.toPlainText()
        if isinstance(ctrl, QSpinBox):
            return str(ctrl.value())
        return str(ctrl.text())

    @staticmethod
    def _value_to_text(key: str, value) -> str:
        if key in ("characters", "staff"):
            return "\n".join(str(v).strip() for v in (value or []) if str(v or "").strip())
        if key in ("genres", "tags", "voices"):
            return ", ".join(str(v).strip() for v in (value or []) if str(v or "").strip())
        if key == "play_time":
            try:
                return str(int(value or 0))
            except (TypeError, ValueError):
                return "0"
        return str(value or "").strip()

    def _has_cover(self) -> bool:
        # 下载中也要算“已有”，否则「只填空缺」会重复触发封面下载
        return bool(self.downloaded_cover or self.original_cover or self._cover_pending)

    def _write_field(self, key: str, value) -> bool:
        """把值写进对应控件。写不动（空值/控件不存在）返回 False。"""
        ctrl = self._get_field_ctrl(key)
        if ctrl is None:
            return False
        try:
            if key in ("characters", "staff"):
                vals = [str(v).strip() for v in (value or []) if str(v or "").strip()]
                if not vals:
                    return False
                ctrl.setPlainText("\n".join(vals))
            elif key in ("genres", "tags", "voices"):
                vals = [str(v).strip() for v in (value or []) if str(v or "").strip()]
                if not vals:
                    return False
                ctrl.setText(", ".join(vals))
            elif key == "play_time":
                n = int(value or 0)
                if n <= 0:
                    return False
                ctrl.setValue(min(n, ctrl.maximum()))
            elif isinstance(ctrl, QTextEdit):
                text = str(value or "").strip()
                if not text:
                    return False
                ctrl.setPlainText(text)
            else:
                text = str(value or "").strip()
                if not text:
                    return False
                ctrl.setText(text)
        except Exception:
            return False
        return True

    def _apply_detail_fields(self, selection: dict, overwrite: bool = False) -> int:
        """把选中的字段写进表单；overwrite=False 时只填空缺。返回写入的栏目数。"""
        written = 0
        for key, value in (selection or {}).items():
            if key == "cover":
                if not value:
                    continue
                if not overwrite and self._has_cover():
                    continue
                self._download_detail_cover(value)
                written += 1
                continue
            if not overwrite and not self._field_is_empty(key):
                continue
            if self._write_field(key, value):
                written += 1
        return written

    def _download_detail_cover(self, url: str):
        self._cover_pending = True
        self.cover_worker = CoverDownloadWorker(url, None, None)
        self.cover_worker.done.connect(self._on_cover_done)
        self.cover_worker.failed.connect(self._on_cover_fail)
        # 线程结束（无论成败）都要清掉“下载中”标记
        self.cover_worker.finished.connect(
            lambda: setattr(self, "_cover_pending", False))
        _orphan_worker(self.cover_worker)
        self.cover_worker.start()

    # ---------- 每栏 🔎 ----------

    def _cached_detail(self):
        """当前表单关联的 detail；只按 (数据源, 条目 id) 认定是不是同一个游戏。

        标题文本不参与判定 —— 改空格、加「汉化版」、换译名都不会让缓存失效。
        想换游戏：用「智能填充」重搜，或 Shift+点击任意 🔎 强制重新搜索。
        """
        d = self.current_detail
        if not d:
            return None
        src = str(d.get("source") or "").strip().lower()
        sid = str(d.get("id") or "").strip()
        if not src or not sid:
            return None      # 关联不完整，当作没有缓存
        cur_src = str(self.source_combo.currentData() or "").strip().lower()
        if cur_src and src != cur_src:
            return None      # 数据源已被切走（例如切到 Steam），旧关联作废
        return net.peek_detail(src, sid) or d

    # ---------- 状态栏提示 ----------

    def _show_cache_hint(self, detail: dict):
        """走了缓存填栏时，在状态栏提醒用的是上次关联的条目。"""
        title = str((detail or {}).get("title")
                    or (detail or {}).get("title_jp") or "").strip()
        text = "已使用上次关联的条目《%s》· Shift+点 🔎 可重新搜索" % title
        self._hint_text = text
        self.smart_label.setText(text)
        self.smart_label.setToolTip(text)   # 超长标题被截断时可悬停看全
        self._status_timer.start(5000)   # 5 秒后自动消失

    def _clear_status_if_hint(self):
        """只在状态栏还显示着这条提示时才清空，避免误清掉后面的新提示。"""
        if self._hint_text and self.smart_label.text() == self._hint_text:
            self.smart_label.setText("")
            self.smart_label.setToolTip("")

    def _info_and_clear(self, text: str, warn: bool = False):
        """弹提示前先清掉状态栏里残留的缓存提示。

        弹窗分支不接管状态栏：如果上一次 🔎 留下的「已使用上次关联…」还在，
        用户会误以为这次操作也走了缓存，所以所有弹窗分支统一在这里先清干净。
        warn=True 时用警告图标（例如「请先输入游戏名」）。
        """
        self._clear_status_if_hint()
        if warn:
            QMessageBox.warning(self, "提示", text)
        else:
            QMessageBox.information(self, "提示", text)

    def on_field_fill(self, key: str, force: bool = False):
        """🔎：有缓存就直接填这一栏；没有就搜索 -> 抓详情 -> 填这一栏。

        判定顺序（固定，不要随意调换）：
          1. 该源结构上没有这一栏 -> 直接提示（与缓存无关，不走缓存、也不发状态提示）
          2. 缓存命中 -> 直接填 + 状态栏提示
          3. 数据源不支持 -> 提示
          4. 标题为空 -> 提示
          5. 联网搜索
        force=True（Shift+点击）只跳过第 2 步。
        """
        source = str(self.source_combo.currentData() or "").lower()

        # 1) 该源永远没有这一栏：跟缓存无关，先拦掉；不触发搜索、也不发状态提示
        if key in _SOURCE_NO_FIELD.get(source, ()):
            self._info_and_clear("%s 没有「%s」这项数据。" % (
                self._source_name(source), _DETAIL_LABEL.get(key, key)))
            return

        # 2) 缓存命中：填这一栏，并在状态栏说明用的是上次关联的条目
        cached = None if force else self._cached_detail()
        if cached is not None:
            self._fill_one_field(key, cached)
            self._show_cache_hint(cached)
            return

        # 3) 该数据源不支持详情抓取（例如 Steam）
        if not self._detail_supported():
            self._info_and_clear("该功能目前支持 VNDB 与 Bangumi，请先切换数据源。")
            return
        title = self.title_edit.text().strip()
        if not title:
            self._info_and_clear("请先在“标题”框中输入要搜索的游戏名。", warn=True)
            return

        self._pending_field = key
        self.smart_btn.setEnabled(False)
        self.smart_label.setText("正在%s搜索…" % self._source_name(source))
        self._smart_search = self._make_search_worker(title, source)
        self._smart_search.finished_ok.connect(self._on_field_search_done)
        self._smart_search.failed.connect(self._on_smart_search_fail)
        _orphan_worker(self._smart_search)
        self._smart_search.start()

    def _on_field_search_done(self, results: list):
        self.smart_btn.setEnabled(True)
        self.smart_label.setText("")
        key = self._pending_field
        if not results:
            QMessageBox.information(self, "提示", "未找到相关游戏，请检查标题或切换数据源。")
            return
        dlg = SubjectSelectDialog(results, self)
        if not dlg.exec() or not dlg.selected:
            return
        self.current_subject = dlg.selected
        self._fetch_detail(dlg.selected, lambda d: self._fill_one_field(key, d))

    def _fill_one_field(self, key: str, detail: dict):
        """把 detail 里的某一栏写进表单（🔎 专用，不做「只填空缺」判断）。"""
        self.current_detail = detail
        if not key:
            return
        value = _detail_value(detail, key)
        items = _detail_items(detail, key)
        if items:
            value = [it["value"] for it in items]
        label = _DETAIL_LABEL.get(key, key)
        src_name = self._source_name(detail.get("source"))

        if key == "play_time":
            if not value:
                QMessageBox.information(self, "提示", "%s 没有游玩时长。" % src_name)
                return
        elif not value:
            QMessageBox.information(self, "提示", "%s 没有「%s」这项数据。" % (src_name, label))
            return

        new_text = self._value_to_text(key, value)
        cur_text = self._field_current_text(key).strip()
        if cur_text and cur_text != new_text.strip():
            if not ask_yes_no(self, "覆盖「%s」？" % label,
                              "这一栏已经有内容了：\n\n%s\n\n要换成：\n\n%s" % (
                                  cur_text[:300], new_text[:300])):
                return
        if self._write_field(key, value):
            self._phase = "ready"
            self.smart_label.setText("已填充「%s」" % label)
        else:
            self.smart_label.setText("「%s」没有可写的内容" % label)

    def on_auto_fill(self):
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "提示", "请先在“标题”框中输入要搜索的游戏名。")
            return
        self._phase = "searching"
        self._searched_title = title
        source = self.source_combo.currentData()
        src_name = {"vndb": "VNDB", "steam": "Steam", "bangumi": "Bangumi"}.get(source, source)
        self.auto_btn.setEnabled(False)
        self.auto_label.setText("正在%s搜索…" % src_name)
        if source == "steam":
            self.search_worker = SteamSearchWorker(title, None)
        elif source == "vndb":
            self.search_worker = VndbSearchWorker(title, None)
        else:
            self.search_worker = BangumiSearchWorker(title, None)
        self.search_worker.finished_ok.connect(self._on_search_done)
        self.search_worker.failed.connect(self._on_search_fail)
        _orphan_worker(self.search_worker)
        self.search_worker.start()

    def _on_title_enter(self):
        """第一次回车检索，检索完成后第二次回车才保存。"""
        if self._phase == "ready":
            self._save()
        elif self._phase == "idle":
            self.on_auto_fill()
        # searching / filling 阶段：忽略回车，等待检索完成

    def _on_title_changed(self, text):
        # 完成填充后保持“可保存”状态，回车直接保存；想重新识别请点“自动填充”
        pass

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._on_title_enter()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_search_done(self, results: list):
        self.auto_btn.setEnabled(True)
        if not results:
            self.auto_label.setText("")
            self._phase = "idle"
            if self.source_combo.currentData() == "steam":
                QMessageBox.information(
                    self, "提示",
                    "Steam 未搜到该游戏（中文/英文名都试过了）。\n\n"
                    "可能该游戏不在 Steam，或名字差异较大。可尝试输入 Steam 上的官方名，"
                    "或切换到 VNDB 搜索。")
            else:
                QMessageBox.information(self, "提示",
                                        "未找到相关游戏，请检查标题，或切换数据源重试。")
            return
        dlg = SubjectSelectDialog(results, self)
        if dlg.exec() and dlg.selected:
            self.subject = dlg.selected
            self._fill_from_subject(self.subject)
        else:
            self._phase = "idle"

    def _on_search_fail(self, msg: str):
        self.auto_btn.setEnabled(True)
        self.auto_label.setText("")
        self._phase = "idle"
        QMessageBox.warning(self, "网络错误",
                            "自动填充失败，请检查网络连接，或切换数据源重试。\n\n详情：%s" % msg)

    def _fill_from_subject(self, sub: dict):
        # 标题：中文优先，无中文则回退到日语原名
        title_val = sub.get("name_cn") or sub.get("name") or ""
        if title_val:
            self.title_edit.setText(title_val)
        self.title_jp_edit.setText(sub.get("name", ""))
        self.developer_edit.setText(sub.get("developer", ""))
        self.release_edit.setText(sub.get("date", ""))
        # 下载封面
        if sub.get("cover"):
            self._phase = "filling"
            self.auto_label.setText("下载封面中…")
            self.cover_worker = CoverDownloadWorker(sub["cover"], sub.get("id"), None)
            self.cover_worker.done.connect(self._on_cover_done)
            self.cover_worker.failed.connect(self._on_cover_fail)
            _orphan_worker(self.cover_worker)
            self.cover_worker.start()
        else:
            self._phase = "ready"
            self.auto_label.setText("未找到封面链接")

    def _on_cover_done(self, rel_path: str, _abs_path: str):
        self._phase = "ready"
        self.auto_label.setText("封面已下载")
        self.downloaded_cover = rel_path
        self.cover_preview.setPixmap(
            rounded_pixmap(load_thumb_qpixmap(rel_path, QSize(130, 180)), 10))

    def _on_cover_fail(self, msg: str):
        self._phase = "ready"
        self.auto_label.setText("封面下载失败")
        QMessageBox.warning(self, "封面下载失败",
                            "封面未能下载，其余信息已填写。\n\n详情：%s" % msg)

    def _save(self):
        if self._phase == "saving":
            return
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "提示", "标题不能为空。")
            return
        total = round(self.story_spin.value() + self.char_spin.value()
                      + self.audio_spin.value(), 1)
        data = {
            "title": title,
            "title_jp": self.title_jp_edit.text().strip(),
            "developer": self.developer_edit.text().strip(),
            "release_date": self.release_edit.text().strip(),
            "status": self.status_combo.currentText(),
            "rating": total,
            "score_story": self.story_spin.value(),
            "score_char": self.char_spin.value(),
            "score_audio": self.audio_spin.value(),
            "review": self.review_edit.text().strip(),
            "play_time": self.playtime_spin.value(),
            "cover_path": self.downloaded_cover,
            "notes": self.notes_edit.toPlainText().strip(),
            # 字段扩展轮新增
            "favorite": 1 if self.favorite_check.isChecked() else 0,
            "publisher": self.publisher_edit.text().strip(),
            "genres": self.genres_edit.text().strip(),
            "tags": self.tags_edit.text().strip(),
            "summary": self.summary_edit.toPlainText().strip(),
            "characters": self.characters_edit.toPlainText().strip(),
            "voice_actors": self.voice_edit.text().strip(),
            "staff": self.staff_edit.toPlainText().strip(),
        }
        try:
            if not self.save_to_db:
                self.result_data = data
            else:
                if self.game_id:
                    self.db.update_game(self.game_id, data)
                    if self.original_cover and self.original_cover != self.downloaded_cover:
                        delete_cover_if_unused(self.db, self.original_cover)
                else:
                    self.game_id = self.db.add_game(data)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", "写入数据库失败：\n%s" % exc)
            return
        self._phase = "saving"
        self.accept()


# ============================================================
# 游戏详情对话框
# ============================================================
class GameDetailDialog(QDialog):
    """展示游戏信息，并提供截图管理功能。"""

    def __init__(self, db: Database, game_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.game_id = game_id
        self.import_worker = None
        self.setWindowTitle("%s · 游戏详情" % APP_NAME)
        self.setMinimumSize(920, 780)
        self.setAcceptDrops(True)
        self._build_ui()
        self._load_info()
        self._load_scores()
        self._reload_screenshots()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # 整页可滚动：内容比窗口高时滚动，而不是把某一张卡片（尤其截图条）挤扁裁切
        self._scroll = QScrollArea()
        self._scroll.setObjectName("detailScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("detailBody")
        self._scroll.setWidget(container)
        outer.addWidget(self._scroll, 1)
        lay = QVBoxLayout(container)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(12)

        # ---- 资料卡：左侧大封面 + 右侧名称 / 状态 / 评分 / 资料 ----
        info_box = QFrame()
        info_box.setObjectName("heroCard")
        info_lay = QHBoxLayout(info_box)
        info_lay.setContentsMargins(18, 18, 18, 18)
        info_lay.setSpacing(18)
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(220, 320)
        self.cover_lbl.setAlignment(Qt.AlignCenter)
        info_lay.addWidget(self.cover_lbl, 0, Qt.AlignTop)

        info_col = QVBoxLayout()
        info_col.setSpacing(10)
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self.status_chip = chip_label("—")
        self.rating_chip = chip_label("未评分")
        self.fav_chip = chip_label("♥ 已收藏", accent_color())
        chip_row.addWidget(self.status_chip)
        chip_row.addWidget(self.rating_chip)
        chip_row.addWidget(self.fav_chip)
        chip_row.addStretch(1)
        info_col.addLayout(chip_row)

        # 类型 / 标签 胶囊（读取时动态生成）
        # 必须用会换行的流式布局：QHBoxLayout 的最小宽度 = 所有胶囊宽度之和，
        # 标签一多就会把整页撑得比窗口还宽，截图区会连带变成超宽的一行。
        self.tag_row = FlowLayout(spacing=6)
        info_col.addLayout(self.tag_row)

        self.info_holder = QLabel()
        self.info_holder.setWordWrap(True)
        self.info_holder.setTextFormat(Qt.RichText)
        self.info_holder.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        info_col.addWidget(self.info_holder, 1)

        info_lay.addLayout(info_col, 1)
        lay.addWidget(info_box)

        # ---- 操作按钮 ----
        btn_row = QHBoxLayout()
        self.edit_btn = QPushButton("编辑信息")
        self.edit_btn.clicked.connect(self.on_edit)
        self.cover_btn = QPushButton("更换封面")
        self.cover_btn.clicked.connect(self.on_change_cover)
        self.delete_btn = QPushButton("删除游戏")
        self.delete_btn.setObjectName("dangerItem")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self.on_delete_game)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.cover_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.delete_btn)
        lay.addLayout(btn_row)

        # ---- 评分维度区 ----
        self.score_box = SectionCard("评分维度", hint="加分制，满分 10")
        sc_lay = QGridLayout()
        sc_lay.addWidget(QLabel("剧本与叙事(0-5)"), 0, 0)
        self.story_spin = QDoubleSpinBox()
        self.story_spin.setRange(0, 5)
        self.story_spin.setSingleStep(0.5)
        self.story_spin.setDecimals(1)
        self.story_spin.valueChanged.connect(self._on_score_changed)
        sc_lay.addWidget(self.story_spin, 0, 1)
        sc_lay.addWidget(QLabel("角色塑造(0-3)"), 0, 2)
        self.char_spin = QDoubleSpinBox()
        self.char_spin.setRange(0, 3)
        self.char_spin.setSingleStep(0.5)
        self.char_spin.setDecimals(1)
        self.char_spin.valueChanged.connect(self._on_score_changed)
        sc_lay.addWidget(self.char_spin, 0, 3)
        sc_lay.addWidget(QLabel("视听演出(0-2)"), 0, 4)
        self.audio_spin = QDoubleSpinBox()
        self.audio_spin.setRange(0, 2)
        self.audio_spin.setSingleStep(0.5)
        self.audio_spin.setDecimals(1)
        self.audio_spin.valueChanged.connect(self._on_score_changed)
        sc_lay.addWidget(self.audio_spin, 0, 5)
        self.total_label = QLabel("总分：0 / 10")
        self.total_label.setObjectName("starLabel")
        sc_lay.addWidget(self.total_label, 0, 6)
        sc_lay.addWidget(QLabel("这游戏好在哪（短评）："), 1, 0)
        self.review_edit = QLineEdit()
        self.review_edit.setPlaceholderText("例如：剧情反转超强、音乐封神、人设出彩…")
        sc_lay.addWidget(self.review_edit, 1, 1, 1, 5)
        save_score_btn = QPushButton("保存评分")
        save_score_btn.clicked.connect(self._on_save_scores)
        sc_lay.addWidget(save_score_btn, 1, 6)
        self.score_box.body().addLayout(sc_lay)
        lay.addWidget(self.score_box)

        # ---- 截图管理区 ----
        # 自动换行排布：行数由 _fit_ss_height() 按【列表自身宽度】算 ——
        #   行数 ≤ SS_MAX_ROWS → 整块显示、由整页滚动；
        #   行数 > SS_MAX_ROWS → 高度封顶，这一块自己带竖向滚动条。
        self.ss_card = SectionCard("截图管理", hint="支持拖拽图片导入")
        upload_row = QHBoxLayout()
        self.upload_btn = QPushButton("上传截图")
        self.upload_btn.clicked.connect(self.on_upload)
        upload_row.addWidget(self.upload_btn)
        upload_row.addWidget(QLabel("按分类筛选："))
        self.filter_combo = TopComboBox()
        self.filter_combo.addItem("全部", None)
        for c in CATEGORY_OPTIONS:
            self.filter_combo.addItem(c, c)
        self.filter_combo.currentIndexChanged.connect(self._reload_screenshots)
        upload_row.addWidget(self.filter_combo)
        upload_row.addStretch(1)
        self.ss_card.body().addLayout(upload_row)

        shot_w = 144                                  # 缩略图展示宽（CG 基本是 16:9）
        shot_h = int(round(shot_w * 9 / 16.0))        # 144 -> 81
        self.ss_item_w = shot_w + 8
        self.ss_item_h = shot_h + 30                  # 画面 + 一行字幕
        self.ss_list = QListWidget()
        self.ss_list.setObjectName("ssGrid")
        self.ss_list.setViewMode(QListView.IconMode)
        self.ss_list.setFlow(QListView.LeftToRight)
        self.ss_list.setWrapping(True)                # 自动换行
        self.ss_list.setResizeMode(QListView.Adjust)  # 窗口变宽/变窄时重排
        self.ss_list.setIconSize(QSize(shot_w, shot_h))
        self.ss_list.setGridSize(QSize(self.ss_item_w, self.ss_item_h))
        self.ss_list.setSpacing(4)
        self.ss_list.setMovement(QListView.Static)
        self.ss_list.setUniformItemSizes(True)
        self.ss_list.setWordWrap(False)
        self.ss_list.setTextElideMode(Qt.ElideRight)
        # 高度由 _fit_ss_height() 算好：行数不超上限时不出滚动条（整页滚动），
        # 截图特别多、超过上限时高度封顶，让这一块出现自己的竖向滚动条
        self.ss_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.ss_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.ss_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ss_list.customContextMenuRequested.connect(self._show_ss_menu)
        self.ss_list.itemDoubleClicked.connect(self._open_screenshot)
        self.ss_card.body().addWidget(self.ss_list)

        self.ss_empty_lbl = QLabel("还没有截图 —— 点上面的「上传截图」，或直接把图片拖进这个窗口")
        self.ss_empty_lbl.setObjectName("ssEmpty")
        self.ss_empty_lbl.setAlignment(Qt.AlignCenter)
        self.ss_card.body().addWidget(self.ss_empty_lbl)
        lay.addWidget(self.ss_card)

        # ---- 剧情与制作（字段扩展轮新增内容）----
        self.extra_card = SectionCard("剧情与制作")
        extra_grid = QFormLayout()
        extra_grid.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.summary_lbl = QLabel("—")
        self.summary_lbl.setWordWrap(True)
        self.characters_lbl = QLabel("—")
        self.characters_lbl.setWordWrap(True)
        self.voice_lbl = QLabel("—")
        self.voice_lbl.setWordWrap(True)
        self.staff_lbl = QLabel("—")
        self.staff_lbl.setWordWrap(True)
        for lbl in (self.summary_lbl, self.characters_lbl, self.voice_lbl, self.staff_lbl):
            lbl.setObjectName("kvValue")
        extra_grid.addRow("简介", self.summary_lbl)
        extra_grid.addRow("角色", self.characters_lbl)
        extra_grid.addRow("声优", self.voice_lbl)
        extra_grid.addRow("制作人员", self.staff_lbl)
        self.extra_card.body().addLayout(extra_grid)
        # 放在"评分维度"之前：资料 → 剧情与制作 → 评分 → 截图
        lay.insertWidget(lay.indexOf(self.score_box), self.extra_card)

    def _load_info(self):
        g = self.db.get_game(self.game_id)
        if not g:
            return
        if g.get("cover_path"):
            self.cover_lbl.setPixmap(rounded_cover_pixmap(g["cover_path"], 220, 320, 14))
        else:
            self.cover_lbl.setPixmap(
                rounded_pixmap(make_placeholder_pixmap(220, 320, "无封面"), 14))
        rating = float(g.get("rating", 0) or 0)
        # 顶部胶囊：状态 + 评分（只读展示）
        status = str(g.get("status", "") or "")
        self.status_chip.setText(status or "—")
        set_chip_color(self.status_chip, status_color(status) if status else "")
        if rating > 0:
            self.rating_chip.setText("★ %s" % fmt_rating(rating))
            set_chip_color(self.rating_chip, accent_color())
        else:
            self.rating_chip.setText("未评分")
            set_chip_color(self.rating_chip, "")
        self.fav_chip.setVisible(bool(g.get("favorite", 0) or 0))
        # 类型 / 标签 胶囊：每次刷新重建
        while self.tag_row.count():
            it = self.tag_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
        for text in _split_list(g.get("genres")) + _split_list(g.get("tags")):
            self.tag_row.addWidget(chip_label(text))
        # 剧情与制作
        self.summary_lbl.setText(str(g.get("summary", "") or "").strip() or "—")
        self.characters_lbl.setText(str(g.get("characters", "") or "").strip() or "—")
        self.voice_lbl.setText(str(g.get("voice_actors", "") or "").strip() or "—")
        self.staff_lbl.setText(str(g.get("staff", "") or "").strip() or "—")
        rating_text = (fmt_rating(rating) + " / 10") if rating > 0 else "未评分"
        stars = "★" * int(rating) if rating > 0 else ""
        html = (
            f"<h2>{_esc(g.get('title',''))}</h2>"
            f"<p><b>原名（日/英）：</b>{_esc(g.get('title_jp','')) or '—'}</p>"
            f"<p><b>开发商：</b>{_esc(g.get('developer','')) or '—'}</p>"
            f"<p><b>发售日：</b>{_esc(g.get('release_date','')) or '—'}</p>"
            f"<p><b>状态：</b>{_esc(g.get('status','')) or '—'}</p>"
            f"<p><b>评分：</b>{rating_text} {stars}</p>"
            f"<p><b>游玩时长：</b>{int(g.get('play_time',0) or 0)} 小时</p>"
            f"<p><b>备注：</b>{_esc(g.get('notes','')) or '—'}</p>"
            f"<p><b>短评：</b>{_esc(g.get('review','')) or '—'}</p>"
        )
        self.info_holder.setText(html)

    def on_edit(self):
        dlg = GameEditDialog(self.db, self.game_id, self)
        if dlg.exec():
            self._load_info()
            self._load_scores()

    def _load_scores(self):
        g = self.db.get_game(self.game_id)
        if not g:
            return
        self.story_spin.setValue(float(g.get("score_story", 0) or 0))
        self.char_spin.setValue(float(g.get("score_char", 0) or 0))
        self.audio_spin.setValue(float(g.get("score_audio", 0) or 0))
        self.review_edit.setText(g.get("review", "") or "")
        self._on_score_changed()

    def _on_score_changed(self):
        total = round(self.story_spin.value() + self.char_spin.value()
                      + self.audio_spin.value(), 1)
        self.total_label.setText("总分：%s / 10" % (fmt_rating(total) if total > 0 else "0"))
        self._total = total

    def _on_save_scores(self):
        total = round(self.story_spin.value() + self.char_spin.value()
                      + self.audio_spin.value(), 1)
        try:
            self.db.update_scores(
                self.game_id, self.story_spin.value(), self.char_spin.value(),
                self.audio_spin.value(), self.review_edit.text().strip(), total)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", "写入评分失败：\n%s" % exc)
            return
        self._load_info()
        QMessageBox.information(self, "完成", "评分已保存。")

    def on_change_cover(self):
        g = self.db.get_game(self.game_id)
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
                self.db.update_cover(self.game_id, dlg.selected_cover)
            except Exception as exc:
                QMessageBox.critical(self, "保存失败", "写入封面失败：\n%s" % exc)
                return
            # 旧封面无人引用时才删；共享封面（内容去重后）保留
            if old and old != dlg.selected_cover:
                delete_cover_if_unused(self.db, old)
            self._load_info()

    def on_delete_game(self):
        if not ask_yes_no(self, "删除游戏",
                          "确定要删除这款游戏吗？其截图记录与本地文件也会一并清理。"):
            return
        try:
            delete_game_and_files(self.db, self.game_id)
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self.accept()

    # ---------- 截图操作 ----------
    def on_upload(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择截图（可多选）", "",
            "图片文件 (*.jpg *.jpeg *.png *.gif *.bmp *.webp)")
        if not files:
            return
        self._upload_files(list(files))

    def _upload_files(self, files):
        if not files:
            return
        cat_dlg = CategoryDialog(files, self)
        if not cat_dlg.exec():
            return
        categories = cat_dlg.get_categories()
        pairs = list(zip(files, categories))

        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("导入中…")
        # 传给导入线程：图片会存到 <CG_ROOT>/<分类>/<游戏名>/ 下
        game = {}
        try:
            game = self.db.get_game(self.game_id) or {}
        except Exception:
            game = {}
        game_name = str(game.get("title") or "")
        self.import_worker = ScreenshotImportWorker(
            self.game_id, pairs, self, game_name=game_name)
        self.import_worker.finished.connect(self._on_import_done)
        self.import_worker.failed.connect(self._on_import_fail)
        self.import_worker.start()

    @staticmethod
    def _is_image_file(path):
        return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
                u.isLocalFile() and self._is_image_file(u.toLocalFile())
                for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = []
        for u in event.mimeData().urls():
            if u.isLocalFile():
                p = u.toLocalFile()
                if self._is_image_file(p):
                    files.append(p)
        if files:
            self._upload_files(files)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_import_done(self, results: list):
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("上传截图")
        try:
            for r in results:
                self.db.add_screenshot(
                    self.game_id, r["rel_path"], r["category"], r["upload_time"])
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", "写入截图记录失败：\n%s" % exc)
        self._reload_screenshots()
        QMessageBox.information(self, "完成", "已成功导入 %d 张截图。" % len(results))

    def _on_import_fail(self, msg: str):
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("上传截图")
        QMessageBox.warning(self, "导入失败", "截图导入失败：\n%s" % msg)

    def _reload_screenshots(self):
        category = self.filter_combo.currentData()
        rows = self.db.get_screenshots(self.game_id, category)
        self.ss_list.clear()
        size = QSize(self.ss_list.iconSize())
        for row in rows:
            pix = load_thumb_qpixmap(row["file_path"], size)
            item = QListWidgetItem(QIcon(pix), "")
            item.setData(Qt.UserRole, row["id"])
            up = str(row.get("upload_time") or "")
            short = up[5:16] if len(up) >= 16 else up      # 2026-09-09 13:11:26 -> 09-09 13:11
            cap = " · ".join([x for x in (str(row.get("category") or ""), short) if x])
            item.setText(cap or "截图")
            item.setToolTip(to_abs(row["file_path"]))
            self.ss_list.addItem(item)
        # 有截图时显示缩略图网格，没有时显示提示（不再是一块空的黑框）
        n = len(rows)
        self.ss_list.setVisible(n > 0)
        if getattr(self, "ss_empty_lbl", None) is not None:
            self.ss_empty_lbl.setVisible(n == 0)
        if getattr(self, "ss_card", None) is not None:
            self.ss_card.set_hint("共 %d 张 · 支持拖拽导入" % n if n
                                  else "支持拖拽图片导入")
        self._fit_ss_height()

    SS_MAX_ROWS = 3          # 截图区最多直接显示几行；超出则由这一块自己出竖向滚动条

    def _fit_ss_height(self):
        """按【截图列表自身的宽度】算每行几张，再把高度设成 min(行数, SS_MAX_ROWS) 行。

        为什么不按窗口宽度算：列表宽度还受页面边距、卡片内边距、页面滚动条，
        以及同页其它控件（例如标签行有多宽）影响，和窗口宽度并不相等。
        以前用 self.width() 估算，页面一被撑宽/收窄就会算错行数 ——
        轻则留白，重则截图被裁掉或只剩一行。
        行数不超过 SS_MAX_ROWS 时不出滚动条（交给整页滚动）；
        超过时高度封顶，这一块自带一条竖向滚动条。
        """
        lst = getattr(self, "ss_list", None)
        if lst is None:
            return
        item_w = max(1, self.ss_item_w + lst.spacing() * 2)
        item_h = max(1, self.ss_item_h + lst.spacing() * 2)
        # 优先用列表的真实宽度；首次布局尚未完成时退回按窗口宽度估算
        avail = lst.width() - 2
        if lst.viewport().width() > item_w:
            avail = lst.viewport().width()
        if avail <= item_w:
            avail = max(item_w, self.width() - 16 * 2 - 16 * 2 - 18)
        n = lst.count()

        def _rows_for(width):
            per = max(1, int(width // item_w))
            return max(1, (n + per - 1) // per) if n else 1

        rows = _rows_for(avail)
        if rows > self.SS_MAX_ROWS:
            # 将会出现竖向滚动条：可用宽度要再扣掉滚动条宽度
            sb = lst.style().pixelMetric(QStyle.PM_ScrollBarExtent)
            rows = _rows_for(max(item_w, avail - sb))
        h = min(rows, self.SS_MAX_ROWS) * item_h + 8
        lst.setFixedHeight(h)
        if getattr(self, "ss_empty_lbl", None) is not None:
            self.ss_empty_lbl.setFixedHeight(h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_ss_height()

    def _show_ss_menu(self, pos):
        item = self.ss_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        open_act = menu.addAction("打开原图")
        del_act = menu.addAction("删除该截图")
        act = menu.exec(self.ss_list.mapToGlobal(pos))
        if act == open_act:
            self._open_screenshot(item)
        elif act == del_act:
            self._delete_screenshot(item)

    def _open_screenshot(self, item):
        abs_path = to_abs(item.toolTip())
        if os.path.isfile(abs_path):
            try:
                os.startfile(abs_path)
            except Exception as exc:
                QMessageBox.warning(self, "无法打开", str(exc))

    def _delete_screenshot(self, item):
        ss_id = item.data(Qt.UserRole)
        if not ask_yes_no(self, "删除截图", "确定删除这张截图吗？"):
            return
        # 查询文件路径
        for row in self.db.get_screenshots(self.game_id):
            if row["id"] == ss_id:
                abs_path = to_abs(row["file_path"])
                # 缩略图新位置：<游戏名>/缩略图/xxx_thumb.jpg
                thumb_new = to_abs(thumbs_rel_path(row["file_path"]))
                # 兼容旧布局：缩略图与原图同级
                thumb_old, _ = os.path.splitext(abs_path)
                thumb_old += "_thumb.jpg"
                for p in (abs_path, thumb_new, thumb_old):
                    if os.path.isfile(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                # 顺手清掉空的“缩略图”文件夹
                try:
                    thumb_dir_path = os.path.dirname(thumb_new)
                    if os.path.isdir(thumb_dir_path) and not os.listdir(thumb_dir_path):
                        os.rmdir(thumb_dir_path)
                except OSError:
                    pass
                break
        self.db.delete_screenshot(ss_id)
        self._reload_screenshots()


def _esc(s: str) -> str:
    """转义 HTML 特殊字符，防止信息显示被破坏。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _split_list(text) -> list:
    """把逗号 / 顿号 / 分号 / 竖线分隔的文本拆成条目列表（类型、标签、声优用）。"""
    return [p.strip() for p in re.split(r"[,，、;；/|]+", str(text or "")) if p.strip()]


# ============================================================
# 批量导入：文件解析 & 批量对话框
# ============================================================
def _read_text_smart(path: str) -> str:
    """读取文本并自动尝试常见编码（UTF-8 / GBK / Big5）。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312", "big5"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


_TITLE_KW = ("游戏名称", "游戏名", "标题", "游戏", "作品", "title", "name")
_JP_KW = ("原名", "外文", "原", "日文", "japanese", "original", "romaji")
_DEV_KW = ("会社", "公司", "开发", "厂商", "developer", "producer", "开发商")


def _detect_header_columns(header):
    title = jp = dev = None
    for i, h in enumerate(header):
        hl = str(h).lower()
        if title is None and any(k.lower() in hl for k in _TITLE_KW):
            title = i
        if jp is None and any(k.lower() in hl for k in _JP_KW):
            jp = i
        if dev is None and any(k.lower() in hl for k in _DEV_KW):
            dev = i
    return {"title": title, "jp": jp, "dev": dev}


def _looks_like_header(row):
    for c in row:
        cl = str(c).lower()
        if any(k.lower() in cl for k in _TITLE_KW + _JP_KW + _DEV_KW):
            return True
    return False


def _rows_from_xlsx(path: str) -> list:
    """用标准库解析 xlsx（zip+XML），返回选定的工作表所有行（字符串列表）。"""
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    sheets = sorted([n for n in z.namelist()
                     if re.match(r"xl/worksheets/sheet\d+\.xml$", n)])
    best_rows, best_score = [], -1
    for s in sheets:
        try:
            root = ET.fromstring(z.read(s))
        except Exception:
            continue
        rows = []
        for row in root.iter(NS + "row"):
            cells = {}
            for c in row.iter(NS + "c"):
                m = re.match(r"([A-Z]+)", c.get("r") or "")
                letter = m.group(1) if m else ""
                t = c.get("t")
                vnode = c.find(NS + "v")
                isnode = c.find(NS + "is")
                v = ""
                if t == "s" and vnode is not None and vnode.text:
                    v = shared[int(vnode.text)]
                elif t == "inlineStr" and isnode is not None:
                    v = "".join(x.text or "" for x in isnode.iter(NS + "t"))
                elif vnode is not None:
                    v = vnode.text or ""
                cells[letter] = v
            rows.append([cells.get(c, "") for c in "ABCDEFGH"])
        score = sum(1 for r in rows if any(str(x).strip() for x in r))
        if score > best_score:
            best_score, best_rows = score, rows
    return best_rows


def _rows_from_table(path: str) -> list:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return _rows_from_xlsx(path)
    text = _read_text_smart(path)
    if ext == ".csv":
        return [r for r in csv.reader(io.StringIO(text))]
    rows = []
    for ln in text.splitlines():
        if ln.strip():
            rows.append(ln.rstrip("\n").split("\t"))
    return rows


def _read_game_records(path: str) -> list:
    """读取表格并识别出游戏记录：title / title_jp / developer。"""
    rows = _rows_from_table(path)
    rows = [r for r in rows if any(str(x).strip() for x in r)]
    if not rows:
        return []
    header_idx = None
    for i, row in enumerate(rows):
        if _looks_like_header(row):
            header_idx = i
            break
    if header_idx is not None:
        cols = _detect_header_columns(rows[header_idx])
        data_rows = rows[header_idx + 1:]
    else:
        cols = {"title": 0, "jp": None, "dev": None}
        data_rows = rows
    if cols["title"] is None:
        cols["title"] = 0

    def cell(row, idx):
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    records = []
    for row in data_rows:
        title = cell(row, cols["title"])
        if not title or title.lower() in ("none", "nan"):
            continue
        records.append({
            "title": title,
            "title_jp": cell(row, cols["jp"]),
            "developer": cell(row, cols["dev"]),
        })
    return records


class BatchImportDialog(QDialog):
    """批量导入：识别 → 编辑检查 → 确认导入。"""

    TABLE_COLS = ["#", "标题", "原名（日/英）", "开发商", "发售日", "状态", "封面", "识别结果"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("%s · 批量导入" % APP_NAME)
        self.setMinimumSize(920, 660)
        self.worker = None
        self.records = []      # 从表格解析出的原始记录
        self.rows = []         # 当前待导入行
        self._loading = False  # 防止 itemChanged 干扰
        self._terminating = False   # 识别中点击终止 → 停止并对已识别行保留，可确认导入
        self._merge_mode = False    # True=重新识别（原地更新），False=初始识别（追加）
        self._rec_queue = []
        self._rec_idx = None
        self._rec_key = ""
        self._rec_sub = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(12)

        # ===== 导入设置 =====
        setup_card = SectionCard("导入设置")
        top = QHBoxLayout()
        top.addWidget(QLabel("数据源"))
        self.source_combo = TopComboBox()
        self.source_combo.addItem("VNDB（直连）", "vndb")
        self.source_combo.addItem("Bangumi（需梯子）", "bangumi")
        self.source_combo.addItem("Steam（需梯子）", "steam")
        top.addWidget(self.source_combo)
        top.addWidget(QLabel("方式"))
        self.mode_combo = TopComboBox()
        self.mode_combo.addItem("联网自动识别（可下载封面）", "auto")
        self.mode_combo.addItem("直接采用表格字段（无需联网）", "direct")
        top.addWidget(self.mode_combo)
        top.addStretch(1)
        setup_card.body().addLayout(top)

        setup_card.body().addWidget(QLabel("每行一个游戏名；或点「导入表格」选择 xlsx / CSV / TXT。"))
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("例如：\nCLANNAD\nKanon\nSteins;Gate")
        self.edit.setMaximumHeight(90)
        setup_card.body().addWidget(self.edit)

        row = QHBoxLayout()
        import_btn = QPushButton("导入表格（xlsx/CSV/TXT）")
        import_btn.clicked.connect(self.on_import_file)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_input)
        rec_btn = QPushButton("识别 / 生成结果")
        rec_btn.clicked.connect(self.on_recognize)
        bgm_btn = QPushButton("从 Bangumi 导入")
        bgm_btn.setToolTip("读取你的 Bangumi 游戏收藏（评分/状态/封面），核对后导入")
        bgm_btn.clicked.connect(self.on_import_bangumi_collection)
        row.addWidget(import_btn)
        row.addWidget(clear_btn)
        row.addWidget(rec_btn)
        row.addWidget(bgm_btn)
        row.addStretch(1)
        setup_card.body().addLayout(row)
        lay.addWidget(setup_card)

        self.table = QTableWidget()
        # 第 0 列已经是序号，行头冗余；隐藏它可避免行头 section 以下的空白区
        # 在深色主题下露出系统浅色底（白色竖条），同时去掉左上角未上色的 corner button
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(len(self.TABLE_COLS))
        self.table.setHorizontalHeaderLabels(self.TABLE_COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hh = self.table.horizontalHeader()
        # 固定列宽 + 标题/原名/开发商自动填满，避免重算列宽导致的忽宽忽窄
        for col in (0, 4, 5, 6, 7):
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setStretchLastSection(False)
        for col, w in ((0, 36), (4, 92), (5, 60), (6, 54), (7, 78)):
            self.table.setColumnWidth(col, w)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_row_double_click)
        result_card = SectionCard("识别结果", hint="双击行可修改封面")
        result_card.body().addWidget(self.table, 1)

        op_row = QHBoxLayout()
        del_btn = QPushButton("删除所选行")
        del_btn.clicked.connect(self._delete_selected)
        re_btn = QPushButton("重新识别所选")
        re_btn.clicked.connect(self._recognize_selected)
        cover_btn = QPushButton("修改封面")
        cover_btn.clicked.connect(self._change_cover_selected)
        dup_btn = QPushButton("检测重复")
        dup_btn.setToolTip("与库中已有游戏重名的行会标记为“重复”，确认导入时可选择跳过")
        dup_btn.clicked.connect(self.on_check_duplicates)
        op_row.addWidget(del_btn)
        op_row.addWidget(re_btn)
        op_row.addWidget(cover_btn)
        op_row.addWidget(dup_btn)
        op_row.addStretch(1)
        self.status_label = QLabel("尚未识别")
        op_row.addWidget(self.status_label)
        result_card.body().addLayout(op_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        result_card.body().addWidget(self.progress_bar)
        lay.addWidget(result_card, 1)

        btn_row = QHBoxLayout()
        self.confirm_btn = QPushButton("确认导入")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setObjectName("add_btn")
        self.confirm_btn.clicked.connect(self._confirm_import)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.confirm_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

    # ---------- 输入 ----------
    def _clear_input(self):
        self.edit.clear()
        self.records = []

    def _collect_names(self):
        return [s.strip() for s in self.edit.toPlainText().splitlines() if s.strip()]

    def on_import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择表格文件", "",
            "支持的表格 (*.xlsx *.csv *.txt);;Excel (*.xlsx);;CSV (*.csv);;文本 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            records = _read_game_records(path)
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", "解析文件出错：\n%s" % exc)
            return
        if not records:
            QMessageBox.warning(self, "提示", "未能从文件中读取到游戏名。")
            return
        self.records = records
        self.edit.setPlainText("\n".join(r["title"] for r in records))
        self.status_label.setText("已读取 %d 条，请点击“识别 / 生成结果”。" % len(records))

    # ---------- 从 Bangumi 导入收藏 ----------
    def on_import_bangumi_collection(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "提示", "正在导入中，请稍候。")
            return
        token = get_bgm_token()
        username = get_bgm_username()
        if not username:
            username, ok = QInputDialog.getText(
                self, "导入 Bangumi 收藏",
                "请输入你的 Bangumi 用户名（登录后会自动带出）：",
                QLineEdit.Normal, username)
            if not ok or not username.strip():
                return
        if not token:
            QMessageBox.information(
                self, "提示",
                "尚未设置 Bangumi 令牌，可能仅能读到公开收藏，且无法读取 R18 游戏。\n"
                "建议先在侧边栏“设置”里完善。")
        self._terminating = False
        self.rows = []
        self.table.setRowCount(0)
        set_bgm_username(username.strip())
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("终止")
        self.confirm_btn.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在读取 Bangumi 收藏…")
        self.worker = BangumiCollectionWorker(username, token, self)
        self.worker.item_done.connect(self._on_bgm_item)
        self.worker.progress.connect(self._on_bgm_progress)
        self.worker.finished_ok.connect(self._on_bgm_done)
        self.worker.failed.connect(self._on_bgm_fail)
        self.worker.start()

    def _on_bgm_item(self, index, row):
        self.rows.append(row)
        self.table.setRowCount(len(self.rows))
        self._write_row(len(self.rows) - 1, row)

    def _on_bgm_progress(self, count, total, title):
        self.status_label.setText("已读取 %d / %d 条…" % (count, total or count))

    def _on_bgm_done(self, rows):
        self.worker = None
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self.confirm_btn.setEnabled(bool(self.rows))
        if self._terminating:
            self._terminating = False
            self.status_label.setText("已终止：已读取 %d 条，可确认导入。" % len(self.rows))
        elif not rows:
            self.status_label.setText("未读到游戏收藏（可能是 0 条，或用户名不对）。")
        else:
            self.status_label.setText("已从 Bangumi 读取 %d 条，可编辑；确认后才会导入。" % len(rows))

    def _on_bgm_fail(self, msg):
        self.worker = None
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self._terminating = False
        self.status_label.setText("读取失败")
        QMessageBox.warning(self, "读取失败", "读取 Bangumi 收藏出错：\n%s" % msg)

    # ---------- 识别 ----------
    def on_recognize(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "提示", "正在识别中，请稍候。")
            return
        if self.mode_combo.currentData() == "direct":
            self._build_direct()
            return
        if self.records:
            keys = [(r.get("title_jp") or r.get("title") or "").strip()
                    for r in self.records if (r.get("title_jp") or r.get("title") or "").strip()]
        else:
            keys = self._collect_names()
        if not keys:
            QMessageBox.warning(self, "提示", "请先输入游戏名或导入表格。")
            return
        jobs = [{"row": None, "key": k} for k in keys]
        self._start_recognize(jobs)

    def _build_direct(self):
        if self.records:
            data = self.records
        else:
            data = [{"title": n, "title_jp": "", "developer": ""}
                    for n in self._collect_names()]
        self.rows = []
        for d in data:
            title = (d.get("title") or "").strip()
            if not title:
                continue
            self.rows.append({
                "title": title,
                "title_jp": (d.get("title_jp") or "").strip(),
                "developer": (d.get("developer") or "").strip(),
                "release_date": (d.get("release_date") or "").strip(),
                "status": "想玩",
                "cover": (d.get("cover") or ""),
                "found": True,
            })
        self._render_table()
        self.confirm_btn.setEnabled(bool(self.rows))
        self.status_label.setText("已生成 %d 条，可编辑；确认后才会导入。" % len(self.rows))

    def _start_recognize(self, jobs):
        self._merge_mode = False
        self._terminating = False
        self.rows = []
        self.table.setRowCount(0)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("终止")
        self.worker = RecognizeWorker(jobs, self.source_combo.currentData(), self)
        self.progress_bar.setRange(0, len(jobs))
        self.progress_bar.setValue(0)
        self.confirm_btn.setEnabled(False)
        self.status_label.setText("识别中…（%d 条）" % len(jobs))
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.finished_ok.connect(self._on_recognize_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _on_progress(self, done, total, key, ok):
        self.progress_bar.setValue(done)
        self.status_label.setText("识别中 (%d/%d)：%s　%s" % (done, total, key,
                                                              "成功" if ok else "失败"))

    def _on_recognize_done(self, results):
        self.worker = None
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self.confirm_btn.setEnabled(bool(self.rows))
        if self._terminating:
            self._terminating = False
            self.status_label.setText("已终止：已识别 %d 条，可“确认导入”或点击“取消”。" % len(self.rows))
            return
        n_bad = sum(1 for r in self.rows if not r.get("found"))
        if n_bad:
            self.status_label.setText("识别完成：共 %d 条，其中 %d 条未识别（红色），可编辑后重新识别或删除。"
                                      % (len(self.rows), n_bad))
        else:
            self.status_label.setText("识别完成：共 %d 条，可编辑；确认后才会导入。" % len(self.rows))

    def _on_fail(self, msg):
        self.worker = None
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self._terminating = False
        self.status_label.setText("识别中断")
        QMessageBox.warning(self, "错误", "识别失败：\n%s" % msg)

    # ---------- 表格 ----------
    def _write_row(self, i, r):
        self._loading = True
        status_col = ("重复" if r.get("dup")
                      else ("已识别" if r.get("found") else "未识别"))
        cells = [
            str(i + 1), r["title"], r["title_jp"], r["developer"],
            r["release_date"], r["status"],
            "有" if r.get("cover") else "无",
            status_col,
        ]
        for c, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if c in (0, 6, 7):
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if r.get("dup"):
                item.setBackground(QColor(255, 240, 170))
                item.setForeground(QColor(120, 80, 0))
            elif not r.get("found"):
                item.setBackground(QColor(255, 224, 224))
                item.setForeground(QColor(150, 30, 30))
            self.table.setItem(i, c, item)
        self._loading = False

    def _render_table(self):
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            self._write_row(i, r)

    def _on_item_done(self, row, rec, ok, error):
        r = {
            "title": rec.get("title") or "",
            "title_jp": rec.get("title_jp") or "",
            "developer": rec.get("developer") or "",
            "release_date": rec.get("release_date") or "",
            "status": rec.get("status") or "想玩",
            "cover": rec.get("cover") or "",
            "found": bool(ok),
        }
        if self._merge_mode:
            if 0 <= row < len(self.rows):
                self.rows[row] = r
                self._write_row(row, r)
        else:
            self.rows.append(r)
            self.table.setRowCount(len(self.rows))
            self._write_row(len(self.rows) - 1, r)

    def _on_item_changed(self, item):
        if self._loading:
            return
        row = item.row()
        col = item.column()
        if not (0 <= row < len(self.rows)):
            return
        mapping = {1: "title", 2: "title_jp", 3: "developer", 4: "release_date", 5: "status"}
        key = mapping.get(col)
        if key:
            self.rows[row][key] = item.text().strip()

    def _delete_selected(self):
        idxs = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        if not idxs:
            QMessageBox.information(self, "提示", "请先选择要删除的行。")
            return
        for i in idxs:
            if 0 <= i < len(self.rows):
                del self.rows[i]
        self._render_table()
        self.confirm_btn.setEnabled(bool(self.rows))
        self.status_label.setText("已删除，剩余 %d 条。" % len(self.rows))
        # 选中是按行号索引记的：不清掉会“停留”在原位置并指向另一条数据，
        # 用户再点一次「删除所选行」就可能误删没打算删的行
        self.table.clearSelection()

    def _recognize_selected(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "提示", "正在识别中，请稍候。")
            return
        idxs = sorted({i.row() for i in self.table.selectedItems()})
        if not idxs:
            QMessageBox.information(self, "提示", "请先选择要重新识别的行。")
            return
        self._rec_queue = list(idxs)
        self._rec_idx = None
        self._rec_sub = None
        self._terminating = False
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("终止")
        self.confirm_btn.setEnabled(False)
        self._rec_start()

    def _rec_start(self):
        if self._terminating or not self._rec_queue:
            self._rec_finish()
            return
        idx = self._rec_queue.pop(0)
        self._rec_idx = idx
        r = self.rows[idx]
        key = (r.get("title_jp") or r.get("title") or "").strip()
        if not key:
            self.rows[idx]["found"] = False
            self._write_row(idx, self.rows[idx])
            QTimer.singleShot(0, self._rec_start)
            return
        self._rec_key = key
        self.status_label.setText("正在搜索“%s”…" % key)
        src = self.source_combo.currentData()
        if src == "steam":
            self.worker = SteamSearchWorker(key, self)
        elif src == "vndb":
            self.worker = VndbSearchWorker(key, self)
        else:
            self.worker = BangumiSearchWorker(key, self)
        self.worker.finished_ok.connect(self._rec_on_results)
        self.worker.failed.connect(lambda msg: self._rec_on_error(msg))
        self.worker.start()

    def _rec_on_results(self, results):
        self.worker = None
        if self._terminating:
            self._rec_finish()
            return
        if not results:
            self.rows[self._rec_idx]["found"] = False
            self._write_row(self._rec_idx, self.rows[self._rec_idx])
            if self.source_combo.currentData() == "steam":
                QMessageBox.information(
                    self, "提示",
                    "Steam 未搜到“%s”（中文/英文名都试过了）。\n\n"
                    "可能该游戏不在 Steam，或名字差异较大。可尝试输入 Steam 官方名，"
                    "或切换到 VNDB 搜索。" % self._rec_key)
            else:
                QMessageBox.information(self, "提示", "未找到“%s”的结果。" % self._rec_key)
            self._rec_start()
            return
        dlg = SubjectSelectDialog(results, self)
        if dlg.exec() and dlg.selected:
            self._rec_sub = dlg.selected
            sub = dlg.selected
            if sub.get("cover"):
                self.status_label.setText("下载封面中…")
                self.worker = CoverDownloadWorker(sub["cover"], sub.get("id"), self)
                self.worker.done.connect(self._rec_on_cover)
                self.worker.failed.connect(self._rec_on_cover_fail)
                self.worker.start()
                return
            self._rec_apply(sub, "")
            self._rec_start()
        else:
            self.rows[self._rec_idx]["found"] = False
            self._write_row(self._rec_idx, self.rows[self._rec_idx])
            self._rec_start()

    def _rec_on_cover(self, rel, _abs):
        self.worker = None
        self._rec_apply(self._rec_sub, rel)
        self._rec_start()

    def _rec_on_cover_fail(self, msg):
        self.worker = None
        self._rec_apply(self._rec_sub, "")
        self._rec_start()

    def _rec_on_error(self, msg):
        self.worker = None
        self.rows[self._rec_idx]["found"] = False
        self._write_row(self._rec_idx, self.rows[self._rec_idx])
        self.status_label.setText("搜索失败：%s" % msg)
        self._rec_start()

    def _rec_apply(self, sub, cover):
        i = self._rec_idx
        self.rows[i] = {
            "title": sub.get("name_cn") or sub.get("name") or self._rec_key,
            "title_jp": sub.get("name", ""),
            "developer": sub.get("developer", ""),
            "release_date": sub.get("date", ""),
            "status": "想玩",
            "cover": cover,
            "found": True,
        }
        self._write_row(i, self.rows[i])

    def _rec_finish(self):
        self.worker = None
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self.confirm_btn.setEnabled(bool(self.rows))
        if self._terminating:
            self._terminating = False
            self.status_label.setText("已终止。")
            self.reject()
        else:
            self.status_label.setText("重新识别完成。")

    def _change_cover_selected(self):
        idxs = sorted({i.row() for i in self.table.selectedItems()})
        if not idxs:
            QMessageBox.information(self, "提示", "请先选择要修改封面的行。")
            return
        idx = idxs[0]
        r = self.rows[idx]
        key = (r.get("title_jp") or r.get("title") or "").strip()
        if not key:
            QMessageBox.warning(self, "提示", "所选行没有名称，无法搜索封面。")
            return
        dlg = CoverPickerDialog(key, self.source_combo.currentData(), self,
                                r.get("developer", ""))
        if dlg.exec() and dlg.selected_cover:
            for i in idxs:
                if 0 <= i < len(self.rows):
                    self.rows[i]["cover"] = dlg.selected_cover
                    self.rows[i]["found"] = True
                    self._write_row(i, self.rows[i])
            self.status_label.setText("已为 %d 行设置封面。" % len(idxs))

    def _on_row_double_click(self, row, col):
        if self.worker is not None and self.worker.isRunning():
            return
        if not (0 <= row < len(self.rows)):
            return
        r = self.rows[row]
        dlg = GameEditDialog(None, None, self, save_to_db=False, initial_data=r)
        if dlg.exec() and dlg.result_data:
            d = dlg.result_data
            self.rows[row] = {
                "title": d["title"],
                "title_jp": d["title_jp"],
                "developer": d["developer"],
                "release_date": d["release_date"],
                "status": d["status"],
                "rating": d["rating"],
                "play_time": d["play_time"],
                "cover": d["cover_path"],
                "notes": d.get("notes", ""),
                "score_story": d.get("score_story", 0),
                "score_char": d.get("score_char", 0),
                "score_audio": d.get("score_audio", 0),
                "review": d.get("review", ""),
                "found": True,
            }
            self._write_row(row, self.rows[row])
            self.status_label.setText("已更新第 %d 行。" % (row + 1))

    # ---------- 确认导入 ----------
    def _existing_titles_set(self):
        """返回库中已有（标题/原名）的规范化集合，用于查重。"""
        titles = set()
        db = None
        try:
            db = Database(DB_PATH)
            for (t, jp) in db.conn.execute("SELECT title, title_jp FROM games").fetchall():
                if t:
                    titles.add(_name_key(t))
                if jp:
                    titles.add(_name_key(jp))
        except Exception:
            pass
        finally:
            if db:
                db.close()
        return titles

    def on_check_duplicates(self):
        if not self.rows:
            QMessageBox.information(self, "提示", "还没有可检测的行，请先识别或导入。")
            return
        existing = self._existing_titles_set()
        dup_count = 0
        for r in self.rows:
            dup = bool(existing) and (
                _name_key(r.get("title")) in existing
                or _name_key(r.get("title_jp")) in existing)
            r["dup"] = dup
            if dup:
                dup_count += 1
        for i, r in enumerate(self.rows):
            self._write_row(i, r)
        if dup_count:
            self.status_label.setText("检测到 %d 条与库中已有游戏重复（标黄），确认导入时可选择跳过。" % dup_count)
        else:
            self.status_label.setText("未检测到与库中已有游戏的重复。")
        # 检测是整体操作，与当前选中无关；清掉选中，避免高亮残留在表格上
        self.table.clearSelection()

    def _confirm_import(self):
        if not self.rows:
            QMessageBox.warning(self, "提示", "没有可导入的条目。")
            return
        # 重复检测：确认导入前提示是否跳过
        dup_rows = [r for r in self.rows if r.get("dup")]
        skip_dups = False
        if dup_rows:
            mb = QMessageBox(self)
            mb.setWindowTitle("发现重复")
            mb.setText("检测到 %d 条与库中已有游戏重名（标黄）。\n"
                       "选择“是”自动跳过它们（只导入其余）；选择“否”仍全部导入。" % len(dup_rows))
            yes_btn = mb.addButton("是", QMessageBox.YesRole)
            no_btn = mb.addButton("否", QMessageBox.NoRole)
            cancel_btn = mb.addButton("取消", QMessageBox.RejectRole)
            mb.setDefaultButton(yes_btn)
            mb.exec()
            clicked = mb.clickedButton()
            if clicked is cancel_btn:
                return
            skip_dups = (clicked is yes_btn)
        to_import = [r for r in self.rows if not (skip_dups and r.get("dup"))]
        if not to_import:
            QMessageBox.information(self, "提示", "没有可导入的条目（已跳过所有重复）。")
            return
        n_bad = sum(1 for r in to_import if not r.get("found"))
        msg = "将导入 %d 条游戏。" % len(to_import)
        if skip_dups:
            msg = "将导入 %d 条游戏（已跳过 %d 条重复）。" % (
                len(to_import), len(self.rows) - len(to_import))
        if n_bad:
            msg += "\n其中有 %d 条未识别（将只导入标题）。" % n_bad
        msg += "\n\n确认导入到数据库？"
        if not ask_yes_no(self, "确认导入", msg):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        db = None
        ok = 0
        err = None
        try:
            db = Database(DB_PATH)
            for r in to_import:
                title = (r.get("title") or "").strip()
                if not title:
                    continue
                data = {
                    "title": title,
                    "title_jp": r.get("title_jp", ""),
                    "developer": r.get("developer", ""),
                    "release_date": r.get("release_date", ""),
                    "status": r.get("status") or "想玩",
                    "rating": float(r.get("rating", 0) or 0),
                    "score_story": float(r.get("score_story", 0) or 0),
                    "score_char": float(r.get("score_char", 0) or 0),
                    "score_audio": float(r.get("score_audio", 0) or 0),
                    "review": r.get("review", ""),
                    "play_time": int(float(r.get("play_time", 0) or 0)),
                    "cover_path": r.get("cover", ""),
                    "notes": r.get("notes", ""),
                }
                db.add_game(data)
                ok += 1
        except Exception as exc:
            err = str(exc)
        finally:
            if db:
                db.close()
            QApplication.restoreOverrideCursor()
        if err:
            QMessageBox.critical(self, "导入失败", "写入数据库失败：\n%s" % err)
            return
        QMessageBox.information(self, "完成", "已导入 %d 条。" % ok)
        self.accept()

    def _on_cancel(self):
        if self.worker is not None and self.worker.isRunning():
            self._terminating = True
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("终止中…")
            self.worker.requestInterruption()
            self.status_label.setText("正在终止…（当前这条完成后停止）")
            return
        self.reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self._terminating = True
            self.worker.requestInterruption()
            self.status_label.setText("正在终止…（当前这条完成后停止）")
            event.ignore()
            return
        super().closeEvent(event)


def _save_local_cover(src_path: str):
    """把本地图片保存为封面，返回 (相对路径, 绝对路径)。"""
    img = Image.open(src_path)
    img = _transpose(img)
    if img.mode in ("P", "RGBA", "LA"):
        img = img.convert("RGB")
    img.thumbnail((600, 800))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    data = buf.getvalue()
    key = hashlib.md5(data).hexdigest()
    fname = f"cover_{key}.jpg"
    abs_path = os.path.join(COVERS_DIR, fname)
    if not os.path.isfile(abs_path):
        with open(abs_path, "wb") as f:
            f.write(data)
    rel = normalize_rel(os.path.join("data", "covers", fname))
    return rel, abs_path


class CoverGridWorker(QThread):
    """下载多个候选封面缩略图（供封面选择器一次性展示）。"""
    item_ready = Signal(int, str, bool, str)   # idx, rel, ok, label
    finished = Signal()
    failed = Signal(str)

    def __init__(self, cands: list, parent=None):
        super().__init__(parent)
        self.cands = cands

    def run(self):
        for i, r in enumerate(self.cands):
            if self.isInterruptionRequested():
                break
            label = r.get("name_cn") or r.get("name") or ""
            if r.get("date"):
                label += "　·　%s" % r["date"]
            try:
                rel, _ = _download_cover(r["cover"], r.get("id"))
                self.item_ready.emit(i, rel, True, label)
            except Exception as exc:
                self.item_ready.emit(i, "", False, label)
            time.sleep(0.25)
        self.finished.emit()


class CoverPickerDialog(QDialog):
    """搜索游戏并展示多个候选封面缩略图，或导入本地图片；返回 self.selected_cover。"""

    def __init__(self, search_key: str, source: str = "vndb", parent=None,
                 developer: str = ""):
        super().__init__(parent)
        self.setWindowTitle("%s · 更换封面" % APP_NAME)
        self.setMinimumSize(720, 640)
        self.search_key = search_key
        self.source = source
        self.developer = developer
        self.results = []
        self.selected_cover = ""
        self.selected_rel = ""
        self._used = False
        self._downloaded = set()
        self._dev_note = ""
        self.search_worker = None
        self.grid_worker = None
        self._build_ui()
        self._start_search()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(12)

        # ===== 搜索条件 =====
        search_card = SectionCard("搜索封面", hint="可修改名称后再搜索，或导入本地图片")
        top = QHBoxLayout()
        top.addWidget(QLabel("数据源"))
        self.source_combo = TopComboBox()
        self.source_combo.addItem("VNDB（直连）", "vndb")
        self.source_combo.addItem("Bangumi（需梯子）", "bangumi")
        self.source_combo.addItem("Steam（需梯子）", "steam")
        idx = self.source_combo.findData(self.source)
        if idx >= 0:
            self.source_combo.setCurrentIndex(idx)
        top.addWidget(self.source_combo)
        top.addStretch(1)
        search_card.body().addLayout(top)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索名"))
        self.search_edit = QLineEdit()
        self.search_edit.setText(self.search_key)
        self.search_edit.setPlaceholderText("可修改后再搜索")
        self.search_edit.returnPressed.connect(self._on_search_clicked)
        search_row.addWidget(self.search_edit, 2)
        search_row.addWidget(QLabel("开发商"))
        self.dev_edit = QLineEdit()
        self.dev_edit.setPlaceholderText("可选，按开发商筛选")
        if self.developer:
            self.dev_edit.setText(self.developer)
        self.dev_edit.returnPressed.connect(self._on_search_clicked)
        search_row.addWidget(self.dev_edit, 1)
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self._on_search_clicked)
        search_row.addWidget(search_btn)
        search_card.body().addLayout(search_row)
        self.status_label = QLabel("搜索中…")
        self.status_label.setObjectName("sectionHint")
        search_card.body().addWidget(self.status_label)
        lay.addWidget(search_card)

        # ===== 候选封面 =====
        grid_card = SectionCard("候选封面", hint="单击选中，双击直接使用")
        self.grid_widget = QListWidget()
        self.grid_widget.setViewMode(QListView.IconMode)
        self.grid_widget.setIconSize(QSize(150, 200))
        self.grid_widget.setResizeMode(QListView.Adjust)
        self.grid_widget.setSpacing(10)
        self.grid_widget.setMovement(QListView.Static)
        self.grid_widget.setUniformItemSizes(False)
        self.grid_widget.setWordWrap(False)
        self.grid_widget.setTextElideMode(Qt.ElideRight)
        self.grid_widget.itemSelectionChanged.connect(self._on_select)
        self.grid_widget.itemDoubleClicked.connect(lambda _: self._accept())
        grid_card.body().addWidget(self.grid_widget, 1)
        row = QHBoxLayout()
        local_btn = QPushButton("导入本地图片作为封面")
        local_btn.clicked.connect(self._on_local_image)
        row.addWidget(local_btn)
        row.addStretch(1)
        grid_card.body().addLayout(row)
        lay.addWidget(grid_card, 1)
        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn.button(QDialogButtonBox.Ok).setText("使用此封面")
        btn.button(QDialogButtonBox.Ok).setObjectName("add_btn")
        btn.button(QDialogButtonBox.Cancel).setText("取消")
        btn.accepted.connect(self._accept)
        btn.rejected.connect(self.reject)
        lay.addWidget(btn)

    def _start_search(self):
        kw = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        if kw:
            self.search_key = kw
        self.grid_widget.clear()
        self.selected_rel = ""
        self.results = []
        self.status_label.setText("搜索中…")
        src = self.source_combo.currentData() if hasattr(self, "source_combo") else self.source
        if src == "steam":
            self.search_worker = SteamSearchWorker(self.search_key, None)
        elif src == "vndb":
            self.search_worker = VndbSearchWorker(self.search_key, None)
        else:
            self.search_worker = BangumiSearchWorker(self.search_key, None)
        self.search_worker.finished_ok.connect(self._on_results)
        self.search_worker.failed.connect(self._on_fail)
        self.search_worker.start()

    def _on_source_changed(self):
        cur = self.source_combo.currentData()
        if cur == self.source:
            return
        self.source = cur
        for w in (self.search_worker, self.grid_worker):
            if w is not None and w.isRunning():
                w.requestInterruption()
                _orphan_worker(w)
        self.search_worker = None
        self.grid_worker = None
        self._start_search()

    def _on_search_clicked(self):
        self.search_key = self.search_edit.text().strip() or self.search_key
        self.search_edit.setText(self.search_key)
        for w in (self.search_worker, self.grid_worker):
            if w is not None and w.isRunning():
                w.requestInterruption()
                _orphan_worker(w)
        self.search_worker = None
        self.grid_worker = None
        self._start_search()

    def _on_results(self, results):
        if not self.isVisible() or self.sender() is not self.search_worker:
            return
        dev = self.dev_edit.text().strip()
        self._dev_note = ""
        if dev:
            dev_l = dev.lower()
            filtered = [r for r in results
                        if dev_l in str(r.get("developer", "")).lower()]
            if filtered:
                results = filtered
            else:
                # 开发商写法不同导致匹配不到时，保留全部避免搜空
                self._dev_note = "未按开发商“%s”匹配到，已显示全部；可清空开发商重试。" % dev
        self.results = results
        if not results:
            self.status_label.setText("未找到匹配结果（可修改搜索名/开发商，或导入本地图片）。")
            return
        cands = [r for r in results if r.get("cover")][:12]
        if not cands:
            self.status_label.setText("搜索结果没有封面（可点“导入本地图片作为封面”）。")
            return
        self.status_label.setText("正在加载封面缩略图…")
        self.grid_worker = CoverGridWorker(cands, None)
        self.grid_worker.item_ready.connect(self._on_item_ready)
        self.grid_worker.finished.connect(self._on_grid_finished)
        self.grid_worker.failed.connect(lambda m: self.status_label.setText("加载失败：%s" % m))
        self.grid_worker.start()

    def _on_item_ready(self, idx, rel, ok, label):
        if self.sender() is not self.grid_worker:
            return
        text = label.split("　·　")[0] if label else ""
        item = QListWidgetItem(load_cover_icon(rel if ok else "", QSize(150, 200)), text)
        item.setData(Qt.UserRole, rel)
        item.setToolTip(label)
        if not ok:
            item.setBackground(QColor(255, 224, 224))
        else:
            self._downloaded.add(rel)
        self.grid_widget.addItem(item)

    def _on_grid_finished(self):
        if not self.isVisible() or self.sender() is not self.grid_worker:
            return
        if self.grid_widget.count():
            self.grid_widget.setCurrentRow(0)
        if self._dev_note:
            self.status_label.setText(self._dev_note)
        else:
            self.status_label.setText("已加载封面缩略图，点击选择后再点“使用此封面”。")

    def _on_fail(self, msg):
        if not self.isVisible() or self.sender() is not self.search_worker:
            return
        self.status_label.setText("搜索失败")
        QMessageBox.warning(self, "搜索失败", "无法获取封面信息：\n%s" % msg)

    def _on_select(self):
        item = self.grid_widget.currentItem()
        if not item:
            return
        rel = item.data(Qt.UserRole) or ""
        self.selected_rel = rel
        self.status_label.setText("已选择封面，可点“使用此封面”。" if rel
                                  else "该条没有封面，请换一个或导入本地图片。")

    def _on_local_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择本地封面图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;所有文件 (*.*)")
        if not path:
            return
        try:
            rel, _ = _save_local_cover(path)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", "无法读取该图片：\n%s" % exc)
            return
        self._downloaded.add(rel)
        item = QListWidgetItem(load_cover_icon(rel, QSize(150, 200)), "本地图片")
        item.setData(Qt.UserRole, rel)
        self.grid_widget.addItem(item)
        self.grid_widget.clearSelection()
        item.setSelected(True)
        self.selected_rel = rel
        self.status_label.setText("已导入本地封面，可点“使用此封面”。")

    def _accept(self):
        if not self.selected_rel:
            QMessageBox.warning(self, "提示", "请先选择一张封面或导入本地图片。")
            return
        self.selected_cover = self.selected_rel
        self._used = True
        self._cleanup()
        self.accept()

    def reject(self):
        if self._busy():
            for w in (self.search_worker, self.grid_worker):
                if w is not None and w.isRunning():
                    w.requestInterruption()
                    _orphan_worker(w)
            self.search_worker = None
            self.grid_worker = None
        self._cleanup()
        super().reject()

    def _busy(self):
        for w in (self.search_worker, self.grid_worker):
            if w is not None and w.isRunning():
                return True
        return False

    def _cleanup(self):
        for rel in self._downloaded:
            if self._used and rel == self.selected_cover:
                continue
            p = to_abs(rel)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def closeEvent(self, event):
        if self._busy():
            for w in (self.search_worker, self.grid_worker):
                if w is not None and w.isRunning():
                    w.requestInterruption()
                    _orphan_worker(w)
            self.search_worker = None
            self.grid_worker = None
        self._cleanup()
        super().closeEvent(event)


class ImageSearchDialog(QDialog):
    """识图窗口：上传 / 拖拽一张截图，选择数据源（AnimeTrace / SauceNAO / dio），后台识别并展示结果。"""

    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("%s · AI 识图" % APP_NAME)
        self.setMinimumSize(680, 560)
        self.image_path = ""
        self.worker = None
        self._build_ui()
        self.setAcceptDrops(True)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(12)

        # ---- 上传区（拖拽 / 选择）----
        upload_card = SectionCard("上传图片", hint="支持拖拽或粘贴本地截图")
        self.preview = QLabel("把图片拖到这里\n或点击下方「选择图片」")
        self.preview.setObjectName("dropZone")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(220)
        upload_card.body().addWidget(self.preview, 1)

        btn_row = QHBoxLayout()
        pick_btn = QPushButton("选择图片")
        pick_btn.clicked.connect(self._pick_image)
        btn_row.addWidget(pick_btn)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self._clear_image)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
        self.identify_btn = QPushButton("开始识别")
        self.identify_btn.setEnabled(False)
        self.identify_btn.clicked.connect(self._start_identify)
        btn_row.addWidget(self.identify_btn)
        upload_card.body().addLayout(btn_row)

        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("识别数据源"))
        self.source_combo = TopComboBox()
        self.source_combo.addItem("AnimeTrace（免 Key，推荐）", "animetrace")
        self.source_combo.addItem("SauceNAO（需 API Key，较准）", "saucenao")
        self.source_combo.addItem("dio.jite.me（动漫人脸，免 Key）", "dio")
        src_row.addWidget(self.source_combo, 1)
        upload_card.body().addLayout(src_row)
        lay.addWidget(upload_card)

        # ---- 识别结果 ----
        result_card = SectionCard("识别结果", hint="双击可打开来源链接")
        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels(["缩略图", "来源", "作品名", "角色名", "置信度", "来源链接"])
        self.result_table.setColumnWidth(0, 120)
        self.result_table.setColumnWidth(1, 100)
        self.result_table.setColumnWidth(2, 200)
        self.result_table.setColumnWidth(3, 150)
        self.result_table.setColumnWidth(4, 80)
        self.result_table.setColumnWidth(5, 120)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.cellDoubleClicked.connect(self._open_result_link)
        self.result_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.result_table.customContextMenuRequested.connect(self._show_result_menu)
        result_card.body().addWidget(self.result_table, 1)

        copy_row = QHBoxLayout()
        copy_work_btn = QPushButton("复制选中作品名")
        copy_work_btn.clicked.connect(lambda: self._copy_result_text(2))
        copy_char_btn = QPushButton("复制选中角色名")
        copy_char_btn.clicked.connect(lambda: self._copy_result_text(3))
        copy_row.addWidget(copy_work_btn)
        copy_row.addWidget(copy_char_btn)
        copy_row.addStretch(1)
        self.add_btn = QPushButton("确认并添加")
        self.add_btn.setObjectName("add_btn")
        self.add_btn.setToolTip("把选中的识别结果交给「添加游戏」窗口，核对后再保存")
        self.add_btn.clicked.connect(self._add_selected_result)
        copy_row.addWidget(self.add_btn)
        result_card.body().addLayout(copy_row)
        lay.addWidget(result_card, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("sectionHint")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择识图图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*.*)")
        if path:
            self._set_image(path)

    def _set_image(self, path):
        if not os.path.isfile(path):
            return
        if not self._is_image(path):
            QMessageBox.warning(self, "提示", "请选择图片文件。")
            return
        self.image_path = path
        pix = QPixmap(path)
        if pix.isNull():
            QMessageBox.warning(self, "提示", "无法加载该图片。")
            return
        max_w, max_h = 620, 300
        if pix.width() > max_w or pix.height() > max_h:
            pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pix)
        self.preview.setStyleSheet(
            "border:2px solid %s;border-radius:14px;background:transparent;"
            % accent_color())
        self.identify_btn.setEnabled(True)

    def _clear_image(self):
        self.image_path = ""
        self.preview.clear()
        self.preview.setText("把图片拖到这里\n或点击下方「选择图片」")
        self.preview.setStyleSheet(
            "border:2px dashed %s;border-radius:14px;color:%s;background:transparent;"
            % (pstr("border", "border_a"), pstr("muted")))
        self.identify_btn.setEnabled(False)
        self._clear_results()

    def _clear_results(self):
        self.result_table.setRowCount(0)
        self.status_label.setText("")

    def _selected_row(self):
        row = self.result_table.currentRow()
        if row < 0:
            items = self.result_table.selectedItems()
            if items:
                row = items[0].row()
        return row

    def _copy_result_text(self, col):
        row = self._selected_row()
        if row < 0:
            self.status_label.setText("请先选择一条识别结果")
            return
        item = self.result_table.item(row, col)
        if item is None or not item.text().strip():
            self.status_label.setText("该列没有可复制的内容")
            return
        QApplication.clipboard().setText(item.text().strip())
        self.status_label.setText("已复制：%s" % item.text().strip())

    def _add_selected_result(self):
        """把选中的识别结果交给「添加游戏」窗口核对后入库。

        只做"把结果填进现有添加流程"这一步，识图本身的核心逻辑完全没有改动。
        """
        row = self._selected_row()
        if row < 0:
            self.status_label.setText("请先选择一条识别结果")
            return
        item = self.result_table.item(row, 2)          # 第 2 列 = 作品名
        name = item.text().strip() if item is not None else ""
        if not name:
            self.status_label.setText("该结果没有作品名，无法添加")
            return
        if self.db is None:
            self.status_label.setText("当前窗口没有数据库连接，无法添加")
            return
        dlg = GameEditDialog(self.db, None, self, initial_data={"title": name})
        if dlg.exec():
            self.status_label.setText("已添加：%s" % name)

    def _show_result_menu(self, pos):
        row = self.result_table.rowAt(pos.y())
        if row < 0:
            return
        self.result_table.selectRow(row)
        menu = QMenu(self)
        act_work = menu.addAction("复制作品名")
        act_char = menu.addAction("复制角色名")
        act_link = menu.addAction("复制来源链接")
        chosen = menu.exec(self.result_table.viewport().mapToGlobal(pos))
        if chosen == act_work:
            self._copy_result_text(2)
        elif chosen == act_char:
            self._copy_result_text(3)
        elif chosen == act_link:
            self._copy_result_text(5)

    @staticmethod
    def _is_image(path):
        return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for u in event.mimeData().urls():
            if u.isLocalFile():
                p = u.toLocalFile()
                if self._is_image(p):
                    self._set_image(p)
                    event.acceptProposedAction()
                    return
        event.ignore()

    def _start_identify(self):
        if not self.image_path:
            return
        source = self.source_combo.currentData()
        if source == "saucenao" and not get_sauce_key().strip():
            QMessageBox.warning(
                self, "缺少 Key",
                "SauceNAO 需要 API Key。\n请到设置  账号中配置。")
            return
        self.identify_btn.setEnabled(False)
        self.identify_btn.setText("识别中…")
        self.status_label.setText("正在识别，请稍候…")
        self._clear_results()
        self.worker = ImageSearchWorker(self.image_path, source, None)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_fail)
        _orphan_worker(self.worker)
        self.worker.start()

    def _on_done(self, results):
        self.identify_btn.setEnabled(True)
        self.identify_btn.setText("开始识别")
        if not results:
            self.status_label.setText("未识别到相关作品 / 角色，可尝试换一张图或切换数据源。")
            return
        self.result_table.setRowCount(0)
        thumb_jobs = []
        for r in results:
            row = self.result_table.rowCount()
            self.result_table.insertRow(row)
            # 缩略图占位（列0）
            ph = QLabel("…")
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet(
                "color:%s;background:%s;border:1px solid %s;"
                % (pstr("muted"), pstr("row"), pstr("border", "border_a")))
            self.result_table.setCellWidget(row, 0, ph)
            self.result_table.setItem(row, 1, QTableWidgetItem(r.get("source", "")))
            self.result_table.setItem(row, 2, QTableWidgetItem(r.get("work", "")))
            self.result_table.setItem(row, 3, QTableWidgetItem(r.get("character", "")))
            sim = r.get("similarity")
            score = r.get("score")
            val = ""
            if sim is not None:
                val = "%.2f%%" % (float(sim or 0))
            elif score:
                val = "%.3f" % (float(score or 0))
            self.result_table.setItem(row, 4, QTableWidgetItem(val))
            link = r.get("url", "")
            self.result_table.setItem(row, 5, QTableWidgetItem(link))
            self.result_table.item(row, 2).setData(Qt.UserRole, link)
            thumb = r.get("thumbnail", "")
            if thumb:
                thumb_jobs.append((row, thumb))
            else:
                ph.setText("无预览")
        self.status_label.setText("识别完成，共 %d 条结果。" % len(results))
        self._start_thumb_loader(thumb_jobs)
    def _on_fail(self, msg):
        self.identify_btn.setEnabled(True)
        self.identify_btn.setText("开始识别")
        self.status_label.setText("识别失败")
        QMessageBox.warning(self, "识别失败", "%s" % msg)

    def _start_thumb_loader(self, jobs):
        if not jobs:
            return
        self._thumb_worker = ThumbLoaderWorker(jobs, None)
        self._thumb_worker.thumb_ready.connect(self._on_thumb_ready)
        self._thumb_worker.thumb_fail.connect(self._on_thumb_fail)
        _orphan_worker(self._thumb_worker)
        self._thumb_worker.start()

    def _on_thumb_ready(self, row, data):
        img = QImage.fromData(data)
        if img.isNull():
            self._on_thumb_fail(row)
            return
        pix = QPixmap.fromImage(img)
        w, h = 110, 80
        if pix.width() > w or pix.height() > h:
            pix = pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pix)
        label.setStyleSheet(
            "background:%s;border:1px solid %s;"
            % (pstr("row"), pstr("border", "border_a")))
        self.result_table.setCellWidget(row, 0, label)

    def _on_thumb_fail(self, row):
        label = QLabel("无预览")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            "color:%s;background:%s;border:1px solid %s;"
            % (pstr("muted"), pstr("row"), pstr("border", "border_a")))
        self.result_table.setCellWidget(row, 0, label)

    def _open_result_link(self, row, col):
        item = self.result_table.item(row, 2)
        if item is None:
            return
        url = item.data(Qt.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.information(self, "提示", "该结果没有可打开的来源链接。")

class SettingsDialog(QDialog):
    """设置窗口：按「外观 / 头像与桌宠 / API 与账号 / 存储与关于」四类分页。"""

    def __init__(self, parent=None, db=None):
        super().__init__(parent)
        self.setWindowTitle("%s · 设置" % APP_NAME)
        self.setMinimumSize(640, 480)
        self.resize(780, 680)
        self.login_worker = None
        # 主窗口会传进来；没传时整理图库会临时自己开一个连接
        self.db = db
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ===== 顶部品牌头（始终显示在最上面）=====
        head_wrap = QWidget()
        head_lay = QVBoxLayout(head_wrap)
        head_lay.setContentsMargins(16, 14, 16, 6)
        head_lay.setSpacing(10)
        outer.addWidget(head_wrap)

        # 各分区先建好，最后按分类装进标签页（见 _add_settings_tab）
        header = QFrame()
        header.setObjectName("heroCard")
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(16, 12, 16, 12)
        header_lay.setSpacing(12)
        logo = QLabel()
        logo.setFixedSize(36, 36)
        logo.setPixmap(app_icon_pixmap(36, radius=10))
        header_lay.addWidget(logo)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("app_brand")
        sub = QLabel(APP_SUBTITLE)
        sub.setObjectName("app_sub")
        title_box.addWidget(brand)
        title_box.addWidget(sub)
        header_lay.addLayout(title_box, 1)
        head_lay.addWidget(header)

        # ===== 主题选择 =====
        self.theme_sec = CollapsibleSection("主题选择")
        theme_lay = self.theme_sec.content_layout()
        theme_lay.addWidget(QLabel("主题（同时切换配色方案和主题自带背景图）："))
        self.theme_combo = TopComboBox()
        for tid in THEME_ORDER:
            self.theme_combo.addItem(THEME_DEFS[tid]["name"], tid)
        ti = self.theme_combo.findData(get_theme_id())
        self.theme_combo.setCurrentIndex(ti if ti >= 0 else 0)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_pick)
        theme_lay.addWidget(self.theme_combo)

        theme_lay.addWidget(QLabel("颜色模式："))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self._mode_group = QButtonGroup(self)
        self._mode_btns = {}
        for mode, label in (("light", "浅色"), ("dark", "深色"), ("system", "跟随系统")):
            rb = QRadioButton(label)
            rb.setCursor(Qt.PointingHandCursor)
            rb.setProperty("colorMode", mode)
            self._mode_group.addButton(rb)
            self._mode_btns[mode] = rb
            mode_row.addWidget(rb)
            rb.toggled.connect(self._on_color_mode_pick)
        cur_mode = get_color_mode()
        if cur_mode in self._mode_btns:
            self._mode_btns[cur_mode].setChecked(True)
        mode_row.addStretch(1)
        theme_lay.addLayout(mode_row)

        theme_lay.addWidget(QLabel("强调色（可选；默认跟随主题，不影响背景图）："))
        self.accent_follow_check = QCheckBox("跟随当前主题")
        self.accent_follow_check.setChecked(not bool(get_accent_override()))
        self.accent_follow_check.toggled.connect(self._on_accent_follow_toggled)
        theme_lay.addWidget(self.accent_follow_check)
        accent_grid = QGridLayout()
        accent_grid.setSpacing(10)
        self._accent_btns = {}
        for idx, (key, preset) in enumerate(ACCENT_PRESETS.items()):
            b = QToolButton()
            b.setFixedSize(26, 26)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QToolButton{background:%s;border-radius:13px;border:2px solid transparent;}"
                "QToolButton:hover{border-color:rgba(255,255,255,0.6);}" % preset["color"])
            b.setToolTip(preset["name"])
            b.clicked.connect(lambda _=False, k=key: self._on_accent_pick(k))
            accent_grid.addWidget(b, idx // 6, idx % 6)
            self._accent_btns[key] = b
        accent_grid.setColumnStretch(6, 1)
        theme_lay.addLayout(accent_grid)
        self._update_accent_buttons()

        # ===== 账号令牌（各自独立可折叠分类）=====
        # SteamGridDB
        self.sgdb_sec = CollapsibleSection("SteamGridDB API Key")
        sgdb_lay = self.sgdb_sec.content_layout()
        sgdb_lay.addWidget(QLabel("用于在 Steam 搜索结果里叠加社区竖版封面（可选）。"))
        sgdb_row = QHBoxLayout()
        self.sgdb_edit = QLineEdit()
        self.sgdb_edit.setPlaceholderText("粘贴你的 SteamGridDB API Key")
        self.sgdb_edit.setText(get_sgdb_key())
        sgdb_row.addWidget(self.sgdb_edit, 1)
        sgdb_eye = QToolButton()
        sgdb_eye.setCheckable(True)
        sgdb_eye.setToolTip("显示 / 隐藏")
        sgdb_eye.setText("👁")
        sgdb_eye.setFixedWidth(28)

        def _sgdb_toggle(checked):
            self.sgdb_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

        sgdb_eye.toggled.connect(_sgdb_toggle)
        sgdb_row.addWidget(sgdb_eye)
        self.sgdb_edit.setEchoMode(QLineEdit.Password)
        sgdb_lay.addLayout(sgdb_row)
        sgdb_get = QPushButton("获取 API Key")
        sgdb_get.setToolTip("打开 SteamGridDB 开发者页面获取 Key")
        sgdb_get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.steamgriddb.com/profile/preferences/api")))
        sgdb_lay.addWidget(sgdb_get)

        # Bangumi
        self.bgm_sec = CollapsibleSection("Bangumi 个人令牌")
        bgm_lay = self.bgm_sec.content_layout()
        bgm_lay.addWidget(QLabel("用于 R18 搜索、登录并导入收藏（可选）。令牌约 1 年有效，仅保存在本机。"))
        bgm_row = QHBoxLayout()
        self.bgm_edit = QLineEdit()
        self.bgm_edit.setPlaceholderText("粘贴你的 Bangumi Access Token")
        self.bgm_edit.setText(get_bgm_token())
        bgm_row.addWidget(self.bgm_edit, 1)
        bgm_eye = QToolButton()
        bgm_eye.setCheckable(True)
        bgm_eye.setToolTip("显示 / 隐藏")
        bgm_eye.setText("👁")
        bgm_eye.setFixedWidth(28)

        def _bgm_toggle(checked):
            self.bgm_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

        bgm_eye.toggled.connect(_bgm_toggle)
        bgm_row.addWidget(bgm_eye)
        self.bgm_edit.setEchoMode(QLineEdit.Password)
        bgm_lay.addLayout(bgm_row)
        bgm_btn_row = QHBoxLayout()
        self.login_btn = QPushButton("验证并登录")
        self.login_btn.clicked.connect(self._verify_login)
        open_btn = QPushButton("获取令牌")
        open_btn.setToolTip("打开 Bangumi 令牌生成页")
        open_btn.clicked.connect(self._open_token_page)
        self.profile_btn = QPushButton("打开个人主页")
        self.profile_btn.clicked.connect(self._open_bgm_profile)
        self.logout_btn = QPushButton("退出登录")
        self.logout_btn.setObjectName("dangerItem")
        self.logout_btn.setCursor(Qt.PointingHandCursor)
        self.logout_btn.clicked.connect(self._logout)
        bgm_btn_row.addWidget(self.login_btn)
        bgm_btn_row.addWidget(open_btn)
        bgm_btn_row.addWidget(self.profile_btn)
        bgm_btn_row.addWidget(self.logout_btn)
        bgm_btn_row.addStretch(1)
        bgm_lay.addLayout(bgm_btn_row)
        self.login_status = QLabel("")
        self.login_status.setStyleSheet("color:%s;" % pstr("accent"))
        bgm_lay.addWidget(self.login_status)

        # SauceNAO
        self.sauce_sec = CollapsibleSection("SauceNAO API Key")
        sauce_lay = self.sauce_sec.content_layout()
        sauce_lay.addWidget(QLabel("用于识图识别（可选），在 saucenao.com 注册后于 API 页面获取。"))
        sauce_row2 = QHBoxLayout()
        self.sauce_edit = QLineEdit()
        self.sauce_edit.setPlaceholderText("粘贴你的 SauceNAO API Key")
        self.sauce_edit.setText(get_sauce_key())
        sauce_row2.addWidget(self.sauce_edit, 1)
        sauce_eye2 = QToolButton()
        sauce_eye2.setCheckable(True)
        sauce_eye2.setToolTip("显示 / 隐藏")
        sauce_eye2.setText("👁")
        sauce_eye2.setFixedWidth(28)

        def _sauce_toggle(checked):
            self.sauce_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

        sauce_eye2.toggled.connect(_sauce_toggle)
        sauce_row2.addWidget(sauce_eye2)
        self.sauce_edit.setEchoMode(QLineEdit.Password)
        sauce_lay.addLayout(sauce_row2)
        sauce_get = QPushButton("获取 API Key")
        sauce_get.setToolTip("打开 SauceNAO 搜索 API 页面")
        sauce_get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://saucenao.com/user.php?page=search-api")))
        sauce_lay.addWidget(sauce_get)

        # ===== 显示分类（悬浮 CG 预览，与主题/背景解耦）=====
        self.disp_sec = CollapsibleSection("显示（悬浮 CG 预览）")
        disp_lay = self.disp_sec.content_layout()
        disp_lay.addWidget(QLabel("悬浮 CG 预览大小："))
        self.hover_combo = TopComboBox()
        self.hover_combo.addItem("小", "small")
        self.hover_combo.addItem("中", "medium")
        self.hover_combo.addItem("大", "large")
        hi = self.hover_combo.findData(get_hover_size())
        if hi >= 0:
            self.hover_combo.setCurrentIndex(hi)
        disp_lay.addWidget(self.hover_combo)
        disp_lay.addWidget(QLabel("悬浮 CG 切换间隔（秒）："))
        self.hover_interval_slider = QSlider(Qt.Horizontal)
        self.hover_interval_slider.setRange(5, 30)   # 0.5 ~ 3.0 秒（读取 config 的取值范围）
        self.hover_interval_slider.setSingleStep(1)
        self.hover_interval_slider.setPageStep(5)
        self.hover_interval_slider.setTickPosition(QSlider.TicksBelow)
        self.hover_interval_slider.setTickInterval(5)
        self.hover_interval_slider.setValue(int(round(get_hover_interval() * 10)))
        self.hover_interval_label = QLabel("%.1f 秒" % get_hover_interval())
        self.hover_interval_label.setStyleSheet("color:%s;font-weight:bold;" % accent_color())
        self.hover_interval_slider.valueChanged.connect(self._on_hover_interval)
        disp_lay.addWidget(self.hover_interval_slider)
        disp_lay.addWidget(self.hover_interval_label)

        # ===== 背景设置（主题自带 / 自定义背景，独立的第二区块）=====
        self.bg_sec = CollapsibleSection("背景设置")
        bg_lay = self.bg_sec.content_layout()
        bg_lay.addWidget(QLabel("当前背景状态："))
        self.bg_status_lbl = QLabel("")
        self.bg_status_lbl.setObjectName("kvValue")
        bg_lay.addWidget(self.bg_status_lbl)
        self.bg_preview = QLabel("")
        self.bg_preview.setObjectName("userImgPreview")
        self.bg_preview.setFixedSize(180, 101)
        self.bg_preview.setAlignment(Qt.AlignCenter)
        bg_lay.addWidget(self.bg_preview, 0, Qt.AlignLeft)
        bg_btns = QHBoxLayout()
        upload_bg = QPushButton("上传自定义背景…")
        upload_bg.setCursor(Qt.PointingHandCursor)
        upload_bg.clicked.connect(self._pick_bg)
        bg_btns.addWidget(upload_bg)
        restore_bg = QPushButton("恢复主题默认背景")
        restore_bg.setCursor(Qt.PointingHandCursor)
        restore_bg.clicked.connect(self._clear_bg)
        bg_btns.addWidget(restore_bg)
        bg_btns.addStretch(1)
        bg_lay.addLayout(bg_btns)
        _bg_tip0 = QLabel("自定义背景只替换背景图，不会改变当前主题配色方案。")
        _bg_tip0.setObjectName("hint")
        _bg_tip0.setWordWrap(True)
        bg_lay.addWidget(_bg_tip0)
        _bg_tip = QLabel("预设图库（把图片放进 data\\wallpapers\\ 会自动出现在这里）："
                         "点击后作为自定义背景，同样不改变主题配色。")
        _bg_tip.setObjectName("hint")
        _bg_tip.setWordWrap(True)
        bg_lay.addWidget(_bg_tip)
        bg_lay.addWidget(self._preset_strip("bg", self._on_pick_bg_preset, 108, 68))
        self._refresh_bg_panel()

        # ===== 桌宠（右下角气泡）=====
        self.pet_sec = CollapsibleSection("桌宠（右下角气泡）")
        pet_lay = self.pet_sec.content_layout()
        pet_lay.addWidget(self._user_image_row(
            "pet", "桌宠形象",
            "显示在气泡左侧。建议用正方形图片（会自动裁成圆角）；留空则用应用图标。", 42, 12))
        pet_lay.addWidget(QLabel(
            "主界面右下角的小气泡，只是装饰：点一下会随机说一句话。"))
        self.pet_show_check = QCheckBox("显示桌宠气泡")
        self.pet_show_check.setChecked(not get_assistant_hidden())
        self.pet_show_check.toggled.connect(self._on_pet_show)
        pet_lay.addWidget(self.pet_show_check)
        self.pet_click_check = QCheckBox("点击桌宠时随机换一句话")
        self.pet_click_check.setChecked(get_pet_click_random())
        self.pet_click_check.toggled.connect(self._on_pet_click)
        pet_lay.addWidget(self.pet_click_check)
        pet_lay.addWidget(QLabel("自动换一句话："))
        self.pet_auto_combo = TopComboBox()
        for label, minutes in (("关闭", 0), ("每 1 分钟", 1), ("每 5 分钟", 5),
                               ("每 15 分钟", 15), ("每 30 分钟", 30), ("每 60 分钟", 60)):
            self.pet_auto_combo.addItem(label, minutes)
        _ai = self.pet_auto_combo.findData(get_pet_auto_minutes())
        self.pet_auto_combo.setCurrentIndex(_ai if _ai >= 0 else 0)
        self.pet_auto_combo.currentIndexChanged.connect(self._on_pet_auto)
        pet_lay.addWidget(self.pet_auto_combo)
        self.pet_preview_lbl = QLabel("")
        self.pet_preview_lbl.setObjectName("petPreview")
        self.pet_preview_lbl.setWordWrap(True)
        _pool0 = get_pet_lines()
        if _pool0:
            self.pet_preview_lbl.setText("试试效果：" + random.choice(_pool0))
        pet_lay.addWidget(self.pet_preview_lbl)
        self.pet_lines_edit = QPlainTextEdit()
        self.pet_lines_edit.setPlaceholderText("在这里写你自己的句子，一行一句；留空则使用内置语句")
        self.pet_lines_edit.setPlainText("\n".join(get_pet_lines()))
        self.pet_lines_edit.setFixedHeight(118)
        pet_lay.addWidget(self.pet_lines_edit)
        pet_btns = QHBoxLayout()
        pet_apply = QPushButton("应用语句并试一句")
        pet_apply.clicked.connect(self._on_pet_lines_apply)
        pet_btns.addWidget(pet_apply)
        pet_reset = QPushButton("恢复内置语句")
        pet_reset.clicked.connect(self._on_pet_lines_reset)
        pet_btns.addWidget(pet_reset)
        pet_btns.addStretch(1)
        pet_lay.addLayout(pet_btns)
        pet_lay.addWidget(QLabel(
            "内置语句共 %d 句；未设置自定义语句时就用这一套。语句只存在本机 settings.json 里。"
            % len(PET_LINES)))

        # ===== CG 存储分类 =====
        self.cg_sec = CollapsibleSection("CG 存储位置")
        cg_lay = self.cg_sec.content_layout()
        cg_lay.addWidget(QLabel(
            "新上传的 CG 会按「分类 / 游戏名」两级子文件夹存放在此目录下，"
            "随机 CG 预览里的「本地 CG 优先」会按游戏名分类筛选。"))
        self.cg_edit = QLineEdit()
        self.cg_edit.setText(get_cg_root())
        self.cg_edit.setPlaceholderText("例如：E:\\cg存储")
        cg_row = QHBoxLayout()
        cg_row.addWidget(self.cg_edit, 1)
        cg_btn = QPushButton("浏览…")
        cg_btn.clicked.connect(self._pick_cg)
        cg_row.addWidget(cg_btn)
        cg_lay.addLayout(cg_row)

        organize_row = QHBoxLayout()
        self.cg_organize_btn = QPushButton("整理历史图片到游戏文件夹")
        self.cg_organize_btn.setToolTip(
            "把旧布局（直接放在分类目录下）的图片移动到对应的游戏文件夹")
        self.cg_organize_btn.clicked.connect(self._organize_cg_library)
        organize_row.addWidget(self.cg_organize_btn)
        organize_row.addStretch(1)
        cg_lay.addLayout(organize_row)
        cg_tip = QLabel(
            "历史图片的归属优先按「数据库截图记录 / 文件名里的游戏 ID」推断，"
            "推断不出的归入「未分类」；移动后数据库里的截图路径会一起更新。")
        cg_tip.setObjectName("hint")
        cg_tip.setWordWrap(True)
        cg_lay.addWidget(cg_tip)

        # ===== 侧边栏头像 =====
        self.avatar_sec = CollapsibleSection("侧边栏头像")
        avatar_lay = self.avatar_sec.content_layout()
        avatar_lay.addWidget(self._user_image_row(
            "avatar", "侧边栏头像",
            "显示在左上角（「游戏库 / 收藏」上方）。建议用正方形图片（会自动裁成圆角）；"
            "留空则用应用图标。", 64, 14))
        _av_tip = QLabel("或直接点下面的预设头像（把图片放进 data\\profile photo\\ 就会自动出现在这里）：")
        _av_tip.setObjectName("hint")
        avatar_lay.addWidget(_av_tip)
        avatar_lay.addWidget(self._preset_strip("avatar", self._on_pick_avatar_preset, 56, 56))

        # ===== 关于 =====
        self.about_card = SectionCard("关于")
        root = os.path.dirname(os.path.dirname(DB_PATH))
        about_grid = QFormLayout()
        about_grid.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for k, v in (("应用", "%s（%s）" % (APP_NAME, APP_SUBTITLE)),
                     ("版本", APP_VERSION),
                     ("数据目录", os.path.join(root, "data")),
                     ("说明文档", os.path.join(root, "help")),
                     ("回滚点", os.path.join(root, "backup"))):
            lbl = QLabel(str(v))
            lbl.setObjectName("kvValue")
            lbl.setWordWrap(True)
            about_grid.addRow(k, lbl)
        self.about_card.body().addLayout(about_grid)
        about_btns = QHBoxLayout()
        about_btns.setSpacing(8)
        for text, path in (("打开说明文档", os.path.join(root, "help", "README.md")),
                           ("打开回滚点目录", os.path.join(root, "backup")),
                           ("打开数据目录", os.path.join(root, "data"))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, p=path: self._open_path(p))
            about_btns.addWidget(b)
        about_btns.addStretch(1)
        self.about_card.body().addLayout(about_btns)

        # ===== 按分类装进标签页（顺手把设置理顺）=====
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self._tab_scrolls = {}
        self._add_settings_tab("外观", [self.theme_sec, self.bg_sec])
        self._add_settings_tab("显示", [self.disp_sec])
        self._add_settings_tab("头像与桌宠", [self.avatar_sec, self.pet_sec])
        self._add_settings_tab("API 与账号", [self.sgdb_sec, self.bgm_sec, self.sauce_sec])
        self._add_settings_tab("存储与关于", [self.cg_sec, self.about_card])
        outer.addWidget(self.tabs, 1)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("保存")
        box.button(QDialogButtonBox.Cancel).setText("取消")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        outer.addWidget(box)
        self._refresh_login_status()
        self._refresh_user_previews()
        self._refresh_preset_marks()

    # ---------- 设置页：分类标签页 / 头像与桌宠形象 ----------
    def _add_settings_tab(self, title: str, sections):
        """把若干分区分装进一个可滚动的标签页（页面与滚动区都透明，别露系统白底）。"""
        scroll = QScrollArea()
        scroll.setObjectName("settingsTab")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        page.setObjectName("settingsTabPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(12)
        for w in sections:
            v.addWidget(w)
        v.addStretch(1)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        self._tab_scrolls[title] = scroll

    def _preset_strip(self, kind: str, on_pick, tw: int, th: int):
        """一排预设缩略图（横向可滚）+「刷新」，并**自动监听目录变化**。

        所以往 data\\profile photo\\ 或 data\\wallpapers\\ 里丢图片之后，
        不用重开设置页 —— 监听 + 600ms 防抖会自动重扫；「刷新」按钮兜底手动重扫。
        """
        box = QWidget()
        box.setObjectName("presetBox")
        outer = QHBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        area = QScrollArea()
        area.setObjectName("presetStrip")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setFixedHeight(th + 30)
        outer.addWidget(area, 1)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setObjectName("presetRefresh")
        refresh_btn.setFixedWidth(58)
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setToolTip("重新扫描文件夹（放进去的图片会立刻出现在这里）")
        outer.addWidget(refresh_btn, 0, Qt.AlignVCenter)

        def rebuild():
            paths = list_presets(kind)
            page = QWidget()
            page.setObjectName("presetPage")
            row = QHBoxLayout(page)
            row.setContentsMargins(2, 2, 2, 2)
            row.setSpacing(8)
            btns = []
            if not paths:
                tip = QLabel("这个文件夹里还没有图片：%s（放进去会自动出现在这里）"
                             % os.path.relpath(get_preset_dir(kind), os.path.dirname(DB_PATH)))
                tip.setObjectName("hint")
                row.addWidget(tip)
            for p in paths:
                b = QToolButton()
                b.setObjectName("presetBtn")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setFixedSize(tw, th)
                b.setIcon(QIcon(rounded_cover_pixmap(p, tw - 4, th - 4, 10)))
                b.setIconSize(QSize(tw - 4, th - 4))
                b.setToolTip(os.path.basename(p))
                b.setProperty("presetPath", p)
                b.clicked.connect(lambda _=False, pp=p: on_pick(pp))
                row.addWidget(b)
                btns.append(b)
            row.addStretch(1)
            area.setWidget(page)
            # 先登记按钮再刷高亮（_refresh_preset_marks 要靠这个属性拿按钮）
            setattr(self, "_preset_btns_" + kind, btns)
            self._refresh_preset_marks()
            refresh_btn.setToolTip("重新扫描文件夹（当前 %d 张）" % len(paths))
            return len(paths)

        refresh_btn.clicked.connect(lambda: rebuild())
        setattr(self, "_preset_refresh_" + kind, refresh_btn)
        rebuild()

        # ---- 目录监听：后续放进来的图片自动变成预设 ----
        folder = get_preset_dir(kind)
        watcher = QFileSystemWatcher(box)
        debounce = QTimer(box)
        debounce.setSingleShot(True)
        debounce.setInterval(600)

        def rescan(*_a):
            # 目录可能刚被重建 / 换掉，重新挂上监听
            if os.path.isdir(folder) and folder not in watcher.directories():
                try:
                    watcher.addPath(folder)
                except Exception:
                    pass
            rebuild()

        debounce.timeout.connect(rescan)

        def on_dir_changed(_path=""):
            debounce.start()

        watcher.directoryChanged.connect(on_dir_changed)
        if os.path.isdir(folder):
            try:
                watcher.addPath(folder)
            except Exception:
                pass
        setattr(self, "_preset_watcher_" + kind, watcher)
        setattr(self, "_preset_debounce_" + kind, debounce)
        return box

    def _refresh_preset_marks(self):
        """给"当前正在用"的预设加高亮；换了别的图（浏览/清除）也会同步取消高亮。"""
        cur_map = {"bg": get_custom_background_path(), "avatar": get_avatar_image()}
        for kind, cur in cur_map.items():
            cur_abs = os.path.normcase(os.path.abspath(to_abs(cur))) if cur else ""
            for b in getattr(self, "_preset_btns_" + kind, []):
                p = b.property("presetPath") or ""
                same = bool(cur_abs) and p and \
                    os.path.normcase(os.path.abspath(p)) == cur_abs
                b.setChecked(same)

    def _on_pick_bg_preset(self, path: str):
        # 预设图已在项目内，直接存相对路径，不复制；仍算“自定义背景”。
        theme_manager.set_custom_background_rel(preset_rel_path(path))
        self._refresh_bg_panel()
        self._refresh_preset_marks()

    def _on_pick_avatar_preset(self, path: str):
        # 预设直接用它的路径（相对项目根），不复制一份，换回来时还能对上高亮
        set_avatar_image(preset_rel_path(path))
        self._refresh_user_previews()
        self._refresh_preset_marks()
        self._sync_pet_to_main()

    def _user_image_row(self, kind: str, _title: str, hint: str, size: int, radius: int):
        """一行「预览 + 选择图片 / 恢复默认 + 说明」，头像和桌宠形象共用。"""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        prev = QLabel()
        prev.setObjectName("userImgPreview")
        prev.setFixedSize(size, size)
        prev.setAlignment(Qt.AlignCenter)
        h.addWidget(prev, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(6)
        tip = QLabel(hint)
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        col.addWidget(tip)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        pick = QPushButton("选择图片…")
        pick.clicked.connect(lambda _=False, k=kind: self._pick_user_image(k))
        btns.addWidget(pick)
        reset = QPushButton("恢复默认")
        reset.clicked.connect(lambda _=False, k=kind: self._clear_user_image(k))
        btns.addWidget(reset)
        btns.addStretch(1)
        col.addLayout(btns)
        col.addStretch(1)
        h.addLayout(col, 1)
        setattr(self, kind + "_prev", prev)
        return row

    def _pick_user_image(self, kind: str):
        is_pet = str(kind).lower().startswith("pet")
        path, _ = QFileDialog.getOpenFileName(
            self, "选择桌宠形象" if is_pet else "选择头像图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;所有文件 (*.*)")
        if not path:
            return
        if not set_user_image(path, kind):
            QMessageBox.warning(self, "无法使用这张图",
                                "图片打不开或格式不支持，换一张试试。")
            return
        self._refresh_user_previews()
        self._refresh_preset_marks()
        self._sync_pet_to_main()

    def _clear_user_image(self, kind: str):
        if str(kind).lower().startswith("pet"):
            set_pet_image("")
        else:
            set_avatar_image("")
        clear_user_image(kind)
        self._refresh_user_previews()
        self._refresh_preset_marks()
        self._sync_pet_to_main()

    def _refresh_user_previews(self):
        """刷新两个预览框（没自定义就显示应用图标），并让主窗口立刻跟着换。"""
        for kind, size, radius in (("avatar", 64, 14), ("pet", 42, 12)):
            lbl = getattr(self, kind + "_prev", None)
            if lbl is None:
                continue
            path = get_user_image(kind)
            pm = QPixmap()
            if path and os.path.isfile(to_abs(path)):
                pm = QPixmap(to_abs(path))
                if not pm.isNull():
                    pm = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
                    if pm.width() > size or pm.height() > size:
                        pm = pm.copy((pm.width() - size) // 2, (pm.height() - size) // 2,
                                     size, size)
                    pm = rounded_pixmap(pm, radius)
            if pm.isNull():
                lbl.setPixmap(app_icon_pixmap(size, radius=radius))
                lbl.setToolTip("当前使用应用图标（未自定义）")
            else:
                lbl.setPixmap(pm)
                lbl.setToolTip(path)
        if getattr(self, "pet_preview_lbl", None) is not None:
            lines = get_pet_lines()
            self.pet_preview_lbl.setText(("试试效果：" + random.choice(lines)) if lines else "")

    def _open_path(self, path: str):
        try:
            if os.path.isdir(path):
                os.startfile(path)
            elif os.path.isfile(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            else:
                QMessageBox.information(self, "找不到", "这个位置不存在：\n%s" % path)
        except Exception as exc:
            QMessageBox.warning(self, "打不开", str(exc))

    def _sync_main_theme_widgets(self):
        """让主窗口的卡片/胶囊/玻璃层跟上当前主题与强调色。"""
        self._refresh_theme_inline()
        app = QApplication.instance()
        if app is None:
            return
        from widgets import MainWindow  # 延迟导入，避免循环依赖
        for w in app.topLevelWidgets():
            if isinstance(w, MainWindow) and hasattr(w, "_refresh_sidebar_accent"):
                w._refresh_sidebar_accent()

    def _refresh_theme_inline(self):
        """刷新本对话框里用内联样式写的、不随 QSS 自动变的控件。"""
        if getattr(self, "hover_interval_label", None) is not None:
            self.hover_interval_label.setStyleSheet(
                "color:%s;font-weight:bold;" % accent_color())
        if getattr(self, "login_status", None) is not None:
            self.login_status.setStyleSheet("color:%s;" % pstr("accent"))
        if getattr(self, "bg_status_lbl", None) is not None:
            self._refresh_bg_panel()

    def _on_theme_pick(self, _idx):
        tid = self.theme_combo.currentData()
        if tid:
            theme_manager.set_theme(str(tid))
            self._sync_main_theme_widgets()

    def _on_color_mode_pick(self, checked):
        if not checked:
            return
        btn = self.sender()
        mode = btn.property("colorMode") if btn is not None else None
        if mode:
            theme_manager.set_color_mode(str(mode))
            self._sync_main_theme_widgets()

    def _on_accent_follow_toggled(self, checked):
        """跟随主题 = 清空覆盖；取消跟随 = 先用一个默认色，用户再点色卡即可。"""
        if checked:
            set_accent_override("")
        elif not get_accent_override():
            set_accent_override(next(iter(ACCENT_PRESETS)))
        theme_manager.refresh_accent()
        self._update_accent_buttons()
        self._sync_main_theme_widgets()

    def _on_accent_pick(self, key):
        set_accent_override(key)
        if self.accent_follow_check.isChecked():
            self.accent_follow_check.blockSignals(True)
            self.accent_follow_check.setChecked(False)
            self.accent_follow_check.blockSignals(False)
        theme_manager.refresh_accent()
        self._update_accent_buttons()
        self._sync_main_theme_widgets()

    def _update_accent_buttons(self):
        cur = get_accent_override()
        follow = not bool(cur)
        self.accent_follow_check.blockSignals(True)
        self.accent_follow_check.setChecked(follow)
        self.accent_follow_check.blockSignals(False)
        for key, b in self._accent_btns.items():
            accent = ACCENT_PRESETS[key]["color"]
            if key == cur:
                b.setStyleSheet(
                    "QToolButton{background:%s;border-radius:14px;"
                    "border:3px solid rgba(255,255,255,0.85);}" % accent)
            else:
                b.setStyleSheet(
                    "QToolButton{background:%s;border-radius:14px;"
                    "border:2px solid transparent;}"
                    "QToolButton:hover{border-color:rgba(255,255,255,0.6);}" % accent)

    def _refresh_bg_panel(self):
        """刷新背景设置区块：状态文字 + 当前背景缩略图。"""
        if getattr(self, "bg_status_lbl", None) is None:
            return
        self.bg_status_lbl.setText(theme_manager.background_state_text())
        pm = QPixmap()
        src = theme_manager.background_path()
        if src and os.path.isfile(src):
            try:
                pm = _load_pix_cover(src, 180, 101)
            except Exception:
                pm = QPixmap()
        if pm.isNull():
            self.bg_preview.setPixmap(QPixmap())
            self.bg_preview.setText("无背景图\n（使用主题背景色兜底）")
            self.bg_preview.setToolTip("")
        else:
            self.bg_preview.setPixmap(pm)
            self.bg_preview.setText("")
            self.bg_preview.setToolTip(src)

    def _on_hover_interval(self, val):
        seconds = val / 10.0
        self.hover_interval_label.setText("%.1f 秒" % seconds)
        set_hover_interval(seconds)

    # ---------- 桌宠（右下角气泡）----------
    def _sync_pet_to_main(self):
        """把桌宠设置立刻同步到主窗口（不用等"保存"）。"""
        app = QApplication.instance()
        if app is None:
            return
        from widgets import MainWindow     # 延迟导入，避免循环依赖
        for w in app.topLevelWidgets():
            if isinstance(w, MainWindow) and hasattr(w, "_refresh_pet_settings"):
                w._refresh_pet_settings()

    def _pet_preview(self):
        """在本窗口里显示一句（同时让主窗口的桌宠跟着换一句）。"""
        lines = get_pet_lines()
        self.pet_preview_lbl.setText(("试试效果：" + random.choice(lines)) if lines else "")
        app = QApplication.instance()
        if app is None:
            return
        from widgets import MainWindow
        for w in app.topLevelWidgets():
            if isinstance(w, MainWindow) and hasattr(w, "_pet_say_random"):
                w._pet_say_random()

    def _on_pet_show(self, checked):
        set_assistant_hidden(not checked)
        self._sync_pet_to_main()

    def _on_pet_click(self, checked):
        set_pet_click_random(checked)
        self._sync_pet_to_main()

    def _on_pet_auto(self, _idx):
        set_pet_auto_minutes(int(self.pet_auto_combo.currentData() or 0))
        self._sync_pet_to_main()

    def _on_pet_lines_apply(self):
        set_pet_lines(self.pet_lines_edit.toPlainText())
        self.pet_lines_edit.setPlainText("\n".join(get_pet_lines()))   # 规范化回显
        self._pet_preview()

    def _on_pet_lines_reset(self):
        set_pet_lines(PET_LINES)          # 与内置相同 → 存成空，表示"用内置"
        self.pet_lines_edit.setPlainText("\n".join(PET_LINES))
        self._pet_preview()

    def _pick_bg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;所有文件 (*.*)")
        if not path:
            return
        if not theme_manager.set_custom_background(path):
            QMessageBox.warning(self, "无法使用这张图",
                                "图片复制失败或格式不支持，换一张试试。")
            return
        self._refresh_bg_panel()
        self._refresh_preset_marks()

    def _clear_bg(self):
        theme_manager.restore_theme_background()
        self._refresh_bg_panel()
        self._refresh_preset_marks()

    def _pick_cg(self):
        path = QFileDialog.getExistingDirectory(self, "选择 CG 存放根目录", get_cg_root())
        if not path:
            return
        self.cg_edit.setText(path)

    def _organize_cg_library(self):
        """把旧布局的历史图片整理进 <CG_ROOT>/<分类>/<游戏名>/ 并同步数据库。"""
        root = (self.cg_edit.text() or "").strip()
        if not root or not os.path.isdir(root):
            QMessageBox.warning(self, "目录无效", "请先选择（或填写）一个存在的 CG 存储根目录。")
            return

        # 主窗口没传 db 时，自己开一个临时连接（用完就关）
        db = self.db
        temp_db = None
        if db is None:
            try:
                temp_db = Database(DB_PATH)
                db = temp_db
            except Exception as exc:
                QMessageBox.critical(self, "无法打开数据库", str(exc))
                return
        try:
            self._run_organize_cg(root, db)
        finally:
            if temp_db is not None:
                temp_db.close()

    def _run_organize_cg(self, root: str, db):
        try:
            index = cg_library.build_index(
                db.get_all_games(), db.get_all_screenshots(),
                path_resolver=to_abs, reserved_names=CATEGORY_OPTIONS)
        except Exception as exc:
            QMessageBox.critical(self, "读取数据库失败", str(exc))
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            report = cg_library.organize_library(
                root, index, categories=CATEGORY_OPTIONS, apply=False)
        finally:
            QApplication.restoreOverrideCursor()

        if report["errors"]:
            QMessageBox.warning(
                self, "无法整理",
                "扫描时出错：\n%s" % "\n".join(str(e) for e in report["errors"][:5]))
            return
        moves = report["moves"]
        if not moves:
            QMessageBox.information(self, "无需整理", "没有发现需要整理的旧布局图片。")
            return

        preview = "\n".join("  %s  ->  %s" % (os.path.basename(s), os.path.basename(d))
                            for s, d in moves[:8])
        if len(moves) > 8:
            preview += "\n  …还有 %d 张" % (len(moves) - 8)
        if not ask_yes_no(
                self, "整理本地 CG 图库",
                "将把 %d 张图片移动到各自游戏名的文件夹：\n\n%s\n\n"
                "移动后数据库里的截图路径会同步更新，确定继续？" % (len(moves), preview)):
            return

        self.cg_organize_btn.setEnabled(False)
        self.cg_organize_btn.setText("整理中…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            report = cg_library.organize_library(
                root, index, categories=CATEGORY_OPTIONS, apply=True)
            mapping = cg_library.remap_screenshot_paths(
                db.get_all_screenshots(), report["moved"], path_resolver=to_abs)
            changed = db.update_screenshot_paths(mapping)
        except Exception as exc:
            QMessageBox.critical(self, "整理出错", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.cg_organize_btn.setEnabled(True)
            self.cg_organize_btn.setText("整理历史图片到游戏文件夹")

        msg = "已整理 %d 张图片，同步更新 %d 条截图记录。" % (
            len(report["moved"]), changed)
        if report["errors"]:
            msg += "\n\n有 %d 项失败：\n%s" % (
                len(report["errors"]),
                "\n".join("%s: %s" % (os.path.basename(e[0]), e[1])
                          for e in report["errors"][:5]))
        QMessageBox.information(self, "整理完成", msg)

    def _open_token_page(self):
        QDesktopServices.openUrl(QUrl("https://next.bgm.tv/demo/access-token"))

    def _open_bgm_profile(self):
        user = get_bgm_username()
        if not user:
            QMessageBox.information(self, "提示", "尚未登录，无法打开个人主页。请先登录。")
            return
        QDesktopServices.openUrl(QUrl("https://bgm.tv/user/%s" % urllib.parse.quote(user)))

    def _logout(self):
        if not get_bgm_token():
            QMessageBox.information(self, "提示", "当前未登录 Bangumi。")
            return
        if not ask_yes_no(self, "退出 Bangumi",
                          "将删除本机保存的 Bangumi 令牌并退出登录，确定？"):
            return
        set_bgm_token("")
        set_bgm_username("")
        set_bgm_nickname("")
        self.bgm_edit.clear()
        self.login_btn.setEnabled(True)
        self.login_btn.setText("验证并登录")
        self._refresh_login_status()
        QMessageBox.information(self, "完成", "已退出 Bangumi，令牌已删除。")

    def _refresh_login_status(self):
        token = get_bgm_token()
        user = get_bgm_username()
        nick = get_bgm_nickname()
        if token and user:
            self.login_status.setText("当前已登录：%s（%s）" % (nick or user, user))
        elif token:
            self.login_status.setText("已填令牌，但尚未验证登录（点“验证并登录”）。")
        else:
            self.login_status.setText("尚未登录：先创建并粘贴令牌，再点“验证并登录”。")

    def _verify_login(self):
        token = self.bgm_edit.text().strip()
        if not token:
            QMessageBox.information(self, "提示", "请先粘贴 Bangumi 令牌（可点“打开令牌页”获取）。")
            return
        set_bgm_token(token)
        self._refresh_login_status()
        self.login_btn.setEnabled(False)
        self.login_btn.setText("验证中…")
        self.login_status.setText("正在验证令牌…")
        self.login_worker = BangumiLoginWorker(token, None)
        self.login_worker.success.connect(self._on_login_done)
        self.login_worker.failed.connect(self._on_login_fail)
        _orphan_worker(self.login_worker)
        self.login_worker.start()

    def _on_login_done(self, username, nickname):
        self.login_btn.setEnabled(True)
        self.login_btn.setText("验证并登录")
        if not username:
            self._refresh_login_status()
            QMessageBox.warning(self, "登录失败", "未能获取用户名，请确认令牌有效。")
            return
        set_bgm_username(username)
        set_bgm_nickname(nickname)
        self._refresh_login_status()
        QMessageBox.information(self, "登录成功",
                                "已登录 Bangumi：%s（%s）" % (nickname or username, username))

    def _on_login_fail(self, msg):
        self.login_btn.setEnabled(True)
        self.login_btn.setText("验证并登录")
        self._refresh_login_status()
        QMessageBox.warning(self, "登录失败", "无法验证 Bangumi 令牌：\n%s" % msg)

    def _save(self):
        set_sgdb_key(self.sgdb_edit.text())
        set_bgm_token(self.bgm_edit.text())
        set_sauce_key(self.sauce_edit.text())
        set_hover_size(self.hover_combo.currentData())
        set_hover_interval(self.hover_interval_slider.value() / 10.0)
        set_cg_root(self.cg_edit.text())
        # 主题/颜色模式/强调色/自定义背景已在选择时通过 ThemeManager 立即持久化
        # 桌宠
        set_assistant_hidden(not self.pet_show_check.isChecked())
        set_pet_click_random(self.pet_click_check.isChecked())
        set_pet_auto_minutes(int(self.pet_auto_combo.currentData() or 0))
        set_pet_lines(self.pet_lines_edit.toPlainText())
        if not self.bgm_edit.text().strip():
            set_bgm_username("")
            set_bgm_nickname("")
        _apply_theme()
        _apply_bg()
        self._sync_pet_to_main()
        QMessageBox.information(self, "完成", "已保存设置。")
        self.accept()


# ============================================================
# 主窗口
# ============================================================
