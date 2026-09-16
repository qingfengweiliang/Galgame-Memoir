# -*- coding: utf-8 -*-
"""随机 CG 图片接口层（无 UI）。

职责：
- 请求 illlights 主图库 info / 随机图
- 失败时按优先级降级：illlights -> dmoe.cc -> 本地 CG
- 用 Pillow 解码（含 AVIF），再给 UI 提供 QPixmap 可加载的显示字节
- 不依赖 PySide6，方便命令行测试 / 以后给别的 UI 复用
- 图源统一成轻量 Provider 接口（见 ImageProvider）：illlights = IlllightsProvider，
  dmoe = DmoeProvider，UapiPro = UapiProProvider，LoliAPI = LoliApiProvider，
  本地图库 = LocalProvider；它们都只是包装 / 转发，不改变原有行为；
  auto 模式由 _auto_poll 按固定优先级轮询（illlights -> dmoe -> uapipro
  -> loliapi -> local），手动模式只调用所选图源
"""

import io
import os
import random
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageOps

import cg_library
from cg_library import LibraryIndex, UNCLASSIFIED

try:
    from PIL import Image as _PILImage
except Exception:  # pragma: no cover - Pillow 是项目硬依赖
    _PILImage = None


MAIN_BASE = "https://api.illlights.com/v1"
MAIN_IMG = MAIN_BASE + "/img"
MAIN_INFO = MAIN_BASE + "/img/info"
FALLBACK_IMG = "https://www.dmoe.cc/random.php"
UAPIPRO_IMG = "https://uapis.cn/api/v1/random/image"

# LoliAPI：分类即设备，两个端点（均已实测 302 -> 图片二进制）
LOLIAPI_BASE = "https://www.loliapi.com"
LOLIAPI_IMG = {
    "pc": LOLIAPI_BASE + "/acg/pc/",
    "pe": LOLIAPI_BASE + "/acg/pe/",
}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# UapiPro 按设备维度分为 PC / 移动端，需要按分类切换 User-Agent
UA_PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

_IMAGE_EXTS = {
    "JPEG": ".jpg",
    "JPG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
    "BMP": ".bmp",
}

_LOCAL_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_LOCAL_CACHE_SECONDS = 120
# 单次本地取图最多重试几个文件，避免随机抽到损坏图就整次失败
_LOCAL_PICK_TRIES = 6

SOURCE_ORDER = {
    # 注意：B1 起「手动 illlights」、B2 起「手动 dmoe / 本地图库」都不再走
    # 这张表，改由各自的 Provider 单独处理（失败即失败、不降级）。
    # 现在只有 auto 会用到它；其余条目按「不删旧代码」保留。
    "auto": ("illlights", "dmoe", "local"),
    "first": ("illlights", "dmoe", "local"),
    "second": ("dmoe", "illlights", "local"),
    "local": ("local", "illlights", "dmoe"),
}


class _NoMatchError(Exception):
    """带筛选条件时主图库返回 404：当前筛选无图。"""


@dataclass
class CGResult:
    """一次随机图请求的结果，UI 只认这个结构。"""

    ok: bool = False
    request_id: int = 0
    raw_bytes: bytes = b""
    display_bytes: bytes = b""       # 已转码成 JPEG，Qt 可稳定显示
    url: str = ""
    source: str = "illlights"        # illlights / dmoe / local
    fmt: str = ""
    width: int = 0
    height: int = 0
    fallback: bool = False
    no_match: bool = False
    message: str = ""
    download_bytes: bytes = b""
    download_ext: str = ".jpg"
    local_path: str = ""             # source == local 时的本地文件绝对路径
    game_name: str = ""              # source == local 时所属的游戏名（可能为「未分类」）


class ImageProvider:
    """图源最小接口：取图 / 声明分类 / 返回必要的图片信息。

    刻意保持轻量：不做调度、不做工厂、不做注册表。自动轮询（若将来需要）
    由调用方负责，Provider 只干本图源自己的事，失败时返回 None / 抛异常，
    绝不在内部切换到别的图源。
    """

    key = ""        # 内部标识（与 SOURCE_ORDER 里的名字一致）
    label = ""      # 界面上的显示名

    def categories(self) -> list:
        """返回本图源支持的分类列表；不支持分类时返回空列表。"""
        return []

    def fetch(self, category=None, request_id: int = 0):
        """按分类取一张图。

        返回 :class:`CGResult`；本图源没有可用图片时返回 ``None``。
        """
        raise NotImplementedError


class LocalProvider(ImageProvider):
    """本地图库 Provider。

    只是把现有本地逻辑原样转发出去（等价转发器）：
    ``categories()`` -> :meth:`RandomCGFetcher.local_game_names`
    ``fetch()``      -> :meth:`RandomCGFetcher._pick_local_cg`

    因此随机规则、作品名筛选、图片加载行为、缓存策略都与包装前完全一致。
    """

    key = "local"
    label = "本地图库"

    def __init__(self, fetcher):
        self._fetcher = fetcher

    def categories(self) -> list:
        """本地图库的分类 = 本地作品名（沿用现有扫描结果，「未分类」排最后）。"""
        return list(self._fetcher.local_game_names() or [])

    def fetch(self, category=None, request_id: int = 0):
        """转发到现有 ``_pick_local_cg``：规则与加载行为一行不改。"""
        return self._fetcher._pick_local_cg(request_id, category)


class IlllightsProvider(ImageProvider):
    """illlights 主图库 Provider。

    包装现有 :meth:`RandomCGFetcher.get_info` 与
    :meth:`RandomCGFetcher._try_illlights`，不新增任何外部接口、不改接口地址。

    分类（由本 Provider 自己声明，数据来自 ``/v1/img/info``）：
    - ``("全部", (None, None))``
    - ``(作品名, (作品名, None))``
    - ``("作品名 · 分辨率", (作品名, 分辨率))``
    ``other`` 不是可查询值（``size=other`` 会被判非法 → 403），一律过滤。

    失败语义：404（无匹配）/ 403 / 超时 / 返回格式异常都算失败，统一返回
    ``ok=False`` 的 :class:`CGResult`，**绝不在内部降级到别的图源**。
    """

    key = "illlights"
    label = "illlights"

    def __init__(self, fetcher):
        self._fetcher = fetcher

    @staticmethod
    def _split(category):
        """把分类值拆成 ``(作品名, 分辨率)``；None / 缺省表示不筛选。"""
        name, size = None, None
        if isinstance(category, (tuple, list)):
            if len(category) >= 1:
                name = category[0]
            if len(category) >= 2:
                size = category[1]
        elif category is not None:
            name = category
        name = str(name).strip() if name else ""
        size = str(size).strip() if size else ""
        return (name or None, size or None)

    def categories(self) -> list:
        """返回 ``[(界面显示文案, 分类提交值), ...]``。

        提交值统一是 ``(作品名, 分辨率)``；分辨率会过滤掉 ``other``。
        数据来自现有 ``get_info()``（沿用其 10 分钟缓存），不新增请求方式。
        """
        try:
            info = self._fetcher.get_info()
        except Exception:
            info = {}
        if not isinstance(info, dict):
            info = {}

        names = [str(n) for n in (info.get("names") or []) if str(n).strip()]
        by_name_size = {}
        for row in (info.get("by_name_size") or []):
            try:
                n = str(row.get("name") or "")
                s = str(row.get("size") or "")
            except Exception:
                continue
            if not n or not s or s.lower() == "other":
                continue
            sizes = by_name_size.setdefault(n, [])
            if s not in sizes:
                sizes.append(s)

        items = [("全部", (None, None))]
        for n in names:
            items.append((n, (n, None)))
        for n in names:
            for s in by_name_size.get(n, []):
                items.append(("%s · %s" % (n, s), (n, s)))
        return items

    def fetch(self, category=None, request_id: int = 0) -> CGResult:
        """只向 illlights 要一张图；失败即失败，不降级到 dmoe / local。"""
        name, size = self._split(category)
        params = {}
        if name:
            params["name"] = name
        if size:
            params["size"] = size
        try:
            return self._fetcher._try_illlights(
                params, name, size, request_id)
        except _NoMatchError as exc:
            return CGResult(
                ok=False, request_id=request_id, source=self.key, no_match=True,
                message=(str(exc)
                         or "当前筛选没有匹配的图片，请调整作品名或分辨率。"))
        except requests.exceptions.Timeout:
            return CGResult(
                ok=False, request_id=request_id, source=self.key,
                message="illlights 请求超时（单次请求上限 10 秒）。")
        except Exception as exc:
            return CGResult(
                ok=False, request_id=request_id, source=self.key,
                message="illlights 加载失败：%s" % exc)


class DmoeProvider(ImageProvider):
    """dmoe 备用图库 Provider。

    包装现有 :meth:`RandomCGFetcher._try_dmoe`，接口地址与参数都不改。
    该接口只有 ``return=json`` 这一个可选参数，**没有任何分类维度**，
    所以 ``categories()`` 返回空列表，UI 据此把分类置灰。

    失败语义：网络异常 / HTTP 错误 / 超时 / 返回格式异常都算失败，统一返回
    ``ok=False`` 的 :class:`CGResult`，**绝不在内部降级到别的图源**。
    """

    key = "dmoe"
    label = "dmoe"

    def __init__(self, fetcher):
        self._fetcher = fetcher

    def categories(self) -> list:
        """该图源没有分类参数，声明为空列表（UI 置灰）。"""
        return []

    def fetch(self, category=None, request_id: int = 0) -> CGResult:
        """只向 dmoe 要一张图；失败即失败，不降级到 illlights / local。"""
        try:
            return self._fetcher._try_dmoe(request_id)
        except requests.exceptions.Timeout:
            return CGResult(
                ok=False, request_id=request_id, source=self.key,
                message="dmoe 请求超时（单次请求上限 10 秒）。")
        except Exception as exc:
            return CGResult(
                ok=False, request_id=request_id, source=self.key,
                message="dmoe 加载失败：%s" % exc)


class UapiProProvider(ImageProvider):
    """UapiPro 图源 Provider。

    接口：``GET https://uapis.cn/api/v1/random/image``
    该接口 302 重定向到图片 URL，拿到的是**图片二进制**（不是 JSON），
    因此请求必须允许自动跟随重定向。

    分类由本 Provider 自己声明：``[(界面显示名, 参数字典), ...]``，
    参数字典直接作为 query 参数（``category`` / ``type``）。

    User-Agent 规则：
    - ``category=acg`` + ``type=pc`` -> :data:`UA_PC`
    - ``category=acg`` + ``type=mb`` -> :data:`UA_MOBILE`
    - 其它分类 -> :data:`BROWSER_UA`

    失败语义：网络异常 / HTTP 错误 / 超时 / 返回格式异常 / 拿到的不是图片，
    都算失败，统一返回 ``ok=False`` 的 :class:`CGResult`，
    **绝不在内部降级到别的图源**。
    """

    key = "uapipro"
    label = "UapiPro"

    def __init__(self, fetcher):
        self._fetcher = fetcher

    def categories(self) -> list:
        """本阶段暴露的分类（anime / general_anime / furry 暂不暴露）。"""
        return [
            ("二次元 · PC", {"category": "acg", "type": "pc"}),
            ("二次元 · 移动端", {"category": "acg", "type": "mb"}),
            ("风景", {"category": "landscape"}),
            ("壁纸 · PC", {"category": "pc_wallpaper"}),
            ("壁纸 · 移动端", {"category": "mobile_wallpaper"}),
            ("表情包", {"category": "bq"}),
            ("AI绘画", {"category": "ai_drawing"}),
        ]

    @staticmethod
    def _split(category):
        """把分类值拆成 ``(category, type)``。

        支持 ``{"category": ..., "type": ...}`` / ``(cat, type)`` / 纯字符串。
        """
        cat = typ = None
        if isinstance(category, dict):
            cat = category.get("category")
            typ = category.get("type")
        elif isinstance(category, (tuple, list)):
            if len(category) >= 1:
                cat = category[0]
            if len(category) >= 2:
                typ = category[1]
        elif category is not None:
            cat = category
        cat = str(cat).strip() if cat else ""
        typ = str(typ).strip() if typ else ""
        return (cat or None, typ or None)

    @staticmethod
    def ua_for(cat, typ) -> str:
        """按分类选 User-Agent（便于单独验证）。"""
        if cat == "acg" and typ == "pc":
            return UA_PC
        if cat == "acg" and typ == "mb":
            return UA_MOBILE
        return BROWSER_UA

    def fetch(self, category=None, request_id: int = 0) -> CGResult:
        """只向 UapiPro 要一张图；失败即失败，不降级到其它图源。"""
        cat, typ = self._split(category)
        params = {}
        if cat:
            params["category"] = cat
        if typ:
            params["type"] = typ
        headers = {"User-Agent": self.ua_for(cat, typ)}
        try:
            r = self._fetcher.session.get(
                UAPIPRO_IMG, params=params, headers=headers,
                timeout=self._fetcher.timeout, allow_redirects=True)
            r.raise_for_status()
            ctype = (r.headers.get("Content-Type") or "").lower()
            if not ctype.startswith("image/") or not r.content:
                raise ValueError("UapiPro 返回的不是图片内容")
            return self._fetcher._pack(
                r.content, ctype, r.url, self.key, False, request_id)
        except requests.exceptions.Timeout:
            return CGResult(
                ok=False, request_id=request_id, source=self.key,
                message="UapiPro 请求超时（单次请求上限 10 秒）。")
        except Exception as exc:
            return CGResult(
                ok=False, request_id=request_id, source=self.key,
                message="UapiPro 加载失败：%s" % exc)


class LoliApiProvider(ImageProvider):
    """LoliAPI 图源 Provider。

    端点（实现前已实测：302 重定向到图片，最终 200 + ``image/webp``）：
    - PC端   -> ``https://www.loliapi.com/acg/pc/``
    - 移动端 -> ``https://www.loliapi.com/acg/pe/``

    分类由本 Provider 自己声明：``[("PC端", "pc"), ("移动端", "pe")]``，
    分类值就是设备标识。

    User-Agent：``pc`` -> :data:`UA_PC`，``pe`` -> :data:`UA_MOBILE`
    （复用 B3 已定义的常量，不重复定义）。

    失败语义：网络异常 / HTTP 错误 / 超时 / 返回格式异常 / 拿到的不是图片，
    都算失败，统一返回 ``ok=False`` 的 :class:`CGResult`，
    **绝不在内部降级到别的图源**。
    """

    key = "loliapi"
    label = "LoliAPI"

    def __init__(self, fetcher):
        self._fetcher = fetcher

    def categories(self) -> list:
        """分类即设备：PC端 / 移动端。"""
        return [("PC端", "pc"), ("移动端", "pe")]

    @staticmethod
    def _norm(category):
        """把分类值规范成 ``"pc"`` / ``"pe"``；识别不了返回 None。"""
        val = category
        if isinstance(category, dict):
            val = (category.get("device") or category.get("type")
                   or category.get("category"))
        elif isinstance(category, (tuple, list)):
            val = category[0] if category else None
        val = str(val).strip().lower() if val else ""
        return val if val in ("pc", "pe") else None

    @staticmethod
    def ua_for(device) -> str:
        """``pc`` -> UA_PC；``pe`` -> UA_MOBILE（便于单独验证）。"""
        return UA_MOBILE if device == "pe" else UA_PC

    def fetch(self, category=None, request_id: int = 0) -> CGResult:
        """只向 LoliAPI 要一张图；失败即失败，不降级到其它图源。"""
        # 未指定分类时按 PC 端处理（UI 总会给出分类；CLI 可能不带）
        device = self._norm(category) or "pc"
        headers = {"User-Agent": self.ua_for(device)}
        try:
            r = self._fetcher.session.get(
                LOLIAPI_IMG[device], headers=headers,
                timeout=self._fetcher.timeout, allow_redirects=True)
            r.raise_for_status()
            ctype = (r.headers.get("Content-Type") or "").lower()
            if not ctype.startswith("image/") or not r.content:
                raise ValueError("LoliAPI 返回的不是图片内容")
            return self._fetcher._pack(
                r.content, ctype, r.url, self.key, False, request_id)
        except requests.exceptions.Timeout:
            return CGResult(
                ok=False, request_id=request_id, source=self.key,
                message="LoliAPI 请求超时（单次请求上限 10 秒）。")
        except Exception as exc:
            return CGResult(
                ok=False, request_id=request_id, source=self.key,
                message="LoliAPI 加载失败：%s" % exc)


class RandomCGFetcher:
    """illlights 主图库 + dmoe 备用图库 + 本地 CG。

    本地 CG 的「作品名」维度由 :mod:`cg_library` 提供（按游戏归类），
    通过 ``library_index`` 传入 games / screenshots 的映射信息。
    """

    def __init__(self, timeout=(5, 10), local_roots=None,
                 library_index: Optional[LibraryIndex] = None):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": BROWSER_UA,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        })
        # 本地 CG 作为第三级降级；传 None 表示不启用本地素材
        self.local_roots = [str(p) for p in (local_roots or []) if p]
        self.library_index = library_index or LibraryIndex()
        self._local_cache = None          # {游戏名: [绝对路径, ...]}
        self._local_cache_time = 0.0
        self._info_cache = None
        self._info_time = 0.0
        self._lock = threading.Lock()
        # 图源 Provider：B1 起 illlights、B2 起 dmoe 与本地图库、
        # B3 起 UapiPro、B5 起 LoliAPI 都已包装；
        # auto 模式由 _auto_poll 按固定优先级轮询（行为见该方法）
        self.providers = {
            "illlights": IlllightsProvider(self),
            "dmoe": DmoeProvider(self),
            "uapipro": UapiProProvider(self),
            "loliapi": LoliApiProvider(self),
            "local": LocalProvider(self),
        }

    # ------------------------------------------------------------------
    # info：作品名 / 分辨率筛选数据
    # ------------------------------------------------------------------
    def get_info(self, force: bool = False) -> dict:
        """获取 /v1/img/info；缓存 10 分钟，失败返回空 dict。"""
        now = time.time()
        if not force and self._info_cache is not None and now - self._info_time < 600:
            return self._info_cache
        try:
            r = self.session.get(MAIN_INFO, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                return {}
            with self._lock:
                self._info_cache = data
                self._info_time = now
            return data
        except Exception:
            return self._info_cache or {}

    # ------------------------------------------------------------------
    # 随机图：auto 按固定优先级轮询（illlights -> dmoe -> uapipro ->
    # loliapi -> local），任一成功立即返回；
    # 手动选某个图源（first / second / uapipro / loliapi / local）
    # 只调用对应 Provider，失败即失败、不降级
    # ------------------------------------------------------------------
    def fetch_random(self, name: Optional[str] = None,
                     size: Optional[str] = None,
                     request_id: int = 0,
                     source_mode: str = "auto") -> CGResult:
        """按图源模式随机取图。

        source_mode:
        - auto    : 按固定优先级轮询 illlights -> dmoe -> uapipro ->
                    loliapi -> local；任一成功立即停止，全部失败才返回失败
        - first   : 只调用 illlights（name=作品名, size=分辨率）；失败即失败
        - second  : 只调用 dmoe（不筛选）；失败即失败
        - uapipro : 只调用 UapiPro（name=category, size=type）；失败即失败
        - loliapi : 只调用 LoliAPI（name=设备 pc/pe）；失败即失败
        - local   : 只调用本地图库（name = 本地作品名）；失败即失败

        只有 auto 会轮询；手动模式一律只调用所选图源（手册红线）。

        筛选规则：
        - 只有 illlights 支持服务端筛选，name / size 才会作为作品名/分辨率；
        - uapipro 复用 name / size 两个槽位承载 category / type（见其 Provider），
          不改变 fetch_random 的签名；
        - loliapi 复用 name 槽位承载设备标识（pc / pe）；
        - auto 没有任何筛选维度，参数一律忽略，各 Provider 都不传分类；
        - local 的 name 是本地作品名，只用于挑本地文件，不会（也没法）
          丢给在线图库当筛选。

        B1：手动选 illlights 时走 IlllightsProvider，404 / 403 / 超时 /
        返回格式异常都算失败，直接返回失败结果，不再切换 dmoe / local。
        B2：手动选 dmoe（second）与本地图库（local）同理，失败即失败。
        B3：手动选 UapiPro（uapipro）同理，失败即失败、不降级。
        B5：手动选 LoliAPI（loliapi）同理，失败即失败、不降级。
        B6：只有 auto 走 _auto_poll 轮询；手动分支一行未改。
        """
        source_mode = str(source_mode or "auto")
        name = (name or "").strip() or None
        size = (size or "").strip() or None

        # 手动模式：只调用所选图源的 Provider，失败即失败，绝不降级
        if source_mode == "first":
            return self.providers["illlights"].fetch(
                category=(name, size), request_id=request_id)
        if source_mode == "second":
            return self.providers["dmoe"].fetch(request_id=request_id)
        if source_mode == "uapipro":
            params = {}
            if name:
                params["category"] = name
            if size:
                params["type"] = size
            return self.providers["uapipro"].fetch(
                category=params, request_id=request_id)
        if source_mode == "loliapi":
            # 分类即设备（pc / pe），沿用 name 槽位承载
            return self.providers["loliapi"].fetch(
                category=name, request_id=request_id)
        if source_mode == "local":
            try:
                result = self.providers["local"].fetch(
                    category=name, request_id=request_id)
            except Exception as exc:
                return CGResult(
                    ok=False, request_id=request_id, source="local",
                    message="本地图库加载失败：%s" % exc)
            if result is not None:
                return result
            return CGResult(
                ok=False, request_id=request_id, source="local",
                message="本地图库没有可用的图片（目录为空或文件无法读取）。")

        # auto（以及未知 mode 的兜底）：按固定优先级轮询，
        # 任一成功立即返回；全部失败时返回明确的失败结果
        return self._auto_poll(request_id)

    def _auto_poll(self, request_id: int) -> CGResult:
        """自动模式轮询：按固定优先级依次尝试，任一成功立即停止。

        优先级：illlights -> dmoe -> uapipro -> loliapi -> local。

        每个 Provider 都不传分类（分类只由手动模式下的 UI 提供），
        因此各自的入参语义不变：
        ``illlights=(None, None)`` / ``dmoe`` 忽略分类 / ``uapipro={}`` /
        ``loliapi=None``（内部默认 PC）/ ``local=None``（全部作品）。

        CGResult 的字段全部由各 Provider 现有实现决定，这里只做透传，
        不补字段、不改字段。全部失败时返回明确的「所有图源都加载失败」。
        """
        errors = []
        for key in ("illlights", "dmoe", "uapipro", "loliapi", "local"):
            try:
                r = self.providers[key].fetch(request_id=request_id)
                if r and r.ok:
                    return r
                if r is not None and getattr(r, "no_match", False):
                    # 记录，但不立即返回；继续尝试下一个
                    errors.append("%s: 无匹配" % key)
                else:
                    errors.append("%s: %s" % (
                        key, getattr(r, "message", "未知错误") if r else "无结果"))
            except Exception as exc:
                errors.append("%s: %s" % (key, exc))
        return CGResult(ok=False, request_id=request_id, source="auto",
                        message="所有图源都加载失败：" + " / ".join(errors))

    def _try_illlights(self, params: dict, name, size, request_id: int) -> CGResult:
        r = self.session.get(
            MAIN_IMG, params=params, timeout=self.timeout,
            allow_redirects=True,
        )
        if r.status_code == 404 and (name or size):
            raise _NoMatchError("当前筛选没有匹配的图片，请调整作品名或分辨率。")
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if not ctype.startswith("image/") or not r.content:
            raise ValueError("主图库返回的不是图片内容")
        return self._pack(r.content, ctype, r.url, "illlights", False, request_id)

    def _try_dmoe(self, request_id: int) -> CGResult:
        r = self.session.get(
            FALLBACK_IMG, timeout=self.timeout, allow_redirects=True,
        )
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if not ctype.startswith("image/") or not r.content:
            raise ValueError("备用图库返回的不是图片内容")
        return self._pack(r.content, ctype, r.url, "dmoe", True, request_id)

    # ------------------------------------------------------------------
    # 本地 CG（第三级图源，按游戏归类 / 筛选）
    # ------------------------------------------------------------------
    def _scan_local_cg(self, force: bool = False, categories=()):
        """扫描本地 CG 目录并按游戏分组：{游戏名: [绝对路径, ...]}。

        结果缓存 2 分钟；`_thumb.jpg` 缩略图会被跳过。
        """
        now = time.time()
        if (not force and self._local_cache is not None
                and now - self._local_cache_time < _LOCAL_CACHE_SECONDS):
            return self._local_cache
        by_game = cg_library.scan_library(
            self.local_roots, self.library_index, _LOCAL_EXTS, categories)
        self._local_cache = by_game
        self._local_cache_time = now
        return by_game

    def local_game_names(self, force: bool = False) -> list:
        """本地图库里出现过的游戏名（下拉框数据源，「未分类」排最后）。"""
        return cg_library.game_names(self._scan_local_cg(force))

    def reset_local_cache(self):
        """丢弃本地扫描缓存（目录结构 / 数据库归属变化后调用）。"""
        with self._lock:
            self._local_cache = None
            self._local_cache_time = 0.0
        return self

    def local_game_stats(self, force: bool = False) -> dict:
        """返回 {游戏名: 图片数}，供 UI 显示数量。"""
        by_game = self._scan_local_cg(force)
        return {name: len(paths) for name, paths in by_game.items()}

    def _pick_local_cg(self, request_id: int,
                       game_name: Optional[str] = None) -> Optional[CGResult]:
        """随机挑一张本地 CG；``game_name`` 为空 = 全部游戏，否则只在该游戏里挑。"""
        by_game = self._scan_local_cg()
        if not by_game:
            return None
        if game_name:
            files = list(by_game.get(game_name) or [])
        else:
            files = [p for paths in by_game.values() for p in paths]
        if not files:
            return None
        if len(files) > 1:
            files = random.sample(files, len(files))
        for path in files[:_LOCAL_PICK_TRIES]:
            result = self._load_local_file(path, request_id)
            if result is not None:
                return result
        return None

    def _load_local_file(self, path: str,
                         request_id: int) -> Optional[CGResult]:
        """读取单个本地文件并打包成 CGResult，失败返回 None。"""
        try:
            with open(path, "rb") as f:
                content = f.read()
            if not content:
                return None
            ext = os.path.splitext(path)[1].lower()
            ctype = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
                ".gif": "image/gif", ".bmp": "image/bmp",
            }.get(ext, "image/jpeg")
            try:
                uri = Path(path).resolve().as_uri()
            except Exception:
                uri = path.replace("\\", "/")
            result = self._pack(content, ctype, uri, "local", True, request_id)
            result.local_path = path
            result.game_name = cg_library.resolve_game_name(
                path, self.library_index)
            return result
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 解码 / 转码
    # ------------------------------------------------------------------
    def _pack(self, content: bytes, content_type: str, final_url: str,
              source: str, fallback: bool, request_id: int) -> CGResult:
        """Pillow 解码原图，生成 Qt 可显示的 JPEG 预览字节。"""
        with Image.open(io.BytesIO(content)) as im:
            im = ImageOps.exif_transpose(im)
            im.load()
            raw_fmt = (im.format or "").upper()
            width, height = im.size

            # 预览统一转 JPEG（保留 alpha 的图先铺白底），避免 Qt 不支持 AVIF 的问题
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                preview = bg
            else:
                preview = im.convert("RGB")
            buf = io.BytesIO()
            preview.save(buf, "JPEG", quality=92, optimize=True, progressive=True)
            display_bytes = buf.getvalue()

        ext = _IMAGE_EXTS.get(raw_fmt, "")
        if ext:
            download_bytes = content
            download_ext = ext
        else:
            # AVIF / HEIC 等格式转成 JPEG 保存，用户下载后能直接打开
            download_bytes = display_bytes
            download_ext = ".jpg"

        fmt_text = raw_fmt or (content_type.split("/")[-1].upper() if content_type else "IMAGE")
        return CGResult(
            ok=True, request_id=request_id,
            raw_bytes=content, display_bytes=display_bytes,
            url=final_url, source=source, fmt=fmt_text,
            width=width, height=height, fallback=fallback,
            download_bytes=download_bytes, download_ext=download_ext,
        )


# 便于命令行/独立测试使用
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="随机 CG API 测试")
    parser.add_argument("--info", action="store_true", help="只测试 /v1/img/info")
    parser.add_argument("--local", default=None,
                        help="本地 CG 根目录，打印按游戏分类的结果（可多次传）")
    parser.add_argument("--name", default=None, help="作品名，例如 ATRI")
    parser.add_argument("--size", default=None, help="分辨率，例如 720")
    parser.add_argument("--source", default="auto",
                        help="图源模式：auto/first/second/local")
    args = parser.parse_args()

    if args.local:
        fetcher = RandomCGFetcher(local_roots=[args.local])
        stats = fetcher.local_game_stats(force=True)
        print("local games =", len(stats))
        for name, count in sorted(stats.items(), key=lambda kv: str(kv[0])):
            print("  %-30s %d" % (name, count))
        raise SystemExit(0)

    fetcher = RandomCGFetcher()
    if args.info:
        info = fetcher.get_info(force=True)
        print("total =", info.get("total"))
        print("names =", info.get("names", [])[:10])
        print("sizes =", info.get("sizes", []))
    else:
        result = fetcher.fetch_random(args.name, args.size,
                                      source_mode=args.source)
        print("ok       =", result.ok)
        print("source   =", result.source)
        print("fallback =", result.fallback)
        print("no_match =", result.no_match)
        print("size     =", result.width, "x", result.height)
        print("format   =", result.fmt)
        print("url      =", result.url)
        print("message  =", result.message)
        if result.ok:
            print("display  =", len(result.display_bytes), "bytes")
            print("download =", len(result.download_bytes), "bytes", result.download_ext)
