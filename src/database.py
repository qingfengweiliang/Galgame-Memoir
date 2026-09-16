# -*- coding: utf-8 -*-
"""SQLite 数据库封装模块。"""

import sqlite3


class Database:
    """SQLite 数据库封装。"""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_tables()

    def _init_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                title_jp    TEXT DEFAULT '',
                developer   TEXT DEFAULT '',
                release_date TEXT DEFAULT '',
                status      TEXT DEFAULT '想玩',
                rating      INTEGER DEFAULT 0,
                play_time   INTEGER DEFAULT 0,
                cover_path  TEXT DEFAULT '',
                notes       TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS screenshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id     INTEGER NOT NULL,
                file_path   TEXT NOT NULL,
                category    TEXT DEFAULT '其他',
                upload_time TEXT DEFAULT '',
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ss_game ON screenshots(game_id)")
        # 迁移：为老数据库补充分数维度 / 短评字段
        cols = {row[1] for row in cur.execute("PRAGMA table_info(games)").fetchall()}
        for cname, cdef in (
            ("score_story", "REAL DEFAULT 0"),
            ("score_char", "REAL DEFAULT 0"),
            ("score_audio", "REAL DEFAULT 0"),
            ("review", "TEXT DEFAULT ''"),
            # 字段扩展：资料展示页需要的新字段（老库自动补列，已有数据不受影响）
            ("favorite", "INTEGER DEFAULT 0"),      # 收藏
            ("publisher", "TEXT DEFAULT ''"),       # 发行商
            ("genres", "TEXT DEFAULT ''"),          # 类型（逗号分隔）
            ("tags", "TEXT DEFAULT ''"),            # 标签（逗号分隔）
            ("summary", "TEXT DEFAULT ''"),         # 简介
            ("characters", "TEXT DEFAULT ''"),      # 角色
            ("voice_actors", "TEXT DEFAULT ''"),    # 声优
            ("staff", "TEXT DEFAULT ''"),           # 制作人员
        ):
            if cname not in cols:
                cur.execute("ALTER TABLE games ADD COLUMN %s %s" % (cname, cdef))
        self.conn.commit()

    # ---------- 游戏 ----------
    def add_game(self, data: dict) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO games(title, title_jp, developer, release_date,
               status, rating, play_time, cover_path, notes,
               score_story, score_char, score_audio, review,
               favorite, publisher, genres, tags, summary, characters,
               voice_actors, staff)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get("title", ""), data.get("title_jp", ""),
             data.get("developer", ""), data.get("release_date", ""),
             data.get("status", "想玩"), float(data.get("rating", 0) or 0),
             int(data.get("play_time", 0) or 0), data.get("cover_path", ""),
             data.get("notes", ""),
             float(data.get("score_story", 0) or 0),
             float(data.get("score_char", 0) or 0),
             float(data.get("score_audio", 0) or 0),
             data.get("review", ""),
             int(data.get("favorite", 0) or 0), data.get("publisher", ""),
             data.get("genres", ""), data.get("tags", ""),
             data.get("summary", ""), data.get("characters", ""),
             data.get("voice_actors", ""), data.get("staff", ""))
        )
        self.conn.commit()
        return cur.lastrowid

    def update_game(self, game_id: int, data: dict):
        cur = self.conn.cursor()
        cur.execute(
            """UPDATE games SET title=?, title_jp=?, developer=?,
               release_date=?, status=?, rating=?, play_time=?, cover_path=?,
               notes=?, score_story=?, score_char=?, score_audio=?, review=?,
               favorite=?, publisher=?, genres=?, tags=?, summary=?,
               characters=?, voice_actors=?, staff=?
               WHERE id=?""",
            (data.get("title", ""), data.get("title_jp", ""),
             data.get("developer", ""), data.get("release_date", ""),
             data.get("status", "想玩"), float(data.get("rating", 0) or 0),
             int(data.get("play_time", 0) or 0), data.get("cover_path", ""),
             data.get("notes", ""),
             float(data.get("score_story", 0) or 0),
             float(data.get("score_char", 0) or 0),
             float(data.get("score_audio", 0) or 0),
             data.get("review", ""),
             int(data.get("favorite", 0) or 0), data.get("publisher", ""),
             data.get("genres", ""), data.get("tags", ""),
             data.get("summary", ""), data.get("characters", ""),
             data.get("voice_actors", ""), data.get("staff", ""),
             game_id)
        )
        self.conn.commit()

    def update_cover(self, game_id: int, cover_path: str):
        cur = self.conn.cursor()
        cur.execute("UPDATE games SET cover_path=? WHERE id=?", (cover_path, game_id))
        self.conn.commit()

    def count_cover_refs(self, cover_path: str) -> int:
        """统计还有多少款游戏引用这个封面路径。"""
        if not cover_path:
            return 0
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM games WHERE cover_path=?", (cover_path,))
        return int(cur.fetchone()[0] or 0)

    def set_favorite(self, game_id: int, value) -> None:
        """切换收藏标记（0/1）。只改这一个字段，不影响其它数据。"""
        cur = self.conn.cursor()
        cur.execute("UPDATE games SET favorite=? WHERE id=?",
                    (1 if value else 0, game_id))
        self.conn.commit()

    def update_scores(self, game_id: int, score_story, score_char, score_audio,
                      review: str, total_rating):
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE games SET score_story=?, score_char=?, score_audio=?, review=?, "
            "rating=? WHERE id=?",
            (score_story, score_char, score_audio, review, total_rating, game_id))
        self.conn.commit()

    def delete_game(self, game_id: int):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM games WHERE id=?", (game_id,))
        self.conn.commit()

    def get_game(self, game_id: int) -> dict:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM games WHERE id=?", (game_id,))
        row = cur.fetchone()
        if not row:
            return {}
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    @staticmethod
    def _like_escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _build_filter(self, status, keyword, developer=None,
                      genres=None, tags=None, favorite_only=False):
        clauses, params = [], []
        if status:
            clauses.append("status=?")
            params.append(status)
        if keyword:
            # 统一搜索：一条 OR 查询同时匹配 游戏名 / 原名 / 制作组 / 发行商 / 类型 / 标签
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR title_jp LIKE ? ESCAPE '\\'"
                " OR developer LIKE ? ESCAPE '\\' OR publisher LIKE ? ESCAPE '\\'"
                " OR genres LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')")
            k = "%" + self._like_escape(keyword) + "%"
            params.extend([k] * 6)
        if developer:
            # 按制作组（开发商）筛选：输入词条即时过滤
            clauses.append("(developer LIKE ? ESCAPE '\\' OR publisher LIKE ? ESCAPE '\\')")
            d = "%" + self._like_escape(developer) + "%"
            params.extend([d, d])
        if genres:
            clauses.append("genres LIKE ? ESCAPE '\\'")
            params.append("%" + self._like_escape(genres) + "%")
        if tags:
            clauses.append("tags LIKE ? ESCAPE '\\'")
            params.append("%" + self._like_escape(tags) + "%")
        if favorite_only:
            clauses.append("favorite=1")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def count_games(self, status=None, keyword=None, developer=None,
                    genres=None, tags=None, favorite_only=False) -> int:
        where, params = self._build_filter(status, keyword, developer,
                                           genres, tags, favorite_only)
        cur = self.conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM games {where}", params)
        return cur.fetchone()[0]

    def get_games_page(self, offset: int, limit: int, status=None, keyword=None,
                       developer=None, genres=None, tags=None,
                       favorite_only=False) -> list:
        where, params = self._build_filter(status, keyword, developer,
                                           genres, tags, favorite_only)
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT * FROM games {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ---------- 截图 ----------
    def add_screenshot(self, game_id: int, rel_path: str, category: str, upload_time: str) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO screenshots(game_id, file_path, category, upload_time) VALUES(?,?,?,?)",
            (game_id, rel_path, category, upload_time)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_screenshots(self, game_id: int, category=None) -> list:
        cur = self.conn.cursor()
        if category:
            cur.execute(
                "SELECT * FROM screenshots WHERE game_id=? AND category=? ORDER BY id DESC",
                (game_id, category)
            )
        else:
            cur.execute(
                "SELECT * FROM screenshots WHERE game_id=? ORDER BY id DESC",
                (game_id,)
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def delete_screenshot(self, ss_id: int):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM screenshots WHERE id=?", (ss_id,))
        self.conn.commit()

    # ---------- 本地 CG 归类辅助 ----------
    def get_all_games(self) -> list:
        """全部游戏（id/title/title_jp），供本地 CG 按游戏名归类使用。"""
        cur = self.conn.cursor()
        cur.execute("SELECT id, title, title_jp FROM games ORDER BY id")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_all_screenshots(self) -> list:
        """全部截图记录（id/game_id/file_path），用于把历史图片推断回游戏。"""
        cur = self.conn.cursor()
        cur.execute("SELECT id, game_id, file_path FROM screenshots ORDER BY id")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def update_screenshot_paths(self, mapping: dict) -> int:
        """按 {旧路径: 新路径} 批量更新截图记录，返回更新的行数。

        整理本地 CG 目录后调用，保证详情页的缩略图还能找到文件。
        """
        if not mapping:
            return 0
        cur = self.conn.cursor()
        changed = 0
        for old, new in mapping.items():
            if not old or not new or old == new:
                continue
            cur.execute("UPDATE screenshots SET file_path=? WHERE file_path=?",
                        (new, old))
            changed += cur.rowcount or 0
        self.conn.commit()
        return changed

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
