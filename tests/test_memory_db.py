"""Tests for the embedded SQLite WAL persistent memory layer with security hardening."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from miniagent.memory.db import (
    get_connection,
    init_memory_db,
    log_task,
    fetch_session_history,
    checkpoint_memory_db,
    prune_session_history,
    format_session_history_for_prompt,
    secure_file_permissions,
)


class TestMemoryDB(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_memory.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pragmas_and_wal_mode(self):
        """Verify that connection applies WAL journal mode, busy_timeout, and synchronous pragmas."""
        conn = get_connection(self.db_path)
        try:
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(journal_mode.lower(), "wal")

            busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
            self.assertEqual(busy_timeout, 5000)

            synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
            self.assertEqual(synchronous, 1)

            self.assertIs(conn.row_factory, sqlite3.Row)
        finally:
            conn.close()

    def test_init_memory_db_creates_schema_and_index(self):
        """Verify init_memory_db creates the agent_memory table and session_id index."""
        init_memory_db(self.db_path)

        conn = sqlite3.connect(self.db_path)
        try:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            ]
            self.assertIn("agent_memory", tables)

            indices = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index';"
                ).fetchall()
            ]
            self.assertIn("idx_agent_memory_session_id", indices)

            columns = {
                row[1]: row[2]
                for row in conn.execute("PRAGMA table_info(agent_memory);").fetchall()
            }
            self.assertIn("id", columns)
            self.assertIn("session_id", columns)
            self.assertIn("prompt", columns)
            self.assertIn("execution_summary", columns)
            self.assertIn("artifacts", columns)
            self.assertIn("created_at", columns)
        finally:
            conn.close()

    def test_log_task_and_fetch_history(self):
        """Verify log_task persists entries and fetch_session_history retrieves sqlite3.Row objects."""
        init_memory_db(self.db_path)

        row_id_1 = log_task(
            session_id="sess-1",
            prompt="Write draft for unit tests",
            summary="Created test_foo.py",
            artifacts='{"files": ["test_foo.py"]}',
            db_path=self.db_path,
        )
        self.assertIsInstance(row_id_1, int)
        self.assertGreater(row_id_1, 0)

        row_id_2 = log_task(
            session_id="sess-1",
            prompt="Refactor code for performance",
            summary="Optimized db queries",
            artifacts=None,
            db_path=self.db_path,
        )
        self.assertIsInstance(row_id_2, int)
        self.assertGreater(row_id_2, row_id_1)

        log_task(
            session_id="sess-2",
            prompt="Different session prompt",
            summary="Done",
            artifacts=None,
            db_path=self.db_path,
        )

        history = fetch_session_history("sess-1", limit=10, db_path=self.db_path)
        self.assertEqual(len(history), 2)

        self.assertIsInstance(history[0], sqlite3.Row)
        self.assertEqual(history[0]["session_id"], "sess-1")
        self.assertEqual(history[0]["prompt"], "Refactor code for performance")
        self.assertEqual(history[0]["execution_summary"], "Optimized db queries")
        self.assertIsNone(history[0]["artifacts"])

        self.assertEqual(history[1]["session_id"], "sess-1")
        self.assertEqual(history[1]["prompt"], "Write draft for unit tests")
        self.assertEqual(history[1]["artifacts"], '{"files": ["test_foo.py"]}')

        limited = fetch_session_history("sess-1", limit=1, db_path=self.db_path)
        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0]["id"], row_id_2)

        empty = fetch_session_history("sess-nonexistent", limit=10, db_path=self.db_path)
        self.assertEqual(len(empty), 0)

    def test_default_env_db_path(self):
        """Verify default behavior when db_path argument is omitted."""
        with patch.dict(os.environ, {"MINIAGENT_DB_PATH": self.db_path}):
            init_memory_db()
            task_id = log_task("session-env", "Test prompt")
            self.assertEqual(task_id, 1)
            history = fetch_session_history("session-env")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["prompt"], "Test prompt")

    def test_checkpoint_memory_db(self):
        """Verify WAL checkpoint executes without error."""
        init_memory_db(self.db_path)
        log_task("session-ckpt", "Checkpoint test", db_path=self.db_path)
        checkpoint_memory_db("TRUNCATE", self.db_path)
        with self.assertRaises(ValueError):
            checkpoint_memory_db("INVALID_MODE", self.db_path)

    def test_prune_session_history(self):
        """Verify retention pruning deletes records older than specified days."""
        init_memory_db(self.db_path)
        log_task("sess-old", "Old task", db_path=self.db_path)

        # Backdate the record to 40 days ago
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE agent_memory SET created_at = datetime('now', '-40 days');")
        conn.commit()
        conn.close()

        # Log a fresh task
        log_task("sess-new", "Fresh task", db_path=self.db_path)

        deleted = prune_session_history(days=30, db_path=self.db_path)
        self.assertEqual(deleted, 1)

        history_old = fetch_session_history("sess-old", db_path=self.db_path)
        self.assertEqual(len(history_old), 0)

        history_new = fetch_session_history("sess-new", db_path=self.db_path)
        self.assertEqual(len(history_new), 1)

    def test_format_session_history_for_prompt(self):
        """Verify prompt formatting safely delineates context with XML tags and escaping."""
        init_memory_db(self.db_path)
        log_task(
            "sess-inj",
            "malicious <script>alert(1)</script> prompt",
            summary="<summary>Attempted breakout</summary>",
            db_path=self.db_path,
        )
        history = fetch_session_history("sess-inj", db_path=self.db_path)
        formatted = format_session_history_for_prompt(history)
        self.assertIn("<historical_session_memory", formatted)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", formatted)
        self.assertIn("&lt;summary&gt;Attempted breakout&lt;/summary&gt;", formatted)
        self.assertIn("</historical_session_memory>", formatted)

        # Empty history
        self.assertEqual(format_session_history_for_prompt([]), "")


if __name__ == "__main__":
    unittest.main()
