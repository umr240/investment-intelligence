"""
SQLite-backed TTL cache for API responses.
Single file (.ii_cache.db) — no external Redis dependency.
TTLs: financial statements 24h, price data 1h, insider/analyst 6h.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class CacheManager:
    def __init__(
        self,
        db_path: str = ".ii_cache.db",
        default_ttl: int = 86_400,
    ) -> None:
        self._db = Path(db_path)
        self._default_ttl = default_ttl
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key       TEXT PRIMARY KEY,
                    value     TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)")

    def get(self, key: str) -> Any | None:
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if time.time() > expires_at:
            self._delete(key)
            return None
        return json.loads(value)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = time.time() + (ttl if ttl is not None else self._default_ttl)
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, default=str), expires_at),
            )

    def _delete(self, key: str) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def invalidate_ticker(self, ticker: str) -> int:
        """Remove all cached entries for a given ticker."""
        ticker_upper = ticker.upper()
        with sqlite3.connect(self._db) as conn:
            result = conn.execute(
                "DELETE FROM cache WHERE key LIKE ?",
                (f"%:{ticker_upper}%",),
            )
            return result.rowcount

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Call periodically (e.g. on scheduler tick)."""
        with sqlite3.connect(self._db) as conn:
            result = conn.execute(
                "DELETE FROM cache WHERE expires_at < ?", (time.time(),)
            )
            return result.rowcount

    def stats(self) -> dict[str, int]:
        with sqlite3.connect(self._db) as conn:
            total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            expired = conn.execute(
                "SELECT COUNT(*) FROM cache WHERE expires_at < ?", (time.time(),)
            ).fetchone()[0]
        return {"total": total, "expired": expired, "live": total - expired}
