# -*- coding: utf-8 -*-
"""????????? API ???Bangumi / VNDB / Steam / SteamGridDB / ????"""

import os
import io
import re
import time
import hashlib
import datetime
import urllib.parse
from PIL import Image, ImageOps

import config
from config import BANGUMI_UA, COVERS_DIR, get_bgm_token, get_sgdb_key, get_sauce_key, normalize_rel, _transpose

import requests


def _http_get(url, **kwargs):
    """GET 请求；若因本地证书链不全导致证书校验失败，则降级为不校验重试（只读公开接口）。"""
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError:
        kwargs.pop("verify", None)
        return requests.get(url, verify=False, **kwargs)


def _http_post(url, **kwargs):
    """POST 请求；若因本地证书链不全导致证书校验失败，则降级为不校验重试（只读公开接口）。"""
    try:
        return requests.post(url, **kwargs)
    except requests.exceptions.SSLError:
        kwargs.pop("verify", None)
        return requests.post(url, verify=False, **kwargs)


def _bangumi_search(keyword: str) -> list:
    """调用 Bangumi 搜索，返回统一字典列表；已配置令牌时优先走新版接口（可含 R18）。"""
    token = get_bgm_token()
    if token:
        try:
            res = _bangumi_search_v0(keyword, token)
            if res:
                return res
        except Exception:
            pass
    return _bangumi_search_legacy(keyword)


def _extract_infobox_value(value):
    """把 Bangumi infobox 的值（字符串或 [{'v':...}] 列表）转成字符串。"""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for v in value:
            if isinstance(v, dict) and "v" in v:
                parts.append(str(v["v"]))
            elif isinstance(v, str):
                parts.append(v)
        return " / ".join(p for p in parts if p)
    if isinstance(value, dict) and "v" in value:
        return str(value["v"])
    return str(value)


def _bangumi_search_v0(keyword: str, token: str) -> list:
    """Bangumi 新版 API 搜索（可返回 R18，需要个人令牌）。"""
    url = "https://api.bgm.tv/v0/search/subjects"
    payload = {"keyword": keyword, "filter": {"type": [4]}}
    headers = {"User-Agent": BANGUMI_UA, "Content-Type": "application/json",
               "Authorization": "Bearer " + token}
    resp = _http_post(url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    items = (resp.json().get("data") or [])[:30]
    results = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "")
        name_cn = str(it.get("name_cn") or name)
        date = str(it.get("date") or "")
        images = it.get("images") or {}
        cover = (images.get("large") or images.get("common")
                 or images.get("medium") or images.get("small") or "")
        if isinstance(cover, str) and cover.startswith("//"):
            cover = "https:" + cover
        developer = ""
        for kv in it.get("infobox") or []:
            key = str(kv.get("key") or "")
            if "开发" in key or key in ("developer", "发行商"):
                developer = _extract_infobox_value(kv.get("value"))
                break
        results.append({
            "id": it.get("id"),
            "name": name,
            "name_cn": name_cn,
            "date": date,
            "cover": cover,
            "developer": developer,
            "source": "bangumi",
        })
    return results


def _bangumi_search_legacy(keyword: str) -> list:
    """Bangumi 旧版公开接口搜索（无需令牌）。"""
    url = "https://api.bgm.tv/search/subject/" + urllib.parse.quote(keyword) + "?type=4"
    resp = _http_get(url, headers={"User-Agent": BANGUMI_UA}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        items = data.get("list") or data.get("data") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    results = []
    for it in items[:30]:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "")
        name_cn = str(it.get("name_cn") or name)
        date = str(it.get("date") or "")
        images = it.get("images") or {}
        cover = (images.get("large") or images.get("common")
                 or images.get("medium") or images.get("small") or "")
        if isinstance(cover, str) and cover.startswith("//"):
            cover = "https:" + cover
        developer = ""
        for kv in it.get("infobox") or []:
            key = str(kv.get("key") or "")
            if key in ("开发", "开发商", "开发公司", "developer", "开发厂商"):
                developer = str(kv.get("value") or "")
                break
        results.append({
            "id": it.get("id"),
            "name": name,
            "name_cn": name_cn,
            "date": date,
            "cover": cover,
            "developer": developer,
            "source": "bangumi",
        })
    return results


def _map_bgm_status(t) -> str:
    """把 Bangumi 收藏类型(1想看/2在看/3看过/4搁置/5抛弃)映射为本地状态。"""
    return {1: "想玩", 2: "正在玩", 3: "通关", 4: "搁置", 5: "放弃"}.get(int(t or 0), "想玩")


def _split_rating(r: float):
    """把一个 0-10 的总评分按比例拆成三维（剧本0-5/角色0-3/视听0-2），避免导入后评分归零。"""
    r = float(r or 0)
    if r <= 0:
        return 0.0, 0.0, 0.0
    return (round(min(5, r * 0.5), 1),
            round(min(3, r * 0.3), 1),
            round(min(2, r * 0.2), 1))


def _vndb_search(keyword: str) -> list:
    """调用 VNDB Kana API 搜索，返回统一的字典列表。"""
    url = "https://api.vndb.org/kana/vn"
    payload = {
        "filters": ["search", "=", keyword],
        "fields": "id, title, alttitle, olang, titles.title, titles.lang, "
                  "developers.name, released, image.url",
        "sort": "searchrank",
        "results": 30,
    }
    headers = {"User-Agent": BANGUMI_UA, "Content-Type": "application/json"}
    resp = _http_post(url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("results") or []
    results = []
    for it in items[:30]:
        if not isinstance(it, dict):
            continue
        main_title = str(it.get("title") or "")
        alttitle = str(it.get("alttitle") or "")
        olang = str(it.get("olang") or "").lower()
        titles = it.get("titles") or []
        zh = next((t for t in titles
                   if str(t.get("lang") or "").lower().startswith("zh")), None)
        name_cn = str((zh or {}).get("title") or "")
        # 原名：优先原语言标题，其次日文，再次 alttitle，最后主标题（罗马音）
        orig = None
        if olang:
            orig = next((t for t in titles
                         if str(t.get("lang") or "").lower() == olang), None)
        if orig is None:
            orig = next((t for t in titles if t.get("lang") == "ja"), None)
        name = str((orig or {}).get("title") or alttitle or main_title)
        if not name_cn:
            name_cn = name
        devs = it.get("developers") or []
        dev = str(devs[0].get("name") or "") if devs else ""
        image = it.get("image") or {}
        cover = str(image.get("url") or "")
        results.append({
            "id": it.get("id"),
            "name": name,
            "name_cn": name_cn,
            "date": str(it.get("released") or ""),
            "cover": cover,
            "developer": dev,
            "source": "vndb",
        })
    return results


def _normalize_steam_date(raw: str) -> str:
    """把 Steam 英文日期（如 'Nov 23, 2015' / '23 Nov 2015'）转成 YYYY-MM-DD。"""
    t = str(raw or "").strip()
    if not t:
        return ""
    # 中文格式：'2025 年 3 月 27 日' / '2025年3月27日'
    mcn = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", t)
    if mcn:
        return "%s-%s-%s" % (mcn.group(1), mcn.group(2).zfill(2), mcn.group(3).zfill(2))
    months = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    # 形式 1：'Nov 23, 2015'
    m = re.match(r"([A-Za-z]{3,})\s+(\d{1,2})[,]?\s+(\d{4})", t)
    if m:
        mon, day, yr = m.group(1), m.group(2), m.group(3)
        mm = months.get(mon[:3].lower())
        if mm:
            return "%s-%s-%s" % (yr, mm, day.zfill(2))
    # 形式 2：'23 Nov, 2015'
    m2 = re.match(r"(\d{1,2})\s+([A-Za-z]{3,})[,]?\s+(\d{4})", t)
    if m2:
        day, mon, yr = m2.group(1), m2.group(2), m2.group(3)
        mm = months.get(mon[:3].lower())
        if mm:
            return "%s-%s-%s" % (yr, mm, day.zfill(2))
    return t


def _steam_detail(appid, lang: str = "schinese"):
    """获取单个 Steam 应用详情（开发者 / 发售日 / 封面），lang 控制返回语言。"""
    url = "https://store.steampowered.com/api/appdetails"
    resp = _http_get(url, params={"appids": appid, "cc": "us", "l": lang},
                     headers={"User-Agent": BANGUMI_UA}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    d = data.get(str(appid)) or {}
    if not d.get("success"):
        return {}
    return d.get("data") or {}


def _steam_search(keyword: str, detail_limit: int = 5) -> list:
    """调用 Steam 商店公开搜索接口，按多语言检索并去重，返回统一字典列表。"""
    s_url = "https://store.steampowered.com/api/storesearch/"
    merged = {}
    # 中文检索可同时命中中文名与英文名（含未本地化的游戏），命中即停，仅中文无结果时补英文
    for l in ("schinese", "en"):
        try:
            resp = _http_get(s_url, params={"term": keyword, "cc": "us", "l": l},
                             headers={"User-Agent": BANGUMI_UA}, timeout=15)
            resp.raise_for_status()
            items = (resp.json().get("items") or [])[:12]
        except Exception:
            continue
        for it in items:
            appid = it.get("id")
            if appid and appid not in merged:
                merged[appid] = it
        if merged:
            break
    if not merged:
        return []
    results = []
    for i, (appid, it) in enumerate(merged.items()):
        if i < detail_limit:
            d_zh = _steam_detail(appid, "schinese")
            name_cn = d_zh.get("name") or it.get("name") or ""
            # 中文名含中日韩字符时才额外查英文原名，避免和中文标题重复；否则直接用显示名
            d_en = _steam_detail(appid, "english") if _has_cjk(name_cn) else {}
            name_ja = d_en.get("name") or ""
            devs = d_zh.get("developers") or []
            date = _normalize_steam_date((d_zh.get("release_date") or {}).get("date") or "")
        else:
            name_cn = it.get("name") or ""
            name_ja = ""
            devs = []
            date = ""
        name = name_ja or name_cn
        dev = " / ".join(str(x) for x in devs)
        cover = _steam_library_cover(appid)
        results.append({
            "id": appid,
            "name": name,
            "name_cn": name_cn,
            "date": date,
            "cover": cover,
            "developer": dev,
            "source": "steam",
        })
    # 合并 SteamGridDB 社区竖版封面（已配置 API Key 时）；匹配上的改用社区图，未匹配的补进列表
    sgdb_key = get_sgdb_key()
    if sgdb_key:
        try:
            sgdb = _sgdb_search(keyword, sgdb_key, detail_limit=min(detail_limit, 5))
            if sgdb:
                index = {}
                for r in results:
                    for k in (_name_key(r.get("name_cn")), _name_key(r.get("name"))):
                        if k:
                            index.setdefault(k, r)
                matched = set()
                kw = _name_key(keyword)
                for s in sgdb:
                    sk = _name_key(s.get("name"))
                    r = index.get(sk)
                    if r is not None and id(r) not in matched:
                        if s.get("cover"):
                            r["cover"] = s["cover"]
                        matched.add(id(r))
                    elif s.get("cover") and (not kw or kw in sk):
                        results.append(s)
        except Exception:
            pass
    return results


def _has_cjk(s: str) -> bool:
    """判断字符串是否含中日韩统一表意文字（多为中文/日文名）。"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(s))


def _name_key(s: str) -> str:
    """归一化名称用于匹配（去空白、转小写）。"""
    return re.sub(r"\s+", "", str(s or "")).lower()


def _steam_library_cover(appid) -> str:
    """构造 Steam 竖版库封面 URL（600×900，适合做封面）；少数游戏可能无此图。"""
    return "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/%s/library_600x900.jpg" % appid


def _sgdb_search(keyword: str, api_key: str, detail_limit: int = 5) -> list:
    """用 SteamGridDB 社区库搜索游戏，返回竖版网格封面 + 名称/发售日。"""
    if not api_key:
        return []
    headers = {"User-Agent": BANGUMI_UA, "Authorization": "Bearer " + api_key,
               "Accept": "application/json"}
    url = "https://www.steamgriddb.com/api/v2/search/autocomplete/" + urllib.parse.quote(keyword)
    resp = _http_get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    games = (resp.json().get("data") or [])[:max(1, detail_limit)]
    results = []
    for g in games:
        name = str(g.get("name") or "")
        sgid = g.get("id")
        release = g.get("release_date")
        date = ""
        if release:
            try:
                date = datetime.datetime.utcfromtimestamp(int(release)).strftime("%Y-%m-%d")
            except Exception:
                date = ""
        cover = ""
        # 取竖版社区网格图（600x900）
        try:
            gurl = "https://www.steamgriddb.com/api/v2/grids/game/%s" % sgid
            gj = _http_get(gurl, headers=headers, timeout=15).json()
            grids = gj.get("data") or []
            for gr in grids:
                if str(gr.get("width")) == "600" and str(gr.get("height")) == "900" and gr.get("url"):
                    cover = gr["url"]
                    break
            if not cover and grids:
                cover = grids[0].get("url", "")
        except Exception:
            cover = ""
        results.append({
            "id": sgid,
            "name": name,
            "name_cn": name,
            "date": date,
            "cover": cover,
            "developer": "",
            "source": "steamgriddb",
        })
    return results


def _search_by_source(source: str, key: str, detail_limit: int = 5) -> list:
    """按数据源分发搜索，统一返回字典列表。"""
    if source == "steamgriddb":
        return _sgdb_search(key, get_sgdb_key(), detail_limit=detail_limit)
    if source == "steam":
        return _steam_search(key, detail_limit=detail_limit)
    if source == "vndb":
        return _vndb_search(key)
    return _bangumi_search(key)


def _download_cover(url: str, subject_id):
    """下载封面并压缩保存，返回 (相对路径, 绝对路径)。"""
    try:
        resp = _http_get(url, headers={"User-Agent": BANGUMI_UA}, timeout=30)
        resp.raise_for_status()
    except Exception:
        # Steam 竖版库封面可能缺失，回退到同一游戏的横版 header
        mm = re.match(r"(https://shared\.akamai\.steamstatic\.com/store_item_assets/steam/apps/\d+)/library_[^/]+\.jpg", url)
        if not mm:
            raise
        url = mm.group(1) + "/header.jpg"
        resp = _http_get(url, headers={"User-Agent": BANGUMI_UA}, timeout=30)
        resp.raise_for_status()
    raw = resp.content
    img = Image.open(io.BytesIO(raw))
    img = _transpose(img)
    if img.mode in ("P", "RGBA", "LA"):
        img = img.convert("RGB")
    img.thumbnail((500, 700))
    # 按“处理后图片内容”的 MD5 命名：同图只存一份，重复下载直接复用。
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    data = buf.getvalue()
    key = hashlib.md5(data).hexdigest()
    fname = f"cover_{key}.jpg"
    abs_path = os.path.join(COVERS_DIR, fname)
    if not os.path.isfile(abs_path):
        with open(abs_path, "wb") as f:
            f.write(data)
    rel_path = normalize_rel(os.path.join("data", "covers", fname))
    return rel_path, abs_path


# ============================================================
# 详情抓取（VNDB / Bangumi）
#   供「智能填充」与每栏 🔎 按钮使用。
#   两个数据源统一转成同一个 detail 字典；缓存 key = (source, subject_id)。
#   注意：VNDB 限流约 200 请求/5 分钟，必须靠缓存避免重复请求。
# ============================================================

_detail_cache = {}


def _detail_key(source, subject_id):
    """缓存 key：数据源 + 条目 id。"""
    return (str(source or "").strip().lower(), str(subject_id or "").strip())


def peek_detail(source, subject_id):
    """只读缓存、不联网。命中返回 detail 字典，否则返回 None。"""
    return _detail_cache.get(_detail_key(source, subject_id))


def get_detail(source, subject_id, force=False):
    """抓取详情（带缓存）。source 支持 'vndb' / 'bangumi'。"""
    key = _detail_key(source, subject_id)
    if not force and key in _detail_cache:
        return _detail_cache[key]
    if key[0] == "vndb":
        detail = _vndb_detail(key[1])
    elif key[0] == "bangumi":
        detail = _bangumi_detail(key[1])
    else:
        raise ValueError("该数据源暂不支持详情抓取：%s" % source)
    _detail_cache[key] = detail
    return detail


def clear_detail_cache():
    """清空详情缓存（排查问题/切换数据源时可用）。"""
    _detail_cache.clear()


def _uniq(seq):
    """去重并保持原顺序（顺手去掉空值）。"""
    out, seen = [], set()
    for x in seq or []:
        s = str(x or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _uniq_by(items, keyfunc):
    """按 keyfunc 去重并保持原顺序（用于 dict 列表）。"""
    out, seen = [], set()
    for it in items or []:
        k = keyfunc(it)
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def _tidy_multi(s):
    """把「枕、けろ枕」/「A / B」这类多值串统一成「A, B」。"""
    t = str(s or "").strip()
    if not t:
        return ""
    parts = re.split(r"[、,，/／|｜;；]+", t)
    return ", ".join(p.strip() for p in parts if p.strip())


# ---------- VNDB ----------

# staff.role -> 中文。只保留创作岗；VNDB 里大量 role="staff" 的杂项直接丢掉。
_VNDB_ROLE_CN = {
    "scenario": "剧本", "writer": "剧本", "script": "剧本",
    "chardesign": "角色设计", "art": "原画", "artist": "原画",
    "music": "音乐", "composer": "作曲", "songs": "主题歌", "vocals": "演唱",
    "director": "导演", "producer": "制作人", "editor": "剪辑",
}
_VNDB_KEEP_ROLES = tuple(_VNDB_ROLE_CN.keys())


def _vndb_detail(vn_id) -> dict:
    """一次 POST 拿全 VNDB 详情，转成统一 detail 结构。

    注意：va 必须写成 va.staff.* / va.character.*，写 va.name 会 400。
    """
    url = "https://api.vndb.org/kana/vn"
    fields = ("id,title,alttitle,olang,titles.title,titles.lang,released,"
              "developers.name,developers.original,image.url,description,length_minutes,"
              "tags.name,tags.rating,tags.category,tags.spoiler,"
              "staff.name,staff.original,staff.role,"
              "va.staff.name,va.staff.original,va.character.name,va.character.original,va.note")
    payload = {"filters": ["id", "=", str(vn_id)], "fields": fields, "results": 1}
    headers = {"User-Agent": BANGUMI_UA, "Content-Type": "application/json"}
    resp = _http_post(url, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    items = resp.json().get("results") or []
    if not items:
        raise ValueError("VNDB 未找到该条目：%s" % vn_id)
    it = items[0]

    # ---- 标题：中文优先；原名取原语言标题 ----
    titles = it.get("titles") or []
    main = str(it.get("title") or "")
    alt = str(it.get("alttitle") or "")
    olang = str(it.get("olang") or "").lower()

    def _title_of(lang):
        return next((str(t.get("title") or "").strip() for t in titles
                     if str(t.get("lang") or "").lower() == lang), "")

    zh = next((str(t.get("title") or "").strip() for t in titles
               if str(t.get("lang") or "").lower().startswith("zh")), "")
    orig = (_title_of(olang) if olang else "") or _title_of("ja")
    title = zh or alt or main
    title_jp = orig or alt or main

    # ---- 开发商 ----
    devs = it.get("developers") or []
    developer = ""
    if devs:
        developer = str(devs[0].get("original") or devs[0].get("name") or "").strip()

    # ---- 类型 / 标签：按 rating 从高到低；cont 当类型，tech/ero 当标签 ----
    ranked = sorted(it.get("tags") or [],
                    key=lambda t: float(t.get("rating") or 0), reverse=True)
    genres = _uniq([t.get("name") for t in ranked
                    if str(t.get("category")) == "cont"])[:12]
    tags = _uniq([t.get("name") for t in ranked
                  if str(t.get("category")) in ("tech", "ero")])[:12]

    # ---- 角色 / 声优：va 里本来就是成对数据 ----
    characters, voices = [], []
    for row in it.get("va") or []:
        if not isinstance(row, dict):
            continue
        ch = row.get("character") or {}
        st = row.get("staff") or {}
        cname = str(ch.get("original") or ch.get("name") or "").strip()
        vname = str(st.get("original") or st.get("name") or "").strip()
        if cname:
            characters.append({"name": cname, "cv": vname, "relation": ""})
            if vname:
                voices.append(vname)
    # VNDB 存在同一角色挂两个 cid 的重复条目，按 (角色, 声优) 去重
    characters = _uniq_by(characters, lambda c: (c["name"], c["cv"]))

    # ---- 制作人员 ----
    staff = []
    for s in it.get("staff") or []:
        if not isinstance(s, dict):
            continue
        role = str(s.get("role") or "").strip().lower()
        if role not in _VNDB_KEEP_ROLES:
            continue
        name = str(s.get("original") or s.get("name") or "").strip()
        if name:
            staff.append({"role": _VNDB_ROLE_CN[role], "name": name})
    staff = _uniq_by(staff, lambda s: (s["role"], s["name"]))

    # ---- 时长：分钟 -> 小时 ----
    minutes = it.get("length_minutes")
    play_time = 0
    try:
        if minutes:
            play_time = int(round(float(minutes) / 60.0))
    except (TypeError, ValueError):
        play_time = 0

    return {
        "source": "vndb",
        "id": str(it.get("id") or vn_id),
        "title": title,
        "title_jp": title_jp,
        "developer": developer,
        "publisher": "",          # VNDB 没有发行商概念
        "release_date": str(it.get("released") or ""),
        "cover": str((it.get("image") or {}).get("url") or ""),
        "summary": str(it.get("description") or ""),
        "genres": genres,
        "tags": tags,
        "characters": characters,
        "voices": _uniq(voices),
        "staff": staff,
        "play_time": play_time,
        "has_summary_zh": False,  # VNDB 简介是英文，默认不勾
    }


# ---------- Bangumi ----------

# persons.relation / infobox key 里算「制作人员」的关键词（开发、发行另有归属）
_BGM_STAFF_KEYWORDS = (
    "剧本", "シナリオ", "脚本", "scenario", "原画", "art",
    "音乐", "音楽", "music", "企画", "制作人", "producer",
    "导演", "監督", "主题歌", "插入歌", "角色设计", "人设", "人物设定",
)


def _bgm_infobox(d) -> dict:
    """infobox -> {小写 key: 字符串值}。"""
    info = {}
    for kv in d.get("infobox") or []:
        if isinstance(kv, dict):
            k = str(kv.get("key") or "").strip().lower()
            if k:
                info[k] = _extract_infobox_value(kv.get("value"))
    return info


def _bangumi_detail(subject_id) -> dict:
    """三跳抓 Bangumi 详情：subject(简介/infobox) + characters(角色/声优) + persons(制作人员)。

    characters / persons 走 best-effort：任一失败只丢该部分，不影响其它字段。

    ⚠️ R18 / 受限条目在 v0 接口里【只对带令牌的请求可见】：不带令牌时接口会假装
    "条目不存在"而返回 404。搜索那边本来就带了令牌（所以这类条目会出现在搜索结果里），
    详情这边以前漏了 —— 于是用户选中 R18 条目必然报 404（但浏览器里登录后能正常打开）。
    """
    headers = {"User-Agent": BANGUMI_UA, "Accept": "application/json"}
    _token = get_bgm_token()
    if _token:
        headers["Authorization"] = "Bearer " + _token          # ← 受限条目必需
    base = "https://api.bgm.tv/v0/subjects/" + urllib.parse.quote(str(subject_id))
    resp = _http_get(base, headers=headers, timeout=20)
    if resp.status_code == 401:
        raise ValueError("Bangumi 令牌无效或已过期：请到「设置 → API 与账号」重新获取令牌，或换个数据源。")
    if resp.status_code == 404:
        if _token:
            raise ValueError(
                "Bangumi 返回 404：该条目可能已被删除/合并，或当前令牌无权访问。\n"
                "可到「设置 → API 与账号」检查令牌，或换个数据源。")
        raise ValueError(
            "Bangumi 返回 404：该条目可能是 R18 / 受限条目。\n"
            "受限条目在没有令牌时对接口不可见（浏览器里登录后能看）。\n"
            "请先到「设置 → API 与账号」填写 Bangumi 访问令牌，或换个数据源。")
    resp.raise_for_status()
    d = resp.json()
    if not isinstance(d, dict) or not d.get("id"):
        raise ValueError("Bangumi 未找到该条目：%s" % subject_id)

    info = _bgm_infobox(d)

    def pick(*names):
        for n in names:
            v = info.get(str(n).strip().lower())
            if v:
                return str(v).strip()
        return ""

    # ---- 角色 + 声优 ----
    characters, voices = [], []
    try:
        chs = _http_get(base + "/characters", headers=headers, timeout=20).json() or []
    except Exception:
        chs = []
    for c in chs:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        actors = c.get("actors") or []
        cv = ""
        if actors and isinstance(actors[0], dict):
            cv = str(actors[0].get("name") or "").strip()
        characters.append({"name": name, "cv": cv,
                           "relation": str(c.get("relation") or "").strip()})
        if cv:
            voices.append(cv)
    characters = _uniq_by(characters, lambda c: (c["name"], c["cv"]))

    # ---- 制作人员 ----
    staff = []
    try:
        ps = _http_get(base + "/persons", headers=headers, timeout=20).json() or []
    except Exception:
        ps = []
    for p in ps:
        if not isinstance(p, dict):
            continue
        rel = str(p.get("relation") or "").strip()
        name = str(p.get("name") or "").strip()
        if name and rel and any(k in rel for k in _BGM_STAFF_KEYWORDS):
            staff.append({"role": rel, "name": name})
    staff = _uniq_by(staff, lambda s: (s["role"], s["name"]))
    if not staff:
        # 回退：persons 拿不到时，用 infobox 里的聚合串（「剧本 = A、B」）
        for rel, keys in (("剧本", ("剧本", "シナリオ", "脚本")),
                          ("原画", ("原画",)),
                          ("音乐", ("音乐", "音楽"))):
            for nm in re.split(r"[、,，/／]+", pick(*keys)):
                nm = nm.strip()
                if nm:
                    staff.append({"role": rel, "name": nm})

    images = d.get("images") or {}
    raw_genres = pick("游戏类型", "类型", "ジャンル", "genre", "genres")
    return {
        "source": "bangumi",
        "id": str(d.get("id") or subject_id),
        "title": str(d.get("name_cn") or d.get("name") or ""),
        "title_jp": str(d.get("name") or ""),
        "developer": _tidy_multi(pick("开发", "开发商", "開発", "develop", "developer",
                                      "制作公司", "制作")),
        "publisher": _tidy_multi(pick("发行", "发行商", "発売", "publisher", "出版")),
        "release_date": str(d.get("date") or pick("发行日期", "发售日期", "発売日") or ""),
        "cover": str(images.get("large") or images.get("common")
                     or images.get("medium") or ""),
        "summary": str(d.get("summary") or ""),
        "genres": _uniq(re.split(r"[、,，/／|｜]+", raw_genres)),
        "tags": _uniq([t.get("name") for t in (d.get("tags") or [])
                       if isinstance(t, dict)
                       and not re.match(r"^\d{4}(-\d{1,2})?$",
                                        str(t.get("name") or "").strip())])[:15],
        "characters": characters,
        "voices": _uniq(voices),
        "staff": staff,
        "play_time": 0,
        "has_summary_zh": True,   # Bangumi 简介是中文
    }


# ============================================================
# Identify CG / screenshot -> find the work & character
#   sources: AnimeTrace (no key), SauceNAO (key), dio.jite.me (no key)
# ============================================================
_IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
}


_ANIMETRACE_MODEL_CACHE = None


def _pick_animetrace_model() -> str:
    """Get the enabled default model for AnimeTrace; fall back to a good name.

    结果会缓存，避免每次识图都先发一次 model/list 请求拖慢速度。
    """
    global _ANIMETRACE_MODEL_CACHE
    if _ANIMETRACE_MODEL_CACHE:
        return _ANIMETRACE_MODEL_CACHE
    try:
        resp = _http_get("https://api.animetrace.com/v1/model/list", timeout=15)
        resp.raise_for_status()
        d = resp.json() or {}
        data = d.get("data") or []
        for m in data:
            if m.get("enabled") and m.get("default"):
                _ANIMETRACE_MODEL_CACHE = str(m.get("id") or "animetrace_high_beta")
                return _ANIMETRACE_MODEL_CACHE
        for m in data:
            if m.get("enabled"):
                _ANIMETRACE_MODEL_CACHE = str(m.get("id") or "animetrace_high_beta")
                return _ANIMETRACE_MODEL_CACHE
    except Exception:
        pass
    _ANIMETRACE_MODEL_CACHE = "animetrace_high_beta"
    return _ANIMETRACE_MODEL_CACHE


def _animetrace_search(image_path: str) -> list:
    """AnimeTrace identify, return unified list: [{work, character, score, source}]."""
    model = _pick_animetrace_model()
    with open(image_path, "rb") as f:
        ext = os.path.splitext(image_path)[1].lower() or ".jpg"
        mime = _IMAGE_MIME.get(ext, "image/jpeg")
        files = {"file": (os.path.basename(image_path), f, mime)}
        resp = _http_post("https://api.animetrace.com/v1/search",
                          data={"model": model, "is_multi": "1", "ai_detect": "1"},
                          files=files, timeout=30)
    resp.raise_for_status()
    d = resp.json() or {}
    results = []
    seen = set()
    for box in (d.get("data") or []):
        # 每个检测框取前若干候补（已按可能性排序），并做 (作品, 角色) 去重
        chars = box.get("character") or []
        for ch in chars[:3]:
            work = str(ch.get("work") or "").strip()
            char = str(ch.get("character") or "").strip()
            if not work:
                continue
            try:
                score = float(ch.get("score") or ch.get("similarity") or 0)
            except (TypeError, ValueError):
                score = 0.0
            key = (work, char)
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "work": work,
                "character": char,
                "score": score,
                "source": "AnimeTrace",
            })
    return results


def _saucenao_search(image_path: str, api_key: str) -> list:
    """SauceNAO identify (needs API key), return unified list."""
    if not api_key:
        raise ValueError("尚未填写 SauceNAO API Key，请先在“设置 → 账号”或识图窗口里填入。")
    with open(image_path, "rb") as f:
        ext = os.path.splitext(image_path)[1].lower() or ".jpg"
        mime = _IMAGE_MIME.get(ext, "image/jpeg")
        data = {
            "api_key": api_key,
            "output_type": "2",
            "numres": "8",
            "db": "999",
            "dedupe": "2",
            "hide": "0",
        }
        headers = {"User-Agent": "GalgameInfoManager/1.0 (local offline desktop app)"}
        files = {"file": (os.path.basename(image_path), f, mime)}
        resp = _http_post("https://saucenao.com/search.php",
                          data=data, files=files, headers=headers, timeout=30)
    resp.raise_for_status()
    d = resp.json() or {}
    header = d.get("header") or {}
    status = header.get("status", -1)
    if status == 429:
        short = header.get("short_remaining")
        long_ = header.get("long_remaining")
        msg = "SauceNAO 请求次数受限，请稍后再试。"
        if short is not None:
            msg += "\n短期剩余：%s" % short
        if long_ is not None:
            msg += "\n长期剩余（今天）：%s" % long_
        raise ValueError(msg)
    if status == 5:
        raise ValueError("SauceNAO 请求次数受限，请稍后再试。")
    if status == 6:
        raise ValueError("SauceNAO 当日搜索次数已用尽，请明天再试。")
    if status != 0:
        raise ValueError("SauceNAO 返回错误（状态码 %s），请检查 API Key 是否有效。" % status)
    min_sim = header.get("minimum_similarity")
    try:
        min_sim = float(min_sim) if min_sim is not None else None
    except (TypeError, ValueError):
        min_sim = None
    results = []
    for item in (d.get("results") or []):
        h = item.get("header") or {}
        dd = item.get("data") or {}
        try:
            sim = float(h.get("similarity") or 0)
        except (TypeError, ValueError):
            sim = 0.0
        if min_sim is not None and sim < min_sim:
            continue
        urls = dd.get("ext_urls") or []
        title = (dd.get("title") or dd.get("source") or dd.get("material")
                 or dd.get("eng_name") or "")
        author = (dd.get("author_name") or dd.get("member_name")
                  or dd.get("creator") or dd.get("pawoo_username")
                  or dd.get("twitter_username") or "")
        thumbnail = h.get("thumbnail") or ""
        page = dd.get("page_url") or ""
        # SauceNAO 缩略图常为相对路径，补全为完整 URL
        if thumbnail and thumbnail.startswith("/"):
            thumbnail = "https://saucenao.com" + thumbnail
        if title:
            results.append({
                "work": str(title).strip(),
                "character": str(author).strip(),
                "score": sim,
                "source": "SauceNAO",
                "url": (str(urls[0]) if urls else str(page)),
                "index": str(h.get("index_name") or h.get("index_id") or ""),
                "similarity": sim,
                "thumbnail": str(thumbnail),
                "page_url": str(page),
            })
    return results


def _dio_search(image_path: str) -> list:
    """dio.jite.me face identify (no key), return unified list."""
    with open(image_path, "rb") as f:
        ext = os.path.splitext(image_path)[1].lower() or ".jpg"
        mime = _IMAGE_MIME.get(ext, "image/jpeg")
        files = {"file": (os.path.basename(image_path), f, mime)}
        resp = _http_post("https://dio.jite.me/api/recognize",
                          data={"use_correction": "1"},
                          files=files, timeout=30)
    resp.raise_for_status()
    d = resp.json() or {}
    results = []
    for face in (d.get("faces") or []):
        anime = str(face.get("anime") or "").strip()
        name = str(face.get("name") or "").strip()
        try:
            score = float(face.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if anime:
            results.append({
                "work": anime,
                "character": name,
                "score": score,
                "source": "dio.jite.me",
            })
    return results


def _identify_image(image_path: str, source: str) -> list:
    """Dispatch by source. source: animetrace / saucenao / dio."""
    source = (source or "").lower()
    if source == "animetrace":
        rows = _animetrace_search(image_path)
    elif source == "saucenao":
        rows = _saucenao_search(image_path, get_sauce_key())
    elif source == "dio":
        rows = _dio_search(image_path)
    else:
        raise ValueError("未知的识图源：%s" % source)
    # 统一归一化：把数据源里误写成 ASCII '=' 的日文中点还原成 '・'（对所有源生效）
    for r in rows:
        r["work"] = str(r.get("work") or "").replace("=", "・").strip()
        r["character"] = str(r.get("character") or "").replace("=", "・").strip()
    # 统一去重，(work, character) 相同则只保留第一条
    seen = set()
    out = []
    for r in rows:
        key = (str(r.get("work") or "").strip(), str(r.get("character") or "").strip())
        if not key[0]:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ============================================================
# 后台线程
# ============================================================
