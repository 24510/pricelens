# -*- coding: utf-8 -*-
"""数据库访问层：初始化 + meta/settings + 商品 + 价格 + 自动刷新状态 + 导出。"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from const import DB_FILENAME, SCHEMA_VERSION
from db.schema import SCHEMA_SQL


def now_str() -> str:
    """统一时间戳格式：2026-09-25 21:17:08。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """单写者模式的 SQLite 封装。"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / DB_FILENAME
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    # ---------- 初始化 ----------

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            self._migrate()
            self._conn.commit()
            if self.get_meta("schema_version") != str(SCHEMA_VERSION):
                self.set_meta("schema_version", str(SCHEMA_VERSION))
            if self.get_meta("created_at") is None:
                self.set_meta("created_at", now_str())

    def _migrate(self) -> None:
        """只增不改：为旧库补齐后续新增的列。"""
        cols = {row["name"] for row in
                self._conn.execute("PRAGMA table_info(prices)").fetchall()}
        if "note" not in cols:
            self._conn.execute("ALTER TABLE prices ADD COLUMN note TEXT DEFAULT ''")
        # P3：自动刷新状态列（items 表）
        icols = {row["name"] for row in
                 self._conn.execute("PRAGMA table_info(items)").fetchall()}
        if "last_check_at" not in icols:
            self._conn.execute("ALTER TABLE items ADD COLUMN last_check_at TEXT")
        if "last_check_error" not in icols:
            self._conn.execute("ALTER TABLE items ADD COLUMN last_check_error TEXT")

    # ---------- meta / settings ----------

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self._conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self._conn.commit()

    # ---------- 商品 ----------

    def list_items(self) -> List[Dict[str, Any]]:
        """监控清单（含最近价 / 记录数），最近有变动的排前面。"""
        sql = (
            "SELECT i.*, "
            "(SELECT p.price FROM prices p WHERE p.item_fk = i.id "
            " ORDER BY p.captured_at DESC, p.id DESC LIMIT 1) AS last_price, "
            "(SELECT p.captured_at FROM prices p WHERE p.item_fk = i.id "
            " ORDER BY p.captured_at DESC, p.id DESC LIMIT 1) AS last_at, "
            "(SELECT COUNT(*) FROM prices p WHERE p.item_fk = i.id) AS price_count "
            "FROM items i WHERE i.status = 'active' "
            "ORDER BY COALESCE(i.last_sample_at, i.created_at) DESC, i.id DESC"
        )
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def get_item(self, item_pk: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM items WHERE id=?", (item_pk,)).fetchone()
        return dict(row) if row else None

    def find_item(self, platform: str, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM items WHERE platform=? AND item_id=?",
                (platform, item_id)).fetchone()
        return dict(row) if row else None

    def add_item(self, platform: str, item_id: str, title: str = "",
                 shop: str = "", url: str = "", note: str = "",
                 pic: str = "") -> Dict[str, Any]:
        """新增商品；若同平台同 ID 已存在，返回已有记录（不重复建）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM items WHERE platform=? AND item_id=?",
                (platform, item_id)).fetchone()
            if row:
                return {"created": False, "item": dict(row)}
            ts = now_str()
            cur = self._conn.execute(
                "INSERT INTO items(platform, item_id, title, shop, url, note, pic, "
                "status, first_seen, created_at) "
                "VALUES(?,?,?,?,?,?,?,'active',?,?)",
                (platform, item_id, title, shop, url, note, pic, ts, ts))
            self._conn.commit()
            new_id = cur.lastrowid
            row = self._conn.execute("SELECT * FROM items WHERE id=?", (new_id,)).fetchone()
        return {"created": True, "item": dict(row)}

    def update_item(self, item_pk: int, title: Optional[str] = None,
                    shop: Optional[str] = None, note: Optional[str] = None,
                    url: Optional[str] = None) -> bool:
        """定点更新商品字段（只改传入的项）。"""
        fields, values = [], []
        if title is not None:
            fields.append("title=?")
            values.append(str(title)[:200])
        if shop is not None:
            fields.append("shop=?")
            values.append(str(shop)[:100])
        if note is not None:
            fields.append("note=?")
            values.append(str(note)[:200])
        if url is not None:
            fields.append("url=?")
            values.append(str(url))
        if not fields:
            return True
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM items WHERE id=?", (int(item_pk),)).fetchone()
            if not row:
                return False
            values.append(int(item_pk))
            self._conn.execute(
                "UPDATE items SET " + ", ".join(fields) + " WHERE id=?", values)
            self._conn.commit()
        return True

    def delete_item(self, item_pk: int) -> Dict[str, Any]:
        """删除商品及其全部价格记录。"""
        with self._lock:
            n = self._conn.execute(
                "SELECT COUNT(*) c FROM prices WHERE item_fk=?", (item_pk,)).fetchone()["c"]
            self._conn.execute("DELETE FROM prices WHERE item_fk=?", (item_pk,))
            cur = self._conn.execute("DELETE FROM items WHERE id=?", (item_pk,))
            self._conn.commit()
        return {"deleted": bool(cur.rowcount), "deleted_prices": n}

    # ---------- 价格 ----------

    def list_prices(self, item_pk: int, limit: int = 500) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, item_fk, captured_at, price, list_price, coupon, note, source "
                "FROM prices WHERE item_fk=? "
                "ORDER BY captured_at DESC, id DESC LIMIT ?",
                (item_pk, int(limit))).fetchall()
        return [dict(r) for r in rows]

    def add_price(self, item_pk: int, price: float, captured_at: str = "",
                  source: str = "manual", note: str = "",
                  list_price: Optional[float] = None,
                  coupon: Optional[float] = None) -> int:
        ts = (captured_at or "").strip() or now_str()

        def _num(v):
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO prices(item_fk, captured_at, price, list_price, coupon, source, note) "
                "VALUES(?,?,?,?,?,?,?)",
                (item_pk, ts, float(price), _num(list_price), _num(coupon), source, note))
            self._conn.execute("UPDATE items SET last_sample_at=? WHERE id=?", (ts, item_pk))
            self._conn.commit()
        return int(cur.lastrowid)

    def delete_price(self, price_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, item_fk FROM prices WHERE id=?", (price_id,)).fetchone()
            if not row:
                return None
            self._conn.execute("DELETE FROM prices WHERE id=?", (price_id,))
            self._conn.commit()
        return {"id": row["id"], "item_fk": row["item_fk"]}

    def item_stats(self, item_pk: int) -> Dict[str, Any]:
        """单商品统计：最低 / 最高 / 平均 / 最近 / 条数。"""
        with self._lock:
            agg = self._conn.execute(
                "SELECT COUNT(*) AS cnt, MIN(price) AS mn, MAX(price) AS mx, AVG(price) AS av "
                "FROM prices WHERE item_fk=?", (item_pk,)).fetchone()
            last = self._conn.execute(
                "SELECT price, captured_at FROM prices WHERE item_fk=? "
                "ORDER BY captured_at DESC, id DESC LIMIT 1", (item_pk,)).fetchone()
        return {
            "count": agg["cnt"] or 0,
            "min": agg["mn"],
            "max": agg["mx"],
            "avg": (round(agg["av"], 2) if agg["av"] is not None else None),
            "last": last["price"] if last else None,
            "last_at": last["captured_at"] if last else None,
        }

    # ---------- 自动刷新（P3） ----------

    def latest_price(self, item_pk: int) -> Optional[Dict[str, Any]]:
        """最近一条价格（供自动刷新比对用）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT price, captured_at FROM prices WHERE item_fk=? "
                "ORDER BY captured_at DESC, id DESC LIMIT 1", (item_pk,)).fetchone()
        return dict(row) if row else None

    def latest_change_at(self) -> Optional[str]:
        """最近一次「价格变化」的时间（价格只在变化时入库，故取最大值）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(captured_at) AS t FROM prices").fetchone()
        return row["t"] if row and row["t"] else None

    def touch_check(self, item_pk: int, at: str, error: str = "") -> None:
        """更新商品的「最后检查」状态（不产生价格记录）。"""
        with self._lock:
            self._conn.execute(
                "UPDATE items SET last_check_at=?, last_check_error=? WHERE id=?",
                (at, str(error or "")[:200], int(item_pk)))
            self._conn.commit()

    def log_refresh_run(self, trigger: str, started_at: str, finished_at: str,
                        total: int, ok: int, changed: int, new_low: int,
                        failed: int, message: str = "") -> int:
        """记录一轮自动刷新（refresh_runs 表）。"""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO refresh_runs(trigger, started_at, finished_at, total, ok, "
                "changed, new_low, failed, message) VALUES(?,?,?,?,?,?,?,?,?)",
                (trigger, started_at, finished_at, int(total), int(ok), int(changed),
                 int(new_low), int(failed), str(message or "")[:300]))
            self._conn.commit()
        return int(cur.lastrowid)

    def recent_refresh_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM refresh_runs ORDER BY id DESC LIMIT ?",
                (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 导出 ----------

    def export_rows(self) -> List[Dict[str, Any]]:
        """导出用：全部价格记录（连带商品信息），按商品、时间排序。"""
        sql = (
            "SELECT i.platform, i.title, i.shop, i.item_id, i.url, "
            "p.captured_at, p.price, p.note, p.source "
            "FROM prices p JOIN items i ON i.id = p.item_fk "
            "ORDER BY i.id, p.captured_at, p.id"
        )
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    # ---------- 统计（界面顶部卡片） ----------

    def stats(self) -> Dict[str, int]:
        with self._lock:
            items = self._conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
            prices = self._conn.execute("SELECT COUNT(*) c FROM prices").fetchone()["c"]
        return {"items": items, "prices": prices}

    def recent_prices(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT p.captured_at, p.price, p.source, i.title, i.platform "
                "FROM prices p LEFT JOIN items i ON i.id = p.item_fk "
                "ORDER BY p.captured_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 生命周期 ----------

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.commit()
                self._conn.close()
        except Exception:
            pass