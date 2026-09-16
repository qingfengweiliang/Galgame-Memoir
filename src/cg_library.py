# -*- coding: utf-8 -*-
"""本地 CG 图库：按「游戏」归类、扫描与整理。

为什么需要它
------------
「随机 CG 预览」里的「作品名」筛选原先只有主图库（illlights）有数据；本地 CG
没有任何游戏维度，所以本地模式下的筛选列表是错的。本模块给本地 CG 补上
「图片 → 游戏名」的判定，供 `random_cg_api.RandomCGFetcher` 扫描 / 筛选，
同时供“上传存盘”和“历史图片整理”复用。

存储布局
--------
新布局（上传时自动创建，按游戏名分子文件夹）::

    <CG_ROOT>/<分类>/<游戏名>/<gameId>_<时间戳>_<原名>.<ext>
    <CG_ROOT>/<分类>/<游戏名>/<缩略图子文件夹>/<gameId>_<时间戳>_<原名>_thumb.jpg

兼容的旧布局（历史图片，不动它也能被正确归类）::

    <CG_ROOT>/<分类>/<gameId>_<时间戳>_<原名>.<ext>
    <data>/screenshots/<gameId>/...

游戏归属的判定依据（优先级从高到低）
------------------------------------
1. 图片所在目录名就是一款已知游戏名（或原名 title_jp）→ 该游戏（新布局，最可靠）
2. 目录名为「未分类」→ 未分类
3. 数据库 screenshots.file_path 精确命中 → 该记录挂载的游戏
4. 文件名前缀 ``<gameId>_``（本程序上传时的命名规则）→ 该 gameId 对应的游戏
5. 以上都判不出来 → 「未分类」

第 3 / 4 条就是历史图片的兜底依据：旧布局的文件名一定带 gameId，
gameId 又能通过 games 表映射到游戏名。二者都没有的（用户手动丢进来的图）
统一归入「未分类」，不会丢失也不会误判。

本模块只依赖标准库，不 import Qt / config / database，方便被网络层、
后台线程或命令行单独使用。
"""

import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# 判断不出游戏时的兜底分类（同时用作文件夹名）
UNCLASSIFIED = "未分类"
# 本地图库下拉里“不过滤”的显示文案（由 UI 使用）
ALL_GAMES_LABEL = "全部作品"
# 缩略图子文件夹名：<CG_ROOT>/<分类>/<游戏名>/<THUMB_DIR_NAME>/<原名>_thumb.jpg
THUMB_DIR_NAME = "缩略图"

# 本程序会处理 / 扫描的图片后缀
DEFAULT_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

# 文件名里 gameId 的两种识别规则：
#   严格：<gameId>_<YYYYMMDD>_<HHMMSS>_<毫秒>_...
#   宽松：<gameId>_...（只有当 gameId 确实存在于 games 表时才采信）
_STRICT_ID_RE = re.compile(r"^(\d+)_\d{8}_\d{6}_\d{3}(?:_|\.|$)")
_LOOSE_ID_RE = re.compile(r"^(\d+)_")

_ILLEGAL_FOLDER_CHARS = '<>:"/\\|?*'
_CTRL_CHARS_RE = re.compile(r"[\x00-\x1f]")


# ======================================================================
# 基础工具
# ======================================================================
def sanitize_folder_name(name) -> str:
    """把游戏名清洗成 Windows / macOS / Linux 都能用的文件夹名。

    只替换文件系统非法字符与控制字符，保留中文、空格、～ 等正常字符；
    空名（或全是非法字符）回退为「未分类」。
    """
    text = _CTRL_CHARS_RE.sub("_", str(name or ""))
    for ch in _ILLEGAL_FOLDER_CHARS:
        text = text.replace(ch, "_")
    # Windows 不允许目录名以空格或点收尾
    text = text.strip()
    while text.endswith("."):
        text = text[:-1]
    text = text.strip()
    return text or UNCLASSIFIED


def is_thumbnail(filename: str) -> bool:
    """是否是本程序生成的 `_thumb.jpg` 缩略图。"""
    stem, _ = os.path.splitext(os.path.basename(filename))
    return stem.lower().endswith("_thumb")


def game_id_from_filename(filename: str,
                          valid_ids: Optional[Iterable[int]] = None
                          ) -> Optional[int]:
    """从文件名前缀解析上传时写入的 gameId。

    严格规则命中就直接返回；宽松规则只有在 gameId 属于 ``valid_ids``
    时才采信，避免把 `20250530140200_1.jpg` 这种普通文件名误判成 ID。
    """
    base = os.path.basename(str(filename or ""))
    m = _STRICT_ID_RE.match(base)
    if m:
        return int(m.group(1))
    m = _LOOSE_ID_RE.match(base)
    if m:
        gid = int(m.group(1))
        if valid_ids is None:
            return None
        try:
            if gid in valid_ids:
                return gid
        except TypeError:
            return None
    return None


def normalize_path_key(path, path_resolver=None) -> str:
    """把路径规范成可用于精确比对的 key（绝对路径 + normcase）。"""
    text = str(path or "")
    if not text:
        return ""
    if path_resolver is not None:
        try:
            text = path_resolver(text) or text
        except Exception:
            pass
    text = text.replace("/", os.sep).replace("\\", os.sep)
    try:
        text = os.path.abspath(text)
    except Exception:
        pass
    return os.path.normcase(os.path.normpath(text))


def _row_get(row, key: str, index: int, default=""):
    """兼容 dict / sqlite Row / tuple 三种行结构。"""
    if row is None:
        return default
    try:
        if hasattr(row, "keys"):
            return row[key]
    except Exception:
        pass
    try:
        return row[index]
    except Exception:
        return default


# ======================================================================
# 游戏索引：gameId → 游戏名，路径 → 游戏名
# ======================================================================
@dataclass
class LibraryIndex:
    """本地 CG 归类所需的数据库侧信息。"""

    id_to_title: Dict[int, str] = field(default_factory=dict)
    path_to_title: Dict[str, str] = field(default_factory=dict)
    known_titles: Set[str] = field(default_factory=set)
    # 目录名别名（游戏名 / 原名 / 清洗后的名字）→ 统一展示用游戏名
    alias_to_title: Dict[str, str] = field(default_factory=dict)
    # 别名的小写形式 → 展示用游戏名（目录名匹配大小写不敏感，O(1) 查询）
    lower_to_title: Dict[str, str] = field(default_factory=dict)
    # 分类名（CG / 背景 / 立绘 / 其他）等不能当成游戏名的目录名
    reserved_names: Set[str] = field(default_factory=set)

    def title_for_id(self, game_id) -> str:
        try:
            return self.id_to_title.get(int(game_id), "") or ""
        except (TypeError, ValueError):
            return ""

    @property
    def is_empty(self) -> bool:
        return not self.id_to_title and not self.path_to_title


def build_index(game_rows: Iterable = (),
                screenshot_rows: Iterable = (),
                path_resolver=None,
                reserved_names: Sequence[str] = ()) -> LibraryIndex:
    """由数据库行构造 LibraryIndex。

    :param game_rows: games 表行，需要 id / title / title_jp 三列
    :param screenshot_rows: screenshots 表行，需要 game_id / file_path 两列
    :param path_resolver: 把库里可能存在的相对路径转成绝对路径（如 config.to_abs）
    :param reserved_names: 分类名等保留目录名，不参与“目录名 = 游戏名”的匹配
    """
    index = LibraryIndex()
    index.reserved_names = {str(x) for x in reserved_names if str(x)}
    index.reserved_names.add(UNCLASSIFIED)

    for row in game_rows or ():
        try:
            gid = int(_row_get(row, "id", 0, 0) or 0)
        except (TypeError, ValueError):
            continue
        title = str(_row_get(row, "title", 1, "") or "").strip()
        title_jp = str(_row_get(row, "title_jp", 2, "") or "").strip()
        if not title and not title_jp:
            continue
        canonical = title or title_jp
        if gid:
            index.id_to_title[gid] = canonical
        # 目录名可能是游戏名、原名或清洗后的结果，都登记成别名
        for alias in (title, title_jp, sanitize_folder_name(canonical)):
            alias = (alias or "").strip()
            if not alias:
                continue
            index.known_titles.add(alias)
            if alias not in index.reserved_names:
                index.alias_to_title[alias] = canonical
                index.lower_to_title[alias.lower()] = canonical

    for row in screenshot_rows or ():
        try:
            gid = int(_row_get(row, "game_id", 0, 0) or 0)
        except (TypeError, ValueError):
            continue
        title = index.id_to_title.get(gid, "")
        raw = str(_row_get(row, "file_path", 1, "") or "")
        if not title or not raw:
            continue
        key = normalize_path_key(raw, path_resolver)
        if key:
            index.path_to_title[key] = title

    index.known_titles.discard("")
    return index


# build_index 之后，LibraryIndex 即可直接使用；
# 手工构造 LibraryIndex() 时各字段都是空容器，也不会抛异常。


def resolve_game_name(path: str, index: Optional[LibraryIndex],
                      categories: Sequence[str] = ()) -> str:
    """判断一张图片属于哪款游戏，判不出来返回「未分类」。"""
    if index is None:
        index = LibraryIndex()

    abs_path = os.path.abspath(str(path or ""))
    parent = os.path.basename(os.path.dirname(abs_path))

    # 1/2. 先看目录名（新布局 / 已归类）
    if parent:
        if parent == UNCLASSIFIED:
            return UNCLASSIFIED
        reserved = set(index.reserved_names) | {str(c) for c in (categories or ())}
        if parent not in reserved:
            hit = index.lower_to_title.get(parent.lower())
            if hit:
                return hit
        # 2.5 更早的 data/screenshots/<gameId>/ 布局：目录名就是 gameId
        if parent.isdigit():
            legacy = index.id_to_title.get(int(parent))
            if legacy:
                return legacy

    # 3. 数据库记录精确命中
    key = normalize_path_key(abs_path)
    if key and key in index.path_to_title:
        return index.path_to_title[key]

    # 4. 文件名前缀里的 gameId
    gid = game_id_from_filename(os.path.basename(abs_path),
                                set(index.id_to_title) or None)
    if gid is not None:
        title = index.id_to_title.get(gid)
        if title:
            return title

    # 5. 兜底
    return UNCLASSIFIED


# ======================================================================
# 扫描 / 筛选
# ======================================================================
def scan_library(roots: Sequence[str],
                 index: Optional[LibraryIndex] = None,
                 exts: Sequence[str] = DEFAULT_EXTS,
                 categories: Sequence[str] = (),
                 ) -> Dict[str, List[str]]:
    """扫描本地 CG 根目录，按游戏名分组返回 {游戏名: [绝对路径, ...]}。

    会跳过本程序生成的 `_thumb.jpg`（原图与缩略图同名，只在存盘时用）。
    """
    allowed = {str(e).lower() for e in exts}
    by_game: Dict[str, List[str]] = {}
    for root in roots or ():
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                stem, ext = os.path.splitext(fn)
                if ext.lower() not in allowed:
                    continue
                if stem.lower().endswith("_thumb"):
                    continue
                full = os.path.join(dirpath, fn)
                game = resolve_game_name(full, index, categories)
                by_game.setdefault(game, []).append(full)
    return by_game


def game_names(by_game: Dict[str, List[str]]) -> List[str]:
    """把扫描结果整理成下拉框用的游戏名列表（「未分类」永远排最后）。"""
    names = sorted((n for n in by_game if n != UNCLASSIFIED), key=_sort_key)
    if UNCLASSIFIED in by_game:
        names.append(UNCLASSIFIED)
    return names


def _sort_key(name: str):
    """中文按拼音不现实，这里用「大小写不敏感 + 原串」稳定排序即可。"""
    return (str(name).lower(), str(name))


# ======================================================================
# 存盘路径
# ======================================================================
def game_dir(root: str, category: str, game_name: str) -> str:
    """上传存盘目录：<CG_ROOT>/<分类>/<游戏名>。"""
    return os.path.join(str(root), str(category), sanitize_folder_name(game_name))


def ensure_game_dir(root: str, category: str, game_name: str) -> str:
    """确保目录存在并返回。"""
    target = game_dir(root, category, game_name)
    os.makedirs(target, exist_ok=True)
    return target


def _unique_path(path: str) -> str:
    """目标已存在时追加 _1/_2 …，避免覆盖同名文件。"""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = "%s_%d%s" % (root, i, ext)
        if not os.path.exists(cand):
            return cand
        i += 1


def _is_known_game_folder(name: str, index: Optional[LibraryIndex]) -> bool:
    """目录名是否确定是我们归类的游戏文件夹（用于只收拾自己建的目录）。"""
    if not index:
        return False
    text = str(name or "").strip()
    if not text:
        return False
    if text == UNCLASSIFIED:
        return True
    return text.lower() in index.lower_to_title


def thumb_dir_for(game_dir_path: str) -> str:
    """给定游戏文件夹，返回其缩略图子文件夹路径。"""
    return os.path.join(str(game_dir_path), THUMB_DIR_NAME)


# ======================================================================
# 历史图片整理
# ======================================================================
def organize_library(root: str,
                     index: Optional[LibraryIndex] = None,
                     categories: Sequence[str] = ("CG", "背景", "立绘", "其他"),
                     exts: Sequence[str] = DEFAULT_EXTS,
                     apply: bool = False,
                     move: bool = True) -> dict:
    """把旧布局的历史图片整理进 ``<分类>/<游戏名>/``。

    只处理**直接躺在分类目录下**的图片（旧布局），
    已经在子文件夹里的图片一律不动，避免破坏用户自己的目录结构。

    落点规则::

        <CG_ROOT>/<分类>/<游戏名>/<原图>
        <CG_ROOT>/<分类>/<游戏名>/<缩略图文件夹>/<原图名>_thumb.jpg

    另外会把「已经放对游戏文件夹、但缩略图还散在同级」的情况收进缩略图子文件夹，
    所以重复点“整理”是幂等的。

    :param apply: False = 只做演练（dry-run），不落盘
    :param move: True 用 shutil.move（同盘改名，最快）；False 复制后保留原图
    :return: 报告 dict::

        {
          "total":   扫描到的待整理图片数,
          "moves":   [(src_abs, dst_abs), ...]     计划中的移动,
          "moved":   [(src_abs, dst_abs), ...]     实际已移动（apply=True 时）,
          "skipped": [src_abs, ...]                已经在目标位置,
          "errors":  [(src_abs, msg), ...],
        }
    """
    allowed = {str(e).lower() for e in exts}
    report = {"total": 0, "moves": [], "moved": [], "skipped": [], "errors": []}
    root = str(root or "")
    if not root or not os.path.isdir(root):
        report["errors"].append((root, "CG 根目录不存在"))
        return report

    def _do_move(src, dst, dst_dir):
        try:
            os.makedirs(dst_dir, exist_ok=True)
            if move:
                shutil.move(src, dst)
            else:
                shutil.copy2(src, dst)
            report["moved"].append((src, dst))
        except Exception as exc:
            report["errors"].append((src, str(exc)))

    # ---- 第一阶段：分类目录下平铺的旧布局图片 -------------------------
    for cat in categories or ():
        cat_dir = os.path.join(root, str(cat))
        if not os.path.isdir(cat_dir):
            continue
        try:
            entries = sorted(os.listdir(cat_dir))
        except OSError as exc:
            report["errors"].append((cat_dir, str(exc)))
            continue
        for fn in entries:
            src = os.path.join(cat_dir, fn)
            if not os.path.isfile(src):
                continue
            if os.path.splitext(fn)[1].lower() not in allowed:
                continue
            report["total"] += 1
            game = resolve_game_name(src, index, categories)
            dst_dir = os.path.join(cat_dir, sanitize_folder_name(game))
            if is_thumbnail(fn):
                dst_dir = os.path.join(dst_dir, THUMB_DIR_NAME)
            dst = os.path.join(dst_dir, fn)
            if (os.path.normcase(os.path.abspath(src))
                    == os.path.normcase(os.path.abspath(dst))):
                report["skipped"].append(src)
                continue
            dst = _unique_path(dst)
            report["moves"].append((src, dst))
            if apply:
                _do_move(src, dst, dst_dir)

    # ---- 第二阶段：游戏文件夹里散落的缩略图 → 游戏名/缩略图/ ----------
    for cat in categories or ():
        cat_dir = os.path.join(root, str(cat))
        if not os.path.isdir(cat_dir):
            continue
        try:
            subs = sorted(os.listdir(cat_dir))
        except OSError:
            continue
        for sub in subs:
            sub_dir = os.path.join(cat_dir, sub)
            if not os.path.isdir(sub_dir) or sub == THUMB_DIR_NAME:
                continue
            # 只整理确定是游戏文件夹的目录，用户自建目录不碰
            if not _is_known_game_folder(sub, index):
                continue
            thumb_dir = os.path.join(sub_dir, THUMB_DIR_NAME)
            try:
                names = sorted(os.listdir(sub_dir))
            except OSError as exc:
                report["errors"].append((sub_dir, str(exc)))
                continue
            for fn in names:
                src = os.path.join(sub_dir, fn)
                if not os.path.isfile(src) or not is_thumbnail(fn):
                    continue
                if os.path.splitext(fn)[1].lower() not in allowed:
                    continue
                report["total"] += 1
                dst = _unique_path(os.path.join(thumb_dir, fn))
                report["moves"].append((src, dst))
                if apply:
                    _do_move(src, dst, thumb_dir)
    return report


def remap_screenshot_paths(screenshot_rows: Iterable,
                           moves: Iterable,
                           path_resolver=None) -> Dict[str, str]:
    """由 (旧绝对路径, 新绝对路径) 生成数据库 file_path 的更新映射。

    数据库里存的是 ``E:/cg存储/CG/xxx.jpg`` 这种正斜杠原样字符串，
    所以返回的 key 用库里存的原文，value 用归一化后的新路径。
    """
    from_key: Dict[str, str] = {}
    for src, dst in moves or ():
        key = normalize_path_key(src, path_resolver)
        if key:
            from_key[key] = str(dst).replace("\\", "/")

    out: Dict[str, str] = {}
    for row in screenshot_rows or ():
        old = str(_row_get(row, "file_path", 1, "") or "")
        if not old:
            continue
        key = normalize_path_key(old, path_resolver)
        new = from_key.get(key)
        if new and new != old:
            out[old] = new
    return out
