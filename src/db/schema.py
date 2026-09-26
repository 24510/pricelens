# -*- coding: utf-8 -*-
"""数据库表结构（P0 冻结，后续里程碑只增不改）。"""

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    keyword    TEXT DEFAULT '',
    is_focus   INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL,
    item_id          TEXT NOT NULL,
    group_fk         INTEGER,
    role             TEXT DEFAULT 'member',
    match_state      TEXT DEFAULT 'confirmed',
    match_conf       INTEGER DEFAULT 100,
    title            TEXT DEFAULT '',
    shop             TEXT DEFAULT '',
    url              TEXT DEFAULT '',
    pic              TEXT DEFAULT '',
    note             TEXT DEFAULT '',
    status           TEXT DEFAULT 'active',
    auto_refreshable INTEGER DEFAULT 0,
    first_seen       TEXT,
    last_sample_at   TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(platform, item_id)
);
CREATE INDEX IF NOT EXISTS ix_items_group ON items(group_fk);

CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_fk     INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    price       REAL NOT NULL,
    list_price  REAL,
    coupon      REAL,
    note        TEXT DEFAULT '',
    source      TEXT DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS ix_prices_item_time ON prices(item_fk, captured_at);

CREATE TABLE IF NOT EXISTS match_candidates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_fk   INTEGER NOT NULL,
    platform   TEXT,
    item_id    TEXT,
    title      TEXT,
    shop       TEXT,
    url        TEXT,
    score      INTEGER,
    reason     TEXT,
    verdict    TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS refresh_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger     TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    total       INTEGER DEFAULT 0,
    ok          INTEGER DEFAULT 0,
    changed     INTEGER DEFAULT 0,
    new_low     INTEGER DEFAULT 0,
    failed      INTEGER DEFAULT 0,
    message     TEXT DEFAULT ''
);
"""