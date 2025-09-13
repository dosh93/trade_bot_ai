from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ActionRecord:
    key: str
    status: str
    details: Optional[str]
    created_at: float


class State:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self):
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
                key TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                details TEXT,
                created_at REAL NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL
            );
            """
        )
        self._conn.commit()

    def has_action(self, key: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("SELECT 1 FROM actions WHERE key=?", (key,))
        row = cur.fetchone()
        return row is not None

    def record_action(self, key: str, status: str, details: Optional[str] = None):
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO actions(key, status, details, created_at) VALUES (?, ?, ?, ?)",
            (key, status, details, now),
        )
        self._conn.commit()

    def record_order_attempt(self):
        now = time.time()
        self._conn.execute("INSERT INTO orders_log(ts) VALUES (?)", (now,))
        self._conn.commit()

    def orders_last_hour(self) -> int:
        since = time.time() - 3600
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) c FROM orders_log WHERE ts >= ?", (since,))
        return int(cur.fetchone()[0])

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


