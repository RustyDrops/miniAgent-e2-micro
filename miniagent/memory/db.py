"""Embedded SQLite persistent state using WAL mode for concurrent, low-overhead reads/writes."""

import os
import sqlite3
from typing import List, Optional


def get_db_path() -> str:
    """Return the database path configured in MINIAGENT_DB_PATH or default."""
    return os.environ.get("MINIAGENT_DB_PATH", "miniagent_memory.db")


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Connect to SQLite database and apply WAL mode and concurrency PRAGMAs."""
    path = db_path if db_path is not None else get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_memory_db(db_path: Optional[str] = None) -> None:
    """Initialize the agent_memory table and its indices."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    execution_summary TEXT,
                    artifacts TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_memory_session_id
                ON agent_memory (session_id);
                """
            )
    finally:
        conn.close()


def log_task(
    session_id: str,
    prompt: str,
    summary: Optional[str] = None,
    artifacts: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Log an agent task execution to persistent memory, returning the new record id."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_memory (session_id, prompt, execution_summary, artifacts)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, prompt, summary, artifacts),
            )
            return cursor.lastrowid
    finally:
        conn.close()


def fetch_session_history(
    session_id: str,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[sqlite3.Row]:
    """Fetch recent execution history for a session as sqlite3.Row objects."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT id, session_id, prompt, execution_summary, artifacts, created_at
            FROM agent_memory
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        return cursor.fetchall()
    finally:
        conn.close()
