# -*- coding: utf-8 -*-
"""???????QThread????"""

import os
import time
import shutil
import urllib.parse
from PIL import Image

from PySide6.QtCore import QThread, Signal

import config
from config import (
    DB_PATH, BANGUMI_UA, IMAGE_EXTENSIONS, get_cg_root, get_sgdb_key,
    normalize_rel, now_str, _transpose, THUMB_MAX_SIZE,
)
from database import Database

import cg_library

import net
from net import (
    _identify_image, _http_get, _bangumi_search, _vndb_search, _steam_search,
    _sgdb_search, _download_cover, _search_by_source, _split_rating, _map_bgm_status,
)


class ImageSearchWorker(QThread):
    """后台识图：调用所选数据源，返回统一结果列表，避免界面卡顿。"""
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, image_path: str, source: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.source = source

    def run(self):
        try:
            self.finished_ok.emit(_identify_image(self.image_path, self.source))
        except Exception as exc:
            self.failed.emit(str(exc))


class ThumbLoaderWorker(QThread):
    """后台下载缩略图字节，主线程再转成 QImage。避免子线程操作 UI。"""
    thumb_ready = Signal(int, bytes)
    thumb_fail = Signal(int)

    def __init__(self, jobs: list, parent=None):
        # jobs: [(row, url), ...]
        super().__init__(parent)
        self.jobs = list(jobs or [])

    def run(self):
        for row, url in self.jobs:
            if not url:
                continue
            try:
                headers = {"User-Agent": "GalgameInfoManager/1.0 (local offline desktop app)"}
                resp = _http_get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if ctype and "image" not in ctype:
                    self.thumb_fail.emit(row)
                    continue
                self.thumb_ready.emit(row, resp.content)
            except Exception:
                self.thumb_fail.emit(row)


class BangumiSearchWorker(QThread):
    """搜索 Bangumi 游戏（type=4），解析返回结果。"""
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, keyword: str, parent=None):
        super().__init__(parent)
        self.keyword = keyword.strip()

    def run(self):
        try:
            self.finished_ok.emit(_bangumi_search(self.keyword))
        except Exception as exc:
            self.failed.emit(str(exc))


class VndbSearchWorker(QThread):
    """搜索 VNDB（https://vndb.org/kana），可直连无需梯子。"""
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, keyword: str, parent=None):
        super().__init__(parent)
        self.keyword = keyword.strip()

    def run(self):
        try:
            self.finished_ok.emit(_vndb_search(self.keyword))
        except Exception as exc:
            self.failed.emit(str(exc))


class SteamSearchWorker(QThread):
    """搜索 Steam 商店（可直连、免注册），返回统一结果列表。"""
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, keyword: str, parent=None):
        super().__init__(parent)
        self.keyword = keyword.strip()

    def run(self):
        try:
            self.finished_ok.emit(_steam_search(self.keyword))
        except Exception as exc:
            self.failed.emit(str(exc))


class SgdbSearchWorker(QThread):
    """搜索 SteamGridDB 社区库，返回带竖版网格封面的统一结果列表。"""
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, keyword: str, api_key: str, parent=None):
        super().__init__(parent)
        self.keyword = keyword.strip()
        self.api_key = api_key

    def run(self):
        try:
            self.finished_ok.emit(_sgdb_search(self.keyword, self.api_key))
        except Exception as exc:
            self.failed.emit(str(exc))


class DetailFetchWorker(QThread):
    """后台抓取某个条目的详情（VNDB / Bangumi），供「智能填充」与每栏 🔎 使用。

    走 net.get_detail() 的内存缓存：同一 (source, id) 第二次调用直接返回，
    不会重复联网，避免触发 VNDB 限流。
    """
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, source: str, subject_id, parent=None):
        super().__init__(parent)
        self.source = str(source or "").strip().lower()
        self.subject_id = subject_id

    def run(self):
        try:
            self.done.emit(net.get_detail(self.source, self.subject_id))
        except Exception as exc:
            self.failed.emit(str(exc))


class BangumiLoginWorker(QThread):
    """用个人令牌验证 Bangumi 登录，取回用户名与昵称。"""
    success = Signal(str, str)   # username, nickname
    failed = Signal(str)

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self.token = token.strip()

    def run(self):
        try:
            headers = {"User-Agent": BANGUMI_UA, "Accept": "application/json",
                       "Authorization": "Bearer " + self.token}
            resp = _http_get("https://api.bgm.tv/v0/me", headers=headers, timeout=20)
            resp.raise_for_status()
            d = resp.json()
            name = str(d.get("username") or "")
            nick = str(d.get("nickname") or name)
            self.success.emit(name, nick)
        except Exception as exc:
            self.failed.emit(str(exc))


class BangumiCollectionWorker(QThread):
    """拉取 Bangumi 用户游戏收藏，下载封面，供用户确认后导入。"""
    progress = Signal(int, int, str)   # count, total, title
    item_done = Signal(int, dict)      # index, row
    finished_ok = Signal(list)         # rows
    failed = Signal(str)

    def __init__(self, username: str, token: str, parent=None):
        super().__init__(parent)
        self.username = username.strip()
        self.token = token.strip()

    def run(self):
        rows = []
        title = ""
        headers = {"User-Agent": BANGUMI_UA, "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        offset, limit = 0, 100
        total = None
        try:
            while True:
                if self.isInterruptionRequested():
                    break
                url = ("https://api.bgm.tv/v0/users/%s/collections"
                       "?subject_type=4&limit=%d&offset=%d" %
                       (urllib.parse.quote(self.username), limit, offset))
                resp = _http_get(url, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data") or []
                total = data.get("total", total)
                for it in items:
                    if self.isInterruptionRequested():
                        break
                    sub = it.get("subject") or {}
                    title = str(sub.get("name_cn") or sub.get("name") or "")
                    if not title:
                        continue
                    title_jp = str(sub.get("name") or "")
                    rate = int(it.get("rate", 0) or 0)
                    story, char, audio = _split_rating(rate)
                    cover = ""
                    img = (sub.get("images") or {}).get("large") or ""
                    if img:
                        try:
                            rel, _ = _download_cover(img, sub.get("id"))
                            cover = rel
                        except Exception:
                            cover = ""
                    row = {
                        "title": title,
                        "title_jp": title_jp,
                        "developer": "",
                        "release_date": str(sub.get("date") or ""),
                        "status": _map_bgm_status(it.get("type")),
                        "rating": rate,
                        "score_story": story,
                        "score_char": char,
                        "score_audio": audio,
                        "cover": cover,
                        "notes": str(it.get("comment") or ""),
                        "found": True,
                    }
                    rows.append(row)
                    self.item_done.emit(len(rows), row)
                self.progress.emit(len(rows), total or (offset + len(items)), title or "")
                if not items or (offset + len(items)) >= (total or 0):
                    break
                offset += limit
                time.sleep(0.2)
            self.finished_ok.emit(rows)
        except Exception as exc:
            self.failed.emit(str(exc))


class CoverDownloadWorker(QThread):
    """下载封面并压缩保存为本地文件。"""
    done = Signal(str, str)  # (相对路径, 绝对路径)
    failed = Signal(str)

    def __init__(self, url: str, subject_id, parent=None):
        super().__init__(parent)
        self.url = url
        self.subject_id = subject_id

    def run(self):
        try:
            rel_path, abs_path = _download_cover(self.url, self.subject_id)
            self.done.emit(rel_path, abs_path)
        except Exception as exc:
            self.failed.emit(str(exc))


class CoverPreviewWorker(QThread):
    """下载封面用于预览（供封面选择器使用）。"""
    done = Signal(str, str)    # rel, abs
    failed = Signal(str)

    def __init__(self, url: str, subject_id, parent=None):
        super().__init__(parent)
        self.url = url
        self.subject_id = subject_id

    def run(self):
        try:
            rel, abs_ = _download_cover(self.url, self.subject_id)
            self.done.emit(rel, abs_)
        except Exception as exc:
            self.failed.emit(str(exc))


class BatchImportWorker(QThread):
    """批量导入：逐个搜索并写入数据库（在后台线程执行，不卡界面）。"""
    progress = Signal(int, int, str, bool)   # done, total, title, ok
    finished_ok = Signal(int, int, list)     # total, success, failed_titles
    failed = Signal(str)

    def __init__(self, records: list, source: str = "vndb", mode: str = "auto",
                 parent=None):
        super().__init__(parent)
        self.records = records
        self.source = source
        self.mode = mode  # "auto"（联网抓取） / "direct"（直接采用表格字段）

    def run(self):
        db = None
        success, failed = 0, []
        total = len(self.records)
        try:
            db = Database(DB_PATH)  # 使用独立连接，避免跨线程共用
            for i, rec in enumerate(self.records, 1):
                if self.isInterruptionRequested():
                    break
                try:
                    title = str(rec.get("title") or "").strip()
                    if not title:
                        raise ValueError("标题为空")
                    if self.mode == "direct":
                        data = {
                            "title": title,
                            "title_jp": str(rec.get("title_jp") or "").strip(),
                            "developer": str(rec.get("developer") or "").strip(),
                            "release_date": "",
                            "status": "想玩",
                            "rating": 0,
                            "play_time": 0,
                            "cover_path": "",
                            "notes": title,
                        }
                    else:
                        key = str(rec.get("title_jp") or title).strip()
                        results = _search_by_source(self.source, key,
                                                    detail_limit=1 if self.source == "steam" else 5)
                        if not results:
                            raise ValueError("未找到结果")
                        best = results[0]
                        cover = ""
                        if best.get("cover"):
                            try:
                                rel, _ = _download_cover(best["cover"], best.get("id"))
                                cover = rel
                            except Exception:
                                cover = ""
                        data = {
                            "title": best.get("name_cn") or best.get("name") or title,
                            "title_jp": best.get("name", ""),
                            "developer": best.get("developer", "")
                                          or str(rec.get("developer") or "").strip(),
                            "release_date": best.get("date", ""),
                            "status": "想玩",
                            "rating": 0,
                            "play_time": 0,
                            "cover_path": cover,
                            "notes": title,
                        }
                    db.add_game(data)
                    success += 1
                    self.progress.emit(i, total, title, True)
                    if self.mode == "auto":
                        time.sleep(0.35)  # 避免触发接口限流
                except Exception as exc:
                    failed.append({"title": title, "error": str(exc)})
                    self.progress.emit(i, total, title, False)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        finally:
            if db:
                db.close()
        self.finished_ok.emit(total, success, failed)


class RecognizeWorker(QThread):
    """批量识别：逐个搜索并下载封面，但不写入数据库（供用户确认）。"""
    progress = Signal(int, int, str, bool)   # done, total, key, ok
    item_done = Signal(int, dict, bool, str) # row, rec, ok, error
    finished_ok = Signal(list)               # list[{row, rec, ok, error}]
    failed = Signal(str)

    def __init__(self, jobs: list, source: str = "vndb", parent=None):
        super().__init__(parent)
        self.jobs = jobs          # list of {"row": int|None, "key": str}
        self.source = source

    def run(self):
        results = []
        total = len(self.jobs)
        for i, job in enumerate(self.jobs, 1):
            if self.isInterruptionRequested():
                break
            key = str(job.get("key") or "").strip()
            row = job.get("row")
            if row is None:
                row = i - 1
            try:
                # Steam 在批量场景只取最匹配的一条信息即可，detail_limit=1 避免逐条重复请求详情
                records = _search_by_source(self.source, key, detail_limit=1) \
                    if self.source == "steam" else _search_by_source(self.source, key)
                if not records:
                    raise ValueError("未找到结果")
                best = records[0]
                cover = ""
                if best.get("cover"):
                    try:
                        rel, _ = _download_cover(best["cover"], best.get("id"))
                        cover = rel
                    except Exception:
                        cover = ""
                rec = {
                    "title": best.get("name_cn") or best.get("name") or key,
                    "title_jp": best.get("name", ""),
                    "developer": best.get("developer", ""),
                    "release_date": best.get("date", ""),
                    "status": "想玩",
                    "cover": cover,
                }
                results.append({"row": row, "rec": rec, "ok": True, "error": ""})
                self.item_done.emit(row, rec, True, "")
                self.progress.emit(i, total, key, True)
            except Exception as exc:
                rec = {"title": key, "title_jp": "", "developer": "",
                       "release_date": "", "status": "想玩", "cover": ""}
                results.append({"row": row, "rec": rec, "ok": False, "error": str(exc)})
                self.item_done.emit(row, rec, False, str(exc))
                self.progress.emit(i, total, key, False)
            time.sleep(0.35)
        self.finished_ok.emit(results)


class ScreenshotImportWorker(QThread):
    """批量导入截图：复制文件 + 生成缩略图。"""
    finished = Signal(list)  # list[dict]
    failed = Signal(str)

    def __init__(self, game_id: int, file_category_pairs: list, parent=None,
                 game_name: str = ""):
        super().__init__(parent)
        self.game_id = game_id
        self.pairs = file_category_pairs  # [(abs_file, category), ...]
        # 游戏名：按 <CG_ROOT>/分类/游戏名/ 分文件夹存储（空则归入「未分类」）
        self.game_name = str(game_name or "").strip()

    def run(self):
        results = []
        try:
            for abs_file, category in self.pairs:
                if not os.path.isfile(abs_file):
                    continue
                # 按“分类 / 游戏名”保存到设置的 CG 根目录下，文件名带游戏 ID 便于管理
                cat_dir = cg_library.ensure_game_dir(
                    get_cg_root(), category, self.game_name)
                stem, ext = os.path.splitext(os.path.basename(abs_file))
                ext = ext.lower() if ext.lower() in IMAGE_EXTENSIONS else ".jpg"
                ts = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time()*1000)%1000:03d}"
                fname = f"{self.game_id}_{ts}_{stem}{ext}"
                dst = os.path.join(cat_dir, fname)
                shutil.copy2(abs_file, dst)

                # 生成缩略图：统一放进 <游戏名>/缩略图/ 子文件夹
                thumb_name = f"{self.game_id}_{ts}_{stem}_thumb.jpg"
                thumb_dir = cg_library.thumb_dir_for(cat_dir)
                os.makedirs(thumb_dir, exist_ok=True)
                thumb_abs = os.path.join(thumb_dir, thumb_name)
                try:
                    im = Image.open(dst)
                    im = _transpose(im)
                    if im.mode in ("P", "RGBA", "LA"):
                        im = im.convert("RGB")
                    im.thumbnail((THUMB_MAX_SIZE, THUMB_MAX_SIZE))
                    im.save(thumb_abs, "JPEG", quality=85)
                except Exception:
                    # 缩略图失败不影响主流程，直接复制原图作为缩略图回退
                    shutil.copy2(dst, thumb_abs)

                rel = normalize_rel(dst)
                thumb_rel = normalize_rel(thumb_abs)
                results.append({
                    "rel_path": rel,
                    "thumb_rel": thumb_rel,
                    "category": category,
                    "upload_time": now_str(),
                })
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


# ============================================================
# 选择对话框：Bangumi 搜索结果选择 & 截图分类选择
# ============================================================
