import os
import tempfile
import unittest

from miniagent.queue import Queue
from miniagent.postmortem import generate_postmortem_report


class PostmortemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getcwd())
        self.db_path = os.path.join(self.tmp.name, 'test.db')
        self.queue = Queue(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_postmortem_empty_and_populated_reports(self):
        # Empty
        rep_empty = generate_postmortem_report(self.queue)
        self.assertIn('No task history recorded yet', rep_empty)

        # Ingest and finish a successful job
        j1 = self.queue.ingest(1, 'Task one')
        self.queue.claim()
        self.queue.finish(j1, 'done ok', duration_ms=1000, tool_calls_count=2)

        # Ingest and fail a second job with BudgetExceeded
        j2 = self.queue.ingest(2, 'Task two')
        self.queue.claim()
        self.queue.finish(j2, 'budget hit', failed=True, error_type='BudgetExceeded', duration_ms=2500)

        rep = generate_postmortem_report(self.queue)
        self.assertIn('Success Rate', rep)
        self.assertIn('50.0%', rep)
        self.assertIn('BudgetExceeded', rep)
        self.assertIn('Budget Exhaustion', rep)
        self.assertIn('Recent Failed / Interrupted Tasks', rep)
        self.assertIn('Task two', rep)


if __name__ == '__main__':
    unittest.main()
