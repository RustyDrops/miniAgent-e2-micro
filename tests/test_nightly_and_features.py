from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from miniagent.queue import Queue
from miniagent.budget import Budget
from miniagent.housekeeping import run_nightly_consolidation
from miniagent.morning import generate_morning_briefing
from miniagent.badges import render_svg_badge, update_status_badges
from miniagent.release import prepare_milestone_release
from miniagent.github import GitHub


class NightlyAndFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.db_path = str(self.workspace / 'features.db')
        self.queue = Queue(self.db_path)
        self.budget = Budget(self.db_path, Decimal('1.00'))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_nightly_consolidation_executes_maintenance(self):
        # Insert a job and finish it
        jid = self.queue.ingest(10, 'Nightly scout task')
        self.queue.claim()
        self.queue.finish(jid, 'Finished without error', failed=False, duration_ms=200)

        # Seed learning note
        k_dir = self.workspace / 'knowledge'
        k_dir.mkdir(parents=True)
        (k_dir / 'note.json').write_text(json.dumps({'topic': 'WAL mode', 'lesson': 'Zero IOPS checkpoint'}), encoding='utf-8')

        with patch('miniagent.canary.run_canary_tests', return_value={'passed': True, 'total_canaries': 103}):
            rep = run_nightly_consolidation(db_path=self.db_path, workspace_root=self.workspace)
            self.assertTrue(rep['wal_truncated'])
            self.assertIn('router_audit', rep)
            self.assertTrue(rep['canary_passed'])
            self.assertEqual(rep['canary_tests_run'], 103)

    def test_morning_briefing_formats_card(self):
        jid = self.queue.ingest(20, 'Overnight routine')
        self.queue.claim()
        self.queue.finish(jid, 'Overnight routine done', failed=False, duration_ms=300)

        briefing = generate_morning_briefing(self.queue, budget=self.budget, workspace_root=self.workspace, hours=8)
        self.assertIn('MiniAgent Morning Briefing', briefing['text'])
        self.assertEqual(briefing['overnight_jobs'], 1)
        self.assertEqual(briefing['succeeded'], 1)
        self.assertIn('Health & Memory', briefing['text'])

    def test_svg_badges_generation(self):
        svg = render_svg_badge('status', 'passing', color='#97CA00')
        self.assertIn('<svg', svg)
        self.assertIn('status', svg)
        self.assertIn('passing', svg)

        res = update_status_badges(workspace_root=self.workspace, budget=self.budget, test_count=103)
        self.assertEqual(len(res['badges']), 3)
        badge_dir = self.workspace / res['dir']
        self.assertTrue((badge_dir / 'budget.svg').is_file())
        self.assertTrue((badge_dir / 'tests.svg').is_file())
        self.assertTrue((badge_dir / 'health.svg').is_file())

        budget_content = (badge_dir / 'budget.svg').read_text(encoding='utf-8')
        self.assertIn('budget', budget_content)

    def test_milestone_release_and_github_draft(self):
        jid = self.queue.ingest(30, 'Weekly milestone')
        self.queue.claim()
        self.queue.finish(jid, 'Milestone reached', failed=False, duration_ms=500)

        fake_gh = GitHub('owner/repo', 'fake_token')
        calls = []
        def req(method, path, payload=None):
            calls.append((method, path, payload))
            if path == '': return {'default_branch': 'main'}
            if path == '/releases': return {'html_url': 'https://github.com/owner/repo/releases/tag/v0.2.0'}
            return {}
        with patch.object(fake_gh, 'request', side_effect=req):
            res = prepare_milestone_release(self.queue, workspace_root=self.workspace, tag_name='v0.2.0', gh=fake_gh)
            self.assertEqual(res['tag'], 'v0.2.0')
            self.assertIn('MiniAgent Autonomous Milestone', res['body'])
            self.assertEqual(res['release_url'], 'https://github.com/owner/repo/releases/tag/v0.2.0')
            self.assertTrue(any(c[0] == 'POST' and c[1] == '/releases' for c in calls))


if __name__ == '__main__':
    unittest.main()
