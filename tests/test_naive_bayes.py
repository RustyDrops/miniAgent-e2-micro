import os
import tempfile
import unittest
from types import SimpleNamespace

from miniagent.naive_bayes import NaiveBayesRouter, tokenize
from miniagent.agent import Agent, DEFAULT_PLAN


class DummyProvider:
    def __init__(self, response):
        self.response = response
        self.call_count = 0

    def complete(self, messages, tools=None, max_output_tokens=None):
        self.call_count += 1
        text = messages[0]['content']
        if 'Choose the smallest suitable sequence' in text:
            return {'role': 'assistant', 'content': self.response}
        return {'role': 'assistant', 'content': 'Completed by specialist'}


class NaiveBayesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'bayes.db')
        self.router = NaiveBayesRouter(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tokenization_and_stopwords(self):
        tokens = tokenize("Research one practical agentic AI technique for SQLite!")
        self.assertNotIn('for', tokens)
        self.assertNotIn('one', tokens)
        self.assertIn('research', tokens)
        self.assertIn('practical', tokens)
        self.assertIn('sqlite', tokens)

    def test_shadow_mode_and_confidence_gating(self):
        # 1. When empty, router must decline to guess
        plan, conf, src = self.router.predict("Fix a unit test bug in tools")
        self.assertIsNone(plan)
        self.assertIn(src, ('no_data', 'uncertain'))

        # 2. Teacher learns builder tasks
        self.router.learn("Write unit test for calculator", ('builder', 'reviewer'), source='teacher')
        self.router.learn("Implement bug fix and test scaffold", ('builder', 'reviewer'), source='teacher')
        self.router.learn("Write Python code and test draft", ('builder', 'reviewer'), source='teacher')

        # Teacher learns research tasks
        self.router.learn("Search arxiv for transformer papers", ('researcher', 'reviewer'), source='teacher')
        self.router.learn("Research wikipedia article on consensus", ('researcher', 'reviewer'), source='teacher')

        # 3. Predict on similar builder task
        pred_plan, pred_conf, pred_src = self.router.predict("Write python test for parser")
        self.assertEqual(pred_plan, ('builder', 'reviewer'))
        self.assertGreaterEqual(pred_conf, 0.80)
        self.assertEqual(pred_src, 'naive_bayes')

        # 4. Predict on unfamiliar task (low confidence -> defers to teacher)
        unk_plan, unk_conf, unk_src = self.router.predict("Quantum teleportation of photons")
        self.assertIsNone(unk_plan)
        self.assertEqual(unk_src, 'uncertain')

    def test_daily_audit_and_self_improvement(self):
        # Seed decisions
        self.router.learn("Search papers on arXiv", ('researcher', 'reviewer'), source='naive_bayes', success=True)
        self.router.learn("Write test code", ('builder', 'reviewer'), source='naive_bayes', success=True)
        self.router.learn("Unfamiliar task", ('researcher', 'builder', 'reviewer'), source='teacher', success=True)

        audit = self.router.daily_audit(hours=24)
        self.assertEqual(audit['total_routed'], 3)
        self.assertEqual(audit['naive_bayes_routed'], 2)
        self.assertEqual(audit['teacher_llm_routed'], 1)
        self.assertEqual(audit['naive_bayes_accuracy_pct'], 100.0)
        self.assertGreater(audit['cost_saved_usd'], 0)
        self.assertIn('researcher,reviewer', audit['plans_distribution'])

    def test_agent_integration_uses_naive_bayes_fast_path(self):
        # Teach router first
        for _ in range(3):
            self.router.learn("Implement Python unit test scaffold", ('builder', 'reviewer'), source='teacher')

        fake_provider = DummyProvider('{"roles": ["researcher", "reviewer"]}')
        config = SimpleNamespace(max_tool_rounds=2, planner_enabled=True, db_path=self.db_path)
        agent = Agent(config, provider=fake_provider)

        # Run task matching learned builder pattern
        result = agent.run_task("Implement unit test code")
        # Planner LLM complete() should NOT be called for planning because Naive Bayes handled it locally!
        # Only the builder and reviewer roles should call complete()
        self.assertEqual(fake_provider.call_count, 2)
        self.assertIn('[plan] builder → reviewer', result)


if __name__ == '__main__':
    unittest.main()
