"""Lightweight SQLite-backed tool response and query cache for e2-micro."""
from contextlib import closing
import hashlib
import json
import sqlite3
import time


class ToolCache:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with closing(self._connect()) as db:
            db.execute('PRAGMA journal_mode = WAL')
            db.execute('PRAGMA synchronous = NORMAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tool_cache (
                    cache_key TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    result TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tool_cache_exp ON tool_cache(expires_at);
            ''')

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.execute('PRAGMA busy_timeout = 5000')
        return conn

    @staticmethod
    def _make_key(tool_name: str, args: dict, target_sha: str = '') -> str:
        canonical_args = json.dumps(args, sort_keys=True, ensure_ascii=False)
        blob = f'{tool_name}:{canonical_args}:{target_sha}'.encode('utf-8')
        return hashlib.sha256(blob).hexdigest()

    def get(self, tool_name: str, args: dict, target_sha: str = '') -> str | None:
        key = self._make_key(tool_name, args, target_sha)
        now = int(time.time())
        with closing(self._connect()) as db:
            row = db.execute('SELECT result FROM tool_cache WHERE cache_key=? AND expires_at>?', (key, now)).fetchone()
            return row[0] if row else None

    def put(self, tool_name: str, args: dict, result: str, ttl_seconds: int = 3600, target_sha: str = '') -> None:
        key = self._make_key(tool_name, args, target_sha)
        now = int(time.time())
        expires = now + max(60, ttl_seconds)
        with closing(self._connect()) as db:
            db.execute('''
                INSERT INTO tool_cache(cache_key, tool_name, result, created_at, expires_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET result=excluded.result, expires_at=excluded.expires_at
            ''', (key, tool_name, result, now, expires))

    def clear_expired(self) -> int:
        now = int(time.time())
        with closing(self._connect()) as db:
            cur = db.execute('DELETE FROM tool_cache WHERE expires_at<=?', (now,))
            return cur.rowcount
