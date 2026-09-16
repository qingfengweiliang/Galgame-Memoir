# -*- coding: utf-8 -*-
"""公共基础模块：路径常量、设置读写、通用工具、图片工具。

本模块不依赖任何业务模块（数据库/网络/UI），供其他模块 import。
"""

import os
import sys
import re
import json
import time
import hashlib
import shutil
import datetime

import theme_defs
from cg_library import THUMB_DIR_NAME

try:
    from PySide6.QtCore import Qt, QSize, QPoint, QRect, QRectF
    from PySide6.QtGui import QPixmap, QIcon, QFont, QImage, QPainter, QColor, QPainterPath, QPen
    from PySide6.QtWidgets import (
        QApplication, QWidget, QPushButton, QToolButton, QLabel, QVBoxLayout, QHBoxLayout,
        QMessageBox,
    )
    from PIL import Image, ImageOps
except ImportError as exc:  # 缺少第三方库时友好提示
    print("缺少必要的第三方库，请先执行：pip install PySide6 requests pillow")
    print("详细错误：", exc)
    sys.exit(1)


# ============================================================
# 全局常量：目录与路径
# ============================================================
# 项目根目录：src 的上一级（data、covers 等都保留在项目根目录，不随 src 移动）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
SCREENSHOTS_DIR = os.path.join(DATA_DIR, "screenshots")
CG_STORAGE_ROOT = r"E:\cg存储"   # 截图的默认保存根目录（按分类存放）
DB_PATH = os.path.join(DATA_DIR, "galgame.db")

PAGE_SIZE = 50          # 每页显示的网格卡片数（分页加载，避免一次性加载上千张卡死）

# 悬浮 CG 轮播间隔（秒）：可在设置页实时调整，取值范围 0.5 ~ 3.0
HOVER_INTERVAL_MIN = 0.5
HOVER_INTERVAL_MAX = 3.0
DEFAULT_HOVER_INTERVAL = 1.8    # 仅在设置里从未保存过该项时使用的兜底值

# 缩略图生成尺寸上限（只影响"新导入"的截图，生成逻辑不变，仅尺寸参数）
THUMB_MAX_SIZE = 640

STATUS_OPTIONS = ["想玩", "正在玩", "搁置", "通关", "放弃"]
CATEGORY_OPTIONS = ["CG", "背景", "立绘", "其他"]

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

# ---- 应用名称与图标（全局改名只需改这里）----
APP_NAME = "Galgame Memoir"
APP_SUBTITLE = "你的私人收藏馆"
APP_VERSION = "V1.0"
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
APP_ICON_PNG = os.path.join(ASSETS_DIR, "app_icon.png")
APP_ICON_ICO = os.path.join(ASSETS_DIR, "app_icon.ico")

# Bangumi API 要求带上 User-Agent
BANGUMI_UA = "GalgameInfoManager/1.0 (local offline desktop app)"

SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
_SETTINGS = {}


# ============================================================
# 设置读写
# ============================================================
def _load_settings() -> dict:
    global _SETTINGS
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                _SETTINGS = json.load(f) or {}
        except Exception:
            _SETTINGS = {}
    return _SETTINGS


def _save_settings():
    global _SETTINGS
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(_SETTINGS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _ensure_loaded():
    """确保 _SETTINGS 已从磁盘加载，避免 setters 覆盖丢数据。"""
    if not _SETTINGS:
        _load_settings()


def get_sgdb_key() -> str:
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("sgdb_key", "") or "")


def set_sgdb_key(key: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["sgdb_key"] = str(key or "").strip()
    _save_settings()


def get_bgm_token() -> str:
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("bgm_token", "") or "")


def set_bgm_token(token: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["bgm_token"] = str(token or "").strip()
    _save_settings()


def get_bgm_username() -> str:
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("bgm_username", "") or "")


def set_bgm_username(name: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["bgm_username"] = str(name or "").strip()
    _save_settings()


def get_bgm_nickname() -> str:
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("bgm_nickname", "") or "")


def set_bgm_nickname(name: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["bgm_nickname"] = str(name or "").strip()
    _save_settings()


def get_cg_root() -> str:
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("cg_root", CG_STORAGE_ROOT) or CG_STORAGE_ROOT)


def set_cg_root(path: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["cg_root"] = (str(path or "").strip() or CG_STORAGE_ROOT)
    _save_settings()


def _qt_system_dark():
    """Qt 6 系统深浅色；拿不到时返回 None。"""
    try:
        app = QApplication.instance()
        if app is None:
            return None
        scheme = app.styleHints().colorScheme()
        if hasattr(Qt, "ColorScheme"):
            return scheme == Qt.ColorScheme.Dark
    except Exception:
        pass
    return None


def get_theme_id() -> str:
    """当前主题 id（9 套之一）。"""
    if not _SETTINGS:
        _load_settings()
    tid = str(_SETTINGS.get("theme_id", theme_defs.DEFAULT_THEME_ID) or theme_defs.DEFAULT_THEME_ID)
    return tid if tid in theme_defs.THEME_DEFS else theme_defs.DEFAULT_THEME_ID


def set_theme_id(theme_id: str):
    global _SETTINGS
    _ensure_loaded()
    tid = str(theme_id or "").strip()
    _SETTINGS["theme_id"] = tid if tid in theme_defs.THEME_DEFS else theme_defs.DEFAULT_THEME_ID
    _save_settings()


def get_color_mode() -> str:
    """颜色模式：light / dark / system。

    升级兼容按确认要求：旧 theme 不参与映射，新键缺失时回默认 light；
    旧键原样保留在 settings.json 中，不删除。
    """
    if not _SETTINGS:
        _load_settings()
    mode = str(_SETTINGS.get("color_mode", theme_defs.DEFAULT_COLOR_MODE) or theme_defs.DEFAULT_COLOR_MODE)
    return mode if mode in ("light", "dark", "system") else theme_defs.DEFAULT_COLOR_MODE


def set_color_mode(mode: str):
    global _SETTINGS
    _ensure_loaded()
    mode = str(mode or "").strip()
    _SETTINGS["color_mode"] = mode if mode in ("light", "dark", "system") else theme_defs.DEFAULT_COLOR_MODE
    _save_settings()


def get_effective_mode() -> str:
    """把 system 解析成实际 light/dark。"""
    mode = get_color_mode()
    if mode in ("light", "dark"):
        return mode
    qt_dark = _qt_system_dark()
    if qt_dark is not None:
        return "dark" if qt_dark else "light"
    try:
        import darkdetect
        return "dark" if darkdetect.isDark() else "light"
    except Exception:
        return "light"


# 兼容旧调用：旧 theme 只表示浅/深开关，不再参与 9 套主题数据。
def get_theme() -> str:
    return get_effective_mode()


def set_theme(mode: str):
    set_color_mode("dark" if str(mode) == "dark" else "light")


ACCENT_PRESETS = {
    "royal":      {"name": "蓝紫",   "color": "#8B7CF6", "hover": "#A99BFF", "soft": "#E4E0FD"},
    "pink":       {"name": "樱花粉", "color": "#FF6FA8", "hover": "#FF8FB8", "soft": "#FFD9E4"},
    "rose":       {"name": "玫红",   "color": "#FF4D79", "hover": "#FF6E92", "soft": "#FFD0DC"},
    "violet":     {"name": "紫罗兰", "color": "#B06FD8", "hover": "#C28BE4", "soft": "#E6D6F5"},
    "purple":     {"name": "深紫",   "color": "#8E5CC8", "hover": "#A578DD", "soft": "#E3D5F5"},
    "cyber_blue": {"name": "赛博蓝", "color": "#0A84FF", "hover": "#3A9BFF", "soft": "#C9E3FF"},
    "navy":       {"name": "深海蓝", "color": "#2E6FE0", "hover": "#4C8BEE", "soft": "#CFDDF5"},
    "teal":       {"name": "青绿",   "color": "#3ECFB2", "hover": "#63DCC2", "soft": "#C9F2E9"},
    "mint":       {"name": "薄荷绿", "color": "#2BB887", "hover": "#52CBA0", "soft": "#C6EFDF"},
    "orange":     {"name": "暖橙",   "color": "#F5852E", "hover": "#F79D55", "soft": "#FBE0C6"},
    "gold":       {"name": "金色",   "color": "#D9A62B", "hover": "#E4BC52", "soft": "#F5E6BF"},
    "red":        {"name": "正红",   "color": "#E5484D", "hover": "#EE6B70", "soft": "#F8D3D4"},
    "sky":        {"name": "天蓝",   "color": "#45B8E8", "hover": "#6BC8EF", "soft": "#CFEAF6"},
}

# 旧默认强调色（只作兼容哨兵，不再参与 9 套主题的主计算）。
DEFAULT_ACCENT = "royal"


def _mix_hex(c1: str, c2: str, t: float) -> str:
    """两个 #RRGGBB 按比例混合，用于派生强调色 hover/soft。"""
    try:
        a, b = QColor(str(c1)), QColor(str(c2))
        t = max(0.0, min(1.0, float(t)))
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        ).name()
    except Exception:
        return str(c1)


def get_accent_override() -> str:
    """旧 13 色强调色覆盖；空字符串表示“跟随当前主题”。"""
    if not _SETTINGS:
        _load_settings()
    a = str(_SETTINGS.get("accent_override", "") or "")
    return a if a in ACCENT_PRESETS else ""


def set_accent_override(name: str):
    global _SETTINGS
    _ensure_loaded()
    name = str(name or "").strip()
    _SETTINGS["accent_override"] = name if name in ACCENT_PRESETS else ""
    _save_settings()


# 兼容旧名：旧 accent 设置不再自动覆盖主题，只有显式调用才写入 accent_override。
def get_accent() -> str:
    return get_accent_override() or DEFAULT_ACCENT


def set_accent(name: str):
    set_accent_override(name)


def _theme_mode_data() -> dict:
    item = theme_defs.THEME_DEFS[get_theme_id()]
    return item["dark" if get_effective_mode() == "dark" else "light"]


def accent_color() -> str:
    override = get_accent_override()
    if override:
        return ACCENT_PRESETS[override]["color"]
    return theme_defs.theme_accent(get_theme_id(), get_effective_mode())


def accent_hover() -> str:
    override = get_accent_override()
    if override:
        return ACCENT_PRESETS[override]["hover"]
    return _mix_hex(accent_color(), "#FFFFFF", 0.20)


def accent_soft() -> str:
    override = get_accent_override()
    if override:
        return ACCENT_PRESETS[override]["soft"]
    return _mix_hex(accent_color(), _theme_mode_data()["card"], 0.82)


def get_hover_size() -> str:
    if not _SETTINGS:
        _load_settings()
    s = str(_SETTINGS.get("hover_size", "medium") or "medium")
    return s if s in ("small", "medium", "large") else "medium"


def set_hover_size(s: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["hover_size"] = s if s in ("small", "medium", "large") else "medium"
    _save_settings()


def get_hover_interval() -> float:
    if not _SETTINGS:
        _load_settings()
    try:
        v = float(_SETTINGS.get("hover_interval", DEFAULT_HOVER_INTERVAL) or DEFAULT_HOVER_INTERVAL)
    except Exception:
        v = DEFAULT_HOVER_INTERVAL
    return max(HOVER_INTERVAL_MIN, min(HOVER_INTERVAL_MAX, v))


def set_hover_interval(v):
    global _SETTINGS
    _ensure_loaded()
    try:
        v = float(v)
    except Exception:
        v = DEFAULT_HOVER_INTERVAL
    _SETTINGS["hover_interval"] = max(HOVER_INTERVAL_MIN, min(HOVER_INTERVAL_MAX, v))
    _save_settings()


def _custom_bg_dir() -> str:
    d = os.path.join(DATA_DIR, "backgrounds")
    os.makedirs(d, exist_ok=True)
    return d


def get_custom_background_path() -> str:
    """自定义背景路径；空字符串表示使用主题自带背景。

    升级兼容按确认要求：旧 bg_image 不再自动迁移为新背景，新键缺失时返回默认空值；
    旧键原样保留，不删除任何原文件。
    """
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("custom_background_path", "") or "")


def set_custom_background_path(path: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["custom_background_path"] = str(path or "").strip()
    _save_settings()


def save_custom_background(src_path: str) -> str:
    """把用户选择的背景图收进 data/backgrounds/，返回相对路径。

    只复制，不移动、不删除原文件；这样用户原图被挪走也不影响应用。
    """
    src = to_abs(src_path) if src_path else ""
    if not src or not os.path.isfile(src):
        return ""
    ext = os.path.splitext(src)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
        ext = ".jpg"
    try:
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        tag = hashlib.md5((src + str(time.time_ns())).encode("utf-8", "ignore")).hexdigest()[:8]
        dst = os.path.join(_custom_bg_dir(), "custom_%s_%s%s" % (stamp, tag, ext))
        shutil.copyfile(src, dst)
    except Exception:
        return ""
    return os.path.relpath(dst, BASE_DIR).replace("\\", "/")


# 兼容旧名：只读写旧键，不再作为主背景来源，保证旧配置不被破坏。
def get_bg_image() -> str:
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("bg_image", "") or "")


def set_bg_image(path: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["bg_image"] = str(path or "").strip()
    _save_settings()


def get_sauce_key() -> str:
    """SauceNAO API Key（识图用，需注册获取）。"""
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("sauce_key", "") or "")


def set_sauce_key(key: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["sauce_key"] = str(key or "").strip()
    _save_settings()


def get_avatar_image() -> str:
    """侧边栏头像块的图片（留空则用应用图标）。"""
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("avatar_image", "") or "")


def set_avatar_image(path: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["avatar_image"] = str(path or "").strip()
    _save_settings()


def get_pet_image() -> str:
    """桌宠气泡里的形象图（留空则用应用图标）。"""
    if not _SETTINGS:
        _load_settings()
    return str(_SETTINGS.get("pet_image", "") or "")


def set_pet_image(path: str):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["pet_image"] = str(path or "").strip()
    _save_settings()


# ---- 用户自选图片（头像 / 桌宠形象）统一存进 data/user/，免得原图被挪走后失效 ----
USER_FILES = {"avatar": "avatar", "pet": "pet"}


def _user_dir() -> str:
    d = os.path.join(DATA_DIR, "user")
    os.makedirs(d, exist_ok=True)
    return d


def save_user_image(src_path: str, kind: str) -> str:
    """把用户选的图片收进 data/user/，返回相对路径（相对项目根，写进设置里）。

    会自动去掉旧文件、缩到 1024 以内（头像/桌宠用不到大图），
    这样即使原图之后被删掉或移动，头像和桌宠形象依旧有效。
    """
    kind = "pet" if str(kind).lower().startswith("pet") else "avatar"
    src = to_abs(src_path) if src_path else ""
    if not src or not os.path.isfile(src):
        return ""
    d = _user_dir()
    for old in os.listdir(d):
        if old.startswith(kind + "."):
            try:
                os.remove(os.path.join(d, old))
            except Exception:
                pass
    ext = os.path.splitext(src)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
        ext = ".png"
    dst = os.path.join(d, kind + ext)
    try:
        img = QImage(src)
        if img.isNull():
            raise ValueError("无法解码")
        if max(img.width(), img.height()) > 1024:
            img = img.scaled(1024, 1024, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if img.format() not in (QImage.Format_PNG, QImage.Format_ARGB32, QImage.Format_ARGB32_Premultiplied):
            pass
        if not img.save(dst):
            raise ValueError("保存失败")
    except Exception:
        try:
            shutil.copyfile(src, dst)
        except Exception:
            return ""
    return os.path.relpath(dst, BASE_DIR).replace("\\", "/")


def clear_user_image(kind: str):
    """删掉 data/user/ 下的头像或桌宠图（不影响设置里的值，调用方自己清）。"""
    kind = "pet" if str(kind).lower().startswith("pet") else "avatar"
    d = _user_dir()
    for old in os.listdir(d):
        if old.startswith(kind + "."):
            try:
                os.remove(os.path.join(d, old))
            except Exception:
                pass


def set_user_image(src_path: str, kind: str) -> str:
    """选择图片 -> 收进 data/user/ 并写进设置；返回可用的相对路径。"""
    rel = save_user_image(src_path, kind)
    if rel:
        (set_pet_image if str(kind).lower().startswith("pet") else set_avatar_image)(rel)
    return rel


def get_user_image(kind: str) -> str:
    return get_pet_image() if str(kind).lower().startswith("pet") else get_avatar_image()


# ---- 预设图片目录：把图片丢进这两个文件夹，设置页会列成缩略图直接点选 ----
PRESET_DIRS = {
    "avatar": os.path.join(DATA_DIR, "profile photo"),   # 头像预设
    "bg": os.path.join(DATA_DIR, "wallpapers"),          # 背景图预设
}


def get_preset_dir(kind: str) -> str:
    """预设目录（kind: "avatar" / "bg"）。"""
    return PRESET_DIRS["bg" if str(kind).lower().startswith("bg") else "avatar"]


def list_presets(kind: str) -> list:
    """列出预设目录里的图片（按文件名排序；忽略以 _ 或 . 开头的文件）。"""
    d = get_preset_dir(kind)
    if not os.path.isdir(d):
        return []
    out = []
    try:
        for name in sorted(os.listdir(d)):
            if name.startswith("_") or name.startswith("."):
                continue
            p = os.path.join(d, name)
            if os.path.isfile(p) and name.lower().endswith(IMAGE_EXTENSIONS):
                out.append(p)
    except Exception:
        return []
    return out


def preset_rel_path(path: str) -> str:
    """预设图片在设置里存成"相对项目根"的路径，整包搬走也不会失效。"""
    try:
        return os.path.relpath(path, BASE_DIR).replace("\\", "/")
    except Exception:
        return path


def get_assistant_hidden() -> bool:
    """右下角助手气泡是否已关闭。"""
    if not _SETTINGS:
        _load_settings()
    return bool(_SETTINGS.get("assistant_hidden", 0))


def set_assistant_hidden(hidden: bool):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["assistant_hidden"] = 1 if hidden else 0
    _save_settings()


# ============================================================
# 桌宠（右下角气泡）
#   气泡本身是纯装饰：点一下随机说一句，句子池可在「设置 → 桌宠」里替换。
#   内置句子只放在这里，不写进数据库，也不影响任何游戏数据。
# ============================================================
PET_LINES = [
    "今天想攻略哪条线？",
    "存档了吗？别又白跑一遍哦。",
    "又到了该选支线的时候了。",
    "这条线我还没走完呢……",
    "好感度 +1。",
    "按保存之前，先深呼吸一下。",
    "BAD END 也是结局的一部分。",
    "别跳过 OP，很好听的。",
    "通关纪念日，要不要记下来？",
    "CG 收集率又高了一点点。",
    "别熬夜了，明天再推也不迟。",
    "选项要慎重，存档更重要。",
    "这句台词，我记了很久。",
    "慢慢来，故事不会跑掉的。",
    "第二遍看，感受会完全不一样。",
    "把喜欢的作品写进备注里吧。",
    "想推的太多了，先去睡吧。",
    "今天的收获不错嘛。",
    "好像触发隐藏剧情了！",
    "要一起重看那段 CG 吗？",
    "这条线的主角，似乎有点犹豫。",
    "第一次通关的心情，值得记住。",
    "别让喜欢的故事只有三分钟热度。",
    "来，给你一颗糖，继续吧。",
    "书架又厚了一点呢。",
    "下一部想推什么？",
    "把结局留给明天，也挺浪漫的。",
    "你收藏的每一部，都是一段回忆。",
    "窗外天亮了，真的该睡了。",
    "能遇见喜欢的故事，真好。",
]


def get_pet_lines() -> list:
    """桌宠的句子池：用户在设置里填过就用自定义的，否则用内置的。"""
    if not _SETTINGS:
        _load_settings()
    raw = _SETTINGS.get("pet_lines", "")
    if isinstance(raw, (list, tuple)):
        lines = [str(s).strip() for s in raw]
    else:
        lines = [s.strip() for s in str(raw or "").splitlines()]
    lines = [s for s in lines if s]
    return lines or list(PET_LINES)


def set_pet_lines(lines):
    """传 list / 多行字符串都行；传空（或与内置相同）就存成空，表示"用内置"。"""
    global _SETTINGS
    _ensure_loaded()
    if isinstance(lines, (list, tuple)):
        items = [str(s).strip() for s in lines]
    else:
        items = [s.strip() for s in str(lines or "").splitlines()]
    items = [s for s in items if s]
    if items == list(PET_LINES):
        items = []
    _SETTINGS["pet_lines"] = items
    _save_settings()


def get_pet_click_random() -> bool:
    """点击桌宠时是否随机换一句话（默认开）。"""
    if not _SETTINGS:
        _load_settings()
    return bool(_SETTINGS.get("pet_click_random", 1))


def set_pet_click_random(on: bool):
    global _SETTINGS
    _ensure_loaded()
    _SETTINGS["pet_click_random"] = 1 if on else 0
    _save_settings()


def get_pet_auto_minutes() -> int:
    """每隔几分钟自动换一句话（0 = 关闭）。"""
    if not _SETTINGS:
        _load_settings()
    try:
        return max(0, int(_SETTINGS.get("pet_auto_minutes", 0) or 0))
    except (TypeError, ValueError):
        return 0


def set_pet_auto_minutes(minutes: int):
    global _SETTINGS
    _ensure_loaded()
    try:
        m = max(0, int(minutes))
    except (TypeError, ValueError):
        m = 0
    _SETTINGS["pet_auto_minutes"] = m
    _save_settings()


def _hover_box_size():
    """返回悬浮预览框的 (宽, 高)。"""
    s = get_hover_size()
    return {"small": (200, 150), "medium": (260, 190), "large": (330, 230)}.get(s, (260, 190))


# ============================================================
# 通用工具函数
# ============================================================
def ensure_directories():
    """确保 data 相关文件夹存在。"""
    for folder in (DATA_DIR, COVERS_DIR, SCREENSHOTS_DIR,
                   os.path.join(DATA_DIR, "backgrounds")):
        os.makedirs(folder, exist_ok=True)


def to_abs(rel_path: str) -> str:
    """将数据库中的路径转为绝对路径；绝对路径（如 E:\\...）原样返回。"""
    if not rel_path:
        return ""
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(BASE_DIR, *rel_path.replace("\\", "/").split("/"))


def normalize_rel(path: str) -> str:
    """将路径规范化为相对路径并统一用 '/' 分隔，供数据库存储。"""
    if not path:
        return ""
    return path.replace("\\", "/")


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fmt_rating(v) -> str:
    """把评分格式化为用户友好字符串；0 显示为“未评分”。"""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v <= 0:
        return "未评分"
    if v == int(v):
        return str(int(v))
    return ("%.1f" % v).rstrip("0").rstrip(".")


def delete_cover_if_unused(db, cover_path: str):
    """删除封面文件，但只在没有任何游戏再引用它时执行。

    这样封面按内容去重后，多个游戏共用一张图时，删掉其中一个游戏不会误删封面。
    """
    if not cover_path:
        return
    try:
        if hasattr(db, "count_cover_refs") and db.count_cover_refs(cover_path) > 0:
            return
        p = to_abs(cover_path)
        covers_root = os.path.abspath(COVERS_DIR)
        abs_p = os.path.abspath(p)
        # 只允许删除 data/covers/ 内的文件，避免误删用户原始图片
        if (os.path.normcase(abs_p).startswith(os.path.normcase(covers_root) + os.sep)
                and os.path.isfile(p)):
            os.remove(p)
    except Exception:
        pass


def delete_game_and_files(db, game_id: int):
    """删除一款游戏：清理截图文件与无人引用的封面，再删除数据库记录。"""
    g = db.get_game(game_id)
    cover_rel = (g or {}).get("cover_path", "") or ""
    sdir = os.path.join(SCREENSHOTS_DIR, str(game_id))
    if os.path.isdir(sdir):
        shutil.rmtree(sdir, ignore_errors=True)
    # 本地 CG：<根目录>/<分类>/<游戏名>/ 下该游戏的文件（文件名以 gameId_ 开头）；
    # 同时兼容旧的 <根目录>/<分类>/<gameId>_... 平铺布局
    roots = {CG_STORAGE_ROOT, get_cg_root()}
    prefix = str(game_id) + "_"
    for root in roots:
        if not os.path.isdir(root):
            continue
        for cat in CATEGORY_OPTIONS:
            cat_dir = os.path.join(root, cat)
            if not os.path.isdir(cat_dir):
                continue
            for dirpath, _dirnames, filenames in os.walk(cat_dir):
                for fn in filenames:
                    if not fn.startswith(prefix):
                        continue
                    try:
                        os.remove(os.path.join(dirpath, fn))
                    except OSError:
                        pass
            # 删掉被清空的游戏名文件夹（只处理分类目录下的一层）
            try:
                for name in os.listdir(cat_dir):
                    sub = os.path.join(cat_dir, name)
                    if os.path.isdir(sub) and not os.listdir(sub):
                        try:
                            os.rmdir(sub)
                        except OSError:
                            pass
            except OSError:
                pass
    db.delete_game(game_id)
    delete_cover_if_unused(db, cover_rel)


_ZOMBIE_WORKERS = []


def ask_yes_no(parent, title: str, text: str) -> bool:
    """二次确认对话框，使用中文“是 / 否”按钮，返回 True=是。"""
    mb = QMessageBox(parent)
    mb.setWindowTitle(title)
    mb.setText(text)
    yes_btn = mb.addButton("是", QMessageBox.YesRole)
    mb.addButton("否", QMessageBox.NoRole)
    mb.setDefaultButton(yes_btn)
    mb.exec()
    return mb.clickedButton() is yes_btn


def _orphan_worker(worker):
    """把仍在运行的线程交给模块级列表托管，避免其随窗口销毁而崩溃。"""
    _ZOMBIE_WORKERS.append(worker)
    worker.finished.connect(lambda w=worker: _release_worker(w))


def _release_worker(worker):
    try:
        if worker in _ZOMBIE_WORKERS:
            _ZOMBIE_WORKERS.remove(worker)
    except ValueError:
        pass


# ============================================================
# 图片工具函数
# ============================================================
def make_placeholder_pixmap(w: int, h: int, text: str) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(QColor(240, 240, 240))
    p = QPainter(pm)
    p.setPen(QColor(150, 150, 150))
    f = QFont()
    f.setPointSize(13)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    return pm


def _transpose(img):
    """安全地按 EXIF 方向旋转图片；旧版本 Pillow 无此函数时原样返回。"""
    try:
        return ImageOps.exif_transpose(img)
    except Exception:
        return img.copy()


def load_cover_icon(rel_path: str, size: QSize) -> QIcon:
    """从相对路径加载封面并生成缩放图标，失败则返回占位图。"""
    if rel_path:
        abs_path = to_abs(rel_path)
        if os.path.isfile(abs_path):
            img = QImage(abs_path)
            if not img.isNull():
                scaled = img.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pm = QPixmap(size.width(), size.height())
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.drawPixmap((size.width() - scaled.width()) // 2,
                             (size.height() - scaled.height()) // 2,
                             QPixmap.fromImage(scaled))
                p.end()
                return QIcon(pm)
    return QIcon(make_placeholder_pixmap(size.width(), size.height(), "无封面"))


def load_cover_icon_center(rel_path: str, size: QSize) -> QIcon:
    """加载封面并完整等比缩放、居中显示，四周留白用透明填充（仅显示用，不改原图）。"""
    if rel_path:
        abs_path = to_abs(rel_path)
        if os.path.isfile(abs_path):
            img = QImage(abs_path)
            if not img.isNull():
                scaled = img.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pm = QPixmap(size.width(), size.height())
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.drawPixmap((size.width() - scaled.width()) // 2,
                             (size.height() - scaled.height()) // 2,
                             QPixmap.fromImage(scaled))
                p.end()
                return QIcon(pm)
    pm = make_placeholder_pixmap(size.width(), size.height(), "无封面")
    return QIcon(pm)


def load_thumb_qpixmap(rel_path: str, size: QSize) -> QPixmap:
    """加载图片并缩放，返回 QPixmap，失败返回占位图。"""
    if rel_path:
        abs_path = to_abs(rel_path)
        if os.path.isfile(abs_path):
            img = QImage(abs_path)
            if not img.isNull():
                scaled = img.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                return QPixmap.fromImage(scaled)
    return make_placeholder_pixmap(size.width(), size.height(), "图片")


def thumbs_rel_path(orig_rel_path: str) -> str:
    """依据原图路径推导缩略图路径。

    存储约定：缩略图放在原图同目录下的 ``缩略图`` 子文件夹里::

        <...>/<游戏名>/xxx.jpg  ->  <...>/<游戏名>/缩略图/xxx_thumb.jpg

    兼容旧布局（缩略图与原图同级）的路径由调用方按需再兜底，这里只给新约定。
    """
    if not orig_rel_path:
        return ""
    p = str(orig_rel_path).replace("\\", "/")
    folder, _, name = p.rpartition("/")
    stem, _ = os.path.splitext(name)
    thumb = stem + "_thumb.jpg"
    if folder:
        return "%s/%s/%s" % (folder, THUMB_DIR_NAME, thumb)
    return "%s/%s" % (THUMB_DIR_NAME, thumb)


def _load_pix_fast(path: str, w: int, h: int) -> QPixmap:
    """用 QImageReader 按比例缩放以完整显示（不裁剪），解码更快、更省内存。"""
    from PySide6.QtGui import QImageReader
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        scaled = size.scaled(QSize(w, h), Qt.KeepAspectRatio)
        reader.setScaledSize(scaled)
    img = reader.read()
    if img.isNull():
        return QPixmap()
    return QPixmap.fromImage(img)


def _load_pix_cover(path: str, w: int, h: int) -> QPixmap:
    """按 cover 方式缩放（保持比例、放大填满、居中裁切），避免悬浮窗残留透明/黑边。"""
    from PySide6.QtGui import QImageReader
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        scaled = size.scaled(QSize(w, h), Qt.KeepAspectRatioByExpanding)
        reader.setScaledSize(scaled)
    img = reader.read()
    if img.isNull():
        return QPixmap()
    if img.width() > w or img.height() > h:
        cx = max(0, (img.width() - w) // 2)
        cy = max(0, (img.height() - h) // 2)
        img = img.copy(cx, cy, w, h)
    return QPixmap.fromImage(img)
