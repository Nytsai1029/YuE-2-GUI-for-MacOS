"""SQLite persistence (WAL, one connection guarded by a lock) with forward-only migrations.

Everything the user makes is immutable once written: drafts, plans and candidates are
never edited in place; edits create new rows with a parent pointer.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import DEFAULT_SETTINGS, deep_merge

MIGRATIONS = [
    """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE songs (id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL, updated REAL,
        archived INTEGER DEFAULT 0, cover_seed INTEGER, meta TEXT DEFAULT '{}');
    CREATE TABLE drafts (id TEXT PRIMARY KEY, song_id TEXT NOT NULL REFERENCES songs(id), created REAL,
        lyrics TEXT, style_fields TEXT, style TEXT, sung TEXT, mapping TEXT, lint TEXT, bpm REAL,
        vocal_bpm REAL, language TEXT, gender TEXT);
    CREATE TABLE takes (id TEXT PRIMARY KEY, song_id TEXT NOT NULL, draft_id TEXT NOT NULL, created REAL,
        preset TEXT, options TEXT, status TEXT, stage TEXT, progress TEXT DEFAULT '{}', chosen_plan TEXT,
        chosen_candidate TEXT, error TEXT, finished REAL, summary TEXT DEFAULT '{}');
    CREATE TABLE plans (id TEXT PRIMARY KEY, take_id TEXT NOT NULL, parent_id TEXT, idx INTEGER, source TEXT,
        seed INTEGER, abc TEXT, dir TEXT, truncated INTEGER, n_tokens INTEGER, analysis TEXT, score REAL,
        passed INTEGER, edit_ops TEXT DEFAULT '[]', created REAL);
    CREATE TABLE candidates (id TEXT PRIMARY KEY, take_id TEXT NOT NULL, plan_id TEXT NOT NULL, idx INTEGER,
        sem_seed INTEGER, noise_seed INTEGER, tokens_path TEXT, n_tokens INTEGER, truncated INTEGER,
        stage TEXT, gates TEXT DEFAULT '{}', metrics TEXT DEFAULT '{}', asr TEXT, score REAL,
        audio_audition TEXT, audio_final TEXT, audio_master TEXT, reject_reason TEXT, created REAL);
    CREATE TABLE jobs (id TEXT PRIMARY KEY, take_id TEXT, kind TEXT, state TEXT, stage TEXT,
        progress TEXT DEFAULT '{}', eta REAL, error TEXT, params TEXT DEFAULT '{}', created REAL, started REAL,
        finished REAL);
    CREATE TABLE feedback (id TEXT PRIMARY KEY, candidate_id TEXT, take_id TEXT, kind TEXT, data TEXT,
        created REAL);
    CREATE TABLE lexicon (term TEXT PRIMARY KEY, sung TEXT NOT NULL, lang TEXT, created REAL);
    CREATE INDEX idx_drafts_song ON drafts(song_id);
    CREATE INDEX idx_takes_song ON takes(song_id);
    CREATE INDEX idx_plans_take ON plans(take_id);
    CREATE INDEX idx_cands_take ON candidates(take_id);
    CREATE INDEX idx_jobs_state ON jobs(state);
    """,
]
JSON_COLUMNS = {"meta", "style_fields", "mapping", "lint", "options", "progress", "analysis", "edit_ops", "gates",
                "metrics", "asr", "params", "data", "summary", "error", "value"}


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_hex(6)


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    def _migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i, sql in enumerate(MIGRATIONS[version:], start=version):
            self.conn.executescript("BEGIN;" + sql + f"PRAGMA user_version={i + 1};COMMIT;")

    # ------------------------------------------------------------------ generic helpers
    @staticmethod
    def _encode(row: dict) -> dict:
        return {k: (json.dumps(v, ensure_ascii=False) if k in JSON_COLUMNS and v is not None else v)
                for k, v in row.items()}

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        for k in JSON_COLUMNS & out.keys():
            if isinstance(out[k], str):
                try:
                    out[k] = json.loads(out[k])
                except ValueError:
                    pass
        return out

    def insert(self, table: str, row: dict) -> dict:
        row = dict(row)
        row.setdefault("id", new_id())
        if "created" in self.columns(table):
            row.setdefault("created", time.time())
        enc = self._encode(row)
        cols = ",".join(enc)
        marks = ",".join("?" for _ in enc)
        with self.lock:
            self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(enc.values()))
        return row

    def update(self, table: str, id: str, **fields) -> None:
        if not fields:
            return
        enc = self._encode(fields)
        sets = ",".join(f"{k}=?" for k in enc)
        with self.lock:
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*enc.values(), id])

    def get(self, table: str, id: str) -> dict | None:
        with self.lock:
            return self._decode(self.conn.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone())

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [self._decode(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        with self.lock:
            return self._decode(self.conn.execute(sql, args).fetchone())

    def execute(self, sql: str, args: tuple = ()) -> None:
        with self.lock:
            self.conn.execute(sql, args)

    _cols: dict[str, set[str]] = {}

    def columns(self, table: str) -> set[str]:
        if table not in self._cols:
            with self.lock:
                self._cols[table] = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        return self._cols[table]

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict:
        stored = {r["key"]: r["value"] for r in self.all("SELECT key, value FROM settings")}
        return deep_merge(DEFAULT_SETTINGS, stored)

    def save_settings(self, update: dict[str, Any]) -> dict:
        current = self.settings()
        merged = deep_merge(current, update)
        with self.lock:
            for key, value in merged.items():
                self.conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET "
                                  "value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))
        return merged

    # ------------------------------------------------------------------ lexicon
    def lexicon(self) -> dict[str, str]:
        return {r["term"]: r["sung"] for r in self.all("SELECT term, sung FROM lexicon")}
