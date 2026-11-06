import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from miniagent.journal import (
    get_day_bounds_utc,
    get_week_bounds_utc,
    collect_recent_learnings,
    generate_daily_journal,
    generate_weekly_recap
)
from miniagent.queue import Queue


class TestJournal(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.db_path = str(self.workspace / 'test.db')
        self.queue = Queue(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_day_and_week_bounds(self):
        start_ts, end_ts, d_str = get_day_bounds_utc('2026-11-06')
        self.assertEqual(d_str, '2026-11-06')
        self.assertLess(start_ts, end_ts)
        self.assertEqual(end_ts - start_ts, 86399)

        w_start, w_end, w_str = get_week_bounds_utc('2026-W45')
        self.assertEqual(w_str, '2026-W45')
        self.assertLess(w_start, w_end)

    def test_generate_daily_journal(self):
        # Insert a job and finish it to record history
        ident = self.queue.ingest(101, 'Autonomous security scan')
        self.queue.claim()
        self.queue.finish(ident, 'Completed without vulnerabilities', failed=False,
                          duration_ms=450, tool_calls_count=3, cost_microdollars=1200)

        # Add a learning note
        k_dir = self.workspace / 'knowledge'
        k_dir.mkdir(parents=True)
        note_data = {
            'topic': 'FTS5 Indexing',
            'lesson': 'Use prefix matching for sub-word token retrieval in SQLite.',
            'sources': ['https://sqlite.org']
        }
        (k_dir / 'note1.json').write_text(json.dumps(note_data), encoding='utf-8')

        res = generate_daily_journal(self.queue, workspace_root=self.workspace)
        self.assertTrue(res['path'].startswith('updates/daily/'))
        self.assertEqual(len(res['sha256']), 64)
        self.assertGreater(res['total_jobs'], 0)

        out_file = self.workspace / res['path']
        self.assertTrue(out_file.is_file())
        content = out_file.read_text(encoding='utf-8')
        self.assertIn('# MiniAgent Daily Log', content)
        self.assertIn('Total Tasks Executed', content)
        self.assertIn('FTS5 Indexing', content)
        self.assertIn('e2-micro', content)

    def test_generate_weekly_recap(self):
        ident = self.queue.ingest(202, 'Weekly performance audit')
        self.queue.claim()
        self.queue.finish(ident, 'Audit passed with 100% test pass rate', failed=False,
                          duration_ms=800, tool_calls_count=5, cost_microdollars=2500)

        res = generate_weekly_recap(self.queue, workspace_root=self.workspace)
        self.assertTrue(res['path'].startswith('updates/weekly/'))
        self.assertEqual(len(res['sha256']), 64)

        out_file = self.workspace / res['path']
        self.assertTrue(out_file.is_file())
        content = out_file.read_text(encoding='utf-8')
        self.assertIn('# MiniAgent Weekly Recap', content)
        self.assertIn('RustyDrops/miniAgent-e2-micro', content)
        self.assertIn('Weekly Budget Limit', content)

    def test_seed_journal_seeds_daily_and_weekly_objectives(self):
        self.queue.seed_journal()
        self.queue.seed_journal()
        objs = self.queue.objectives()
        self.assertEqual(len(objs), 2)
        intervals = {o[2] for o in objs}
        self.assertEqual(intervals, {86400, 7 * 86400})


if __name__ == '__main__':
    unittest.main()
