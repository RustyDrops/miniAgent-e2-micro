"""Nightly memory consolidation, SQLite maintenance, and self-healing housekeeping."""
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import time

from .tools import ROOT


def run_nightly_consolidation(db_path=None, workspace_root=None):
    """Execute nightly housekeeping: WAL truncation, cache purge, knowledge grooming, router calibration, and canary checks."""
    db_p = db_path or os.environ.get('MINIAGENT_DB', 'miniagent.db')
    root = ROOT if workspace_root is None else Path(workspace_root)
    now = int(time.time())

    report = {
        'timestamp': now,
        'wal_truncated': False,
        'cache_purged': 0,
        'knowledge_groomed': 0,
        'router_audit': {},
        'canary_passed': False,
        'canary_tests_run': 0
    }

    # 1. SQLite WAL truncation and optimization
    try:
        with closing(sqlite3.connect(db_p, timeout=15)) as db:
            db.execute('PRAGMA busy_timeout = 5000')
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.execute('PRAGMA optimize')
            report['wal_truncated'] = True

            # 2. Tool cache cleanup of expired entries
            try:
                cur = db.execute('DELETE FROM tool_cache WHERE expires_at IS NOT NULL AND expires_at < ?', (now,))
                report['cache_purged'] = cur.rowcount
            except sqlite3.OperationalError:
                pass
    except Exception as exc:
        report['sqlite_error'] = type(exc).__name__

    # 3. Knowledge base deduplication
    try:
        from . import knowledge
        groom_res = knowledge.groom(root)
        report['knowledge_groomed'] = groom_res.get('removed', 0)
    except Exception as exc:
        report['knowledge_error'] = type(exc).__name__

    # 4. Naive Bayes task router calibration and noise pruning
    try:
        from .naive_bayes import NaiveBayesRouter
        router = NaiveBayesRouter(db_p)
        report['router_audit'] = router.daily_audit(hours=24)
    except Exception as exc:
        report['router_error'] = type(exc).__name__

    # 5. Canary test suite regression check
    try:
        from .canary import run_canary_tests
        canary_res = run_canary_tests()
        report['canary_passed'] = canary_res.get('passed', False)
        report['canary_tests_run'] = canary_res.get('total_canaries', 0)
    except Exception as exc:
        report['canary_error'] = type(exc).__name__

    return report
