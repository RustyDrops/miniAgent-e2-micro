"""Tests for the embedded SQLite WAL persistent memory layer."""

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

            # synchronous: 1 is NORMAL
            synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
            self.assertEqual(synchronous, 1)

            # Verify row_factory is sqlite3.Row
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


if __name__ == "__main__":
    unittest.main()
