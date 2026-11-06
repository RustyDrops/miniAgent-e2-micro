import os
import tempfile
import sqlite3
from contextlib import closing
import unittest
from unittest.mock import patch

from miniagent.queue import Queue
from miniagent.__main__ import job_tool_handler


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getcwd())
        self.queue = Queue(os.path.join(self.tmp.name, 'queue.db'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingestion_survives_restart_and_deduplicates_updates(self):
        ident = self.queue.ingest(42, 'a task')
        self.assertIsNotNone(ident)
        reloaded = Queue(self.queue.path)
        self.assertEqual(reloaded.offset(), 43)
        self.assertIsNone(reloaded.ingest(42, 'a task'))
        self.assertEqual(reloaded.claim(), (ident, 'a task'))
        self.assertIsNone(reloaded.claim())
        reloaded.recover()
        self.assertEqual(reloaded.pending_notifications()[0][:2], (ident, 'interrupted'))
        self.assertIsNone(reloaded.claim())

    def test_pause_and_schedule_skip_missed_intervals(self):
        with patch('miniagent.queue.time.time', return_value=1000):
            ident = self.queue.add_objective('Research improvements', 6)
        self.queue.pause(True)
        self.queue.schedule_due(now=100000)
        self.assertIsNone(self.queue.claim())
        self.queue.pause(False)
        self.queue.schedule_due(now=100000)
        self.queue.schedule_due(now=100000)
        job = self.queue.claim()
        self.assertEqual(job[1], 'Research improvements')
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.objectives()[0][3], 100000 + 6 * 3600)
        self.queue.finish(job[0], 'done')
        self.assertEqual(self.queue.pending_notifications()[0][2], 'done')
        self.queue.mark_notified(job[0])
        self.assertEqual(self.queue.pending_notifications(), [])
        self.assertTrue(self.queue.remove_objective(ident))

    def test_limits_queue_and_objectives(self):
        for n in range(20):
            self.assertIsNotNone(self.queue.ingest(n, 'task'))
        self.assertIsNone(self.queue.ingest(20, 'overflow'))
        self.assertEqual(self.queue.offset(), 21)
        with self.assertRaises(ValueError):
            self.queue.add_objective('too frequent', 1)
        for _ in range(5):
            self.queue.add_objective('task', 6)
        with self.assertRaises(ValueError):
            self.queue.add_objective('too many', 6)

    def test_default_learning_is_seeded_once_and_can_be_removed(self):
        with patch('miniagent.queue.time.time', return_value=1000):
            self.queue.seed_learning()
            self.queue.seed_learning()
        objectives = self.queue.objectives()
        self.assertEqual(len(objectives), 1)
        self.assertEqual(objectives[0][2:], (86400, 87400))
        self.assertTrue(self.queue.remove_objective(objectives[0][0]))
        self.queue.seed_learning()
        self.assertEqual(self.queue.objectives(), [])

    def test_followups_are_staged_bounded_and_cannot_recurse(self):
        with patch('miniagent.queue.time.time', return_value=1000):
            for n in range(3): self.queue.add_objective('research ' + str(n), 6)
            self.queue.schedule_due(now=23000)
            first = self.queue.claim()
            child = self.queue.propose_followup(first[0], 'Investigate a testable idea')
            with self.assertRaises(ValueError): self.queue.propose_followup(first[0], 'duplicate')
            self.queue.finish(first[0], 'done')
            second = self.queue.claim()
            self.queue.propose_followup(second[0], 'Try a second idea')
            self.queue.finish(second[0], 'done', failed=True)
            third = self.queue.claim()
            with self.assertRaises(ValueError): self.queue.propose_followup(third[0], 'over daily quota')
            self.queue.finish(third[0], 'done')
            claimed = self.queue.claim()
            self.assertEqual(claimed[0], child)
            with self.assertRaises(ValueError): self.queue.propose_followup(child, 'cannot recurse')
            self.assertEqual(self.queue.counts()['cancelled'], 1)

    def test_background_budget_and_user_priority(self):
        class Budget:
            def today(self): return 750, 1000
        with patch('miniagent.queue.time.time', return_value=1000):
            self.queue.add_objective('background', 6)
            self.queue.schedule_due(now=23000)
            user = self.queue.ingest(1, 'user request')
            self.assertEqual(self.queue.claim(allow_background=False)[0], user)
            self.queue.finish(user, 'done')
            self.assertIsNone(self.queue.claim(allow_background=False))
            job = self.queue.claim()
            result = job_tool_handler(self.queue, Budget(), job[0])('propose_followup', {'task': 'follow up'})
            self.assertIn('threshold', result)
            self.assertNotIn('proposed', self.queue.counts())

    def test_tool_handler_stages_followup_until_success(self):
        class Budget:
            def today(self): return 100, 1000
        with patch('miniagent.queue.time.time', return_value=1000):
            self.queue.add_objective('research', 6)
            self.queue.schedule_due(now=23000)
            parent = self.queue.claim()
            dispatch = job_tool_handler(self.queue, Budget(), parent[0])
            result = dispatch('propose_followup', {'task': 'Evaluate the proposed idea'})
            self.assertIn('proposed', result)
            self.assertIsNone(self.queue.claim())
            self.queue.finish(parent[0], 'completed')
            self.assertEqual(self.queue.claim()[1], 'Evaluate the proposed idea')

    def test_restart_cancels_unfinished_proposals(self):
        with patch('miniagent.queue.time.time', return_value=1000):
            self.queue.add_objective('background', 6)
            self.queue.schedule_due(now=23000)
            parent = self.queue.claim()
            self.queue.propose_followup(parent[0], 'follow up')
            self.queue.recover()
            self.assertEqual(self.queue.counts(), {'cancelled': 1, 'interrupted': 1})
            self.assertIsNone(self.queue.claim())

    def test_existing_database_schema_is_upgraded(self):
        legacy = os.path.join(self.tmp.name, 'legacy.db')
        with closing(sqlite3.connect(legacy)) as db:
            db.execute('CREATE TABLE jobs (id INTEGER PRIMARY KEY, task TEXT NOT NULL, state TEXT NOT NULL, result TEXT, notified INTEGER NOT NULL DEFAULT 0, update_id INTEGER UNIQUE, created INTEGER NOT NULL)')
            db.execute("INSERT INTO jobs(task,state,created) VALUES('old task','queued',1)")
            db.commit()
        updated = Queue(legacy)
        self.assertEqual(updated.claim(), (1, 'old task'))

    def test_inspect_and_cancel_only_unstarted_work(self):
        first = self.queue.ingest(1, 'first task')
        second = self.queue.ingest(2, 'second task')
        self.assertEqual(self.queue.claim()[0], first)
        self.assertEqual(self.queue.cancel_job(first), 'running')
        self.assertEqual(self.queue.cancel_job(second), 'cancelled')
        self.assertEqual(self.queue.cancel_job(99999), 'not_found')
        self.assertEqual(self.queue.get_job(second)[1], 'cancelled')
        self.assertIsNone(self.queue.claim())
        self.queue.finish(first, 'result text')
        reloaded = Queue(self.queue.path)
        self.assertEqual(reloaded.get_job(first)[4], 'result text')
        self.assertEqual({x[0] for x in reloaded.recent_jobs()}, {first, second})

    def test_cancelling_proposal_prevents_followup_after_parent_finishes(self):
        with patch('miniagent.queue.time.time', return_value=1000):
            self.queue.add_objective('research', 6)
            self.queue.schedule_due(now=23000)
            parent = self.queue.claim()
            proposal = self.queue.propose_followup(parent[0], 'later')
            self.assertEqual(self.queue.cancel_job(proposal), 'cancelled')
            self.queue.finish(parent[0], 'done')
            self.assertIsNone(self.queue.claim())

    def test_questions_workflow_and_clarification(self):
        ident = self.queue.ingest(1, 'ambiguous task')
        job = self.queue.claim()
        self.assertEqual(job[0], ident)
        # Cannot ask question if not running
        with self.assertRaises(ValueError):
            self.queue.propose_question(999, 'q?', 'ctx')
        # Propose question
        qid = self.queue.propose_question(ident, 'Which format?', 'JSON or YAML')
        self.assertIsNotNone(qid)
        # Cannot ask two questions for same task
        with self.assertRaises(ValueError):
            self.queue.propose_question(ident, 'Another?', 'ctx')
        # Question is proposed, not open yet
        self.assertEqual(self.queue.open_questions(), [])
        # When job finishes, question transitions to open
        self.queue.finish(ident, 'Done awaiting answer')
        open_qs = self.queue.open_questions(unnotified=True)
        self.assertEqual(len(open_qs), 1)
        self.assertEqual(open_qs[0], (qid, 'Which format?', 'JSON or YAML', ident))
        self.queue.mark_question_notified(qid)
        self.assertEqual(self.queue.open_questions(unnotified=True), [])
        # Answer question -> queues new continuation job
        cont_job = self.queue.answer_question(qid, 'Use JSON format')
        self.assertIsNotNone(cont_job)
        self.assertEqual(self.queue.open_questions(), [])
        # Cannot answer twice
        with self.assertRaises(ValueError):
            self.queue.answer_question(qid, 'Again')
        # Claim continuation job
        next_job = self.queue.claim()
        self.assertEqual(next_job[0], cont_job)
        self.assertIn('Use JSON format', next_job[1])
        self.assertIn('Which format?', next_job[1])

    def test_task_history_recording_and_querying(self):
        ident = self.queue.ingest(1, 'task with history')
        claimed = self.queue.claim()
        self.assertEqual(claimed[0], ident)
        self.queue.finish(ident, 'success output', duration_ms=1200, tool_calls_count=3)
        history = self.queue.get_history(limit=5)
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertEqual(entry[1], ident)  # job_id
        self.assertEqual(entry[2], 'task with history')
        self.assertEqual(entry[4], 'done')  # state
        self.assertEqual(entry[7], 1200)  # duration_ms
        self.assertEqual(entry[9], 3)  # tool_calls_count
        self.assertIsNone(entry[10])  # error_type

        # Test failed task history
        ident2 = self.queue.ingest(2, 'failed task')
        self.queue.claim()
        self.queue.finish(ident2, 'error occurred', failed=True, error_type='TimeoutError', duration_ms=5000)
        failed_history = self.queue.get_history(failed_only=True)
        self.assertEqual(len(failed_history), 1)
        self.assertEqual(failed_history[0][1], ident2)
        self.assertEqual(failed_history[0][4], 'failed')
        self.assertEqual(failed_history[0][10], 'TimeoutError')

        # Test cancelled task history
        ident3 = self.queue.ingest(3, 'cancelled task')
        self.queue.cancel_job(ident3)
        cancelled_history = self.queue.get_history(job_id=ident3)
        self.assertEqual(len(cancelled_history), 1)
        self.assertEqual(cancelled_history[0][4], 'cancelled')


if __name__ == '__main__':
    unittest.main()
