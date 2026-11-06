import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from miniagent.evaluation import CASES, evaluate_planner
from miniagent.budget import BudgetExceeded


class FakeBudget:
    def __init__(self): self.calls = 0
    def today(self):
        self.calls += 1
        return (10 if self.calls == 1 else 30, 1000000)


class FakeAgent:
    def __init__(self, fail_at=None): self.index, self.fail_at = 0, fail_at
    def plan_roles(self, prompt):
        if self.index == self.fail_at: raise BudgetExceeded('secret detail')
        name, expected_prompt, expected_roles = CASES[self.index]
        if prompt != expected_prompt: raise AssertionError('unexpected prompt')
        self.index += 1
        return expected_roles, False
    def run_task(self, task): raise AssertionError('fixture tasks must never be executed')


class EvaluationTests(unittest.TestCase):
    def test_evaluation_only_plans_and_reports_cost_delta(self):
        result = evaluate_planner(FakeAgent(), FakeBudget())
        self.assertEqual(result['completed'], len(CASES))
        self.assertEqual(result['exact'], len(CASES))
        self.assertEqual(result['missing_cases'], 0)
        self.assertEqual(result['ledger_change_microdollars'], 20)
        self.assertIsNone(result['error'])

    def test_provider_or_budget_failure_stops_and_reports_partial_results(self):
        result = evaluate_planner(FakeAgent(fail_at=2), FakeBudget())
        self.assertEqual(result['completed'], 2)
        self.assertEqual(result['error'], 'BudgetExceeded')
        self.assertNotIn('secret detail', str(result))

    def test_reports_missing_extra_and_fallback_distinctly(self):
        class Imperfect(FakeAgent):
            def plan_roles(self, prompt):
                result, fallback = super().plan_roles(prompt)
                if self.index == 1: return ('researcher', 'reviewer'), False
                if self.index == 5: return ('reviewer',), True
                return result, fallback
        report = evaluate_planner(Imperfect(), FakeBudget())
        self.assertEqual(report['cases'][0]['extra'], ['researcher'])
        self.assertEqual(report['cases'][4]['missing'], ['builder'])
        self.assertEqual(report['fallbacks'], 1)
        self.assertEqual(report['missing_cases'], 1)

    def test_cli_refuses_paid_evaluation_without_live_flag(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            env = dict(os.environ)
            env.update({'MINIAGENT_API_KEY': 'key', 'MINIAGENT_BASE_URL': 'https://example.com/v1',
                        'MINIAGENT_MODEL': 'model', 'MINIAGENT_INPUT_USD_PER_MILLION': '0.1',
                        'MINIAGENT_OUTPUT_USD_PER_MILLION': '0.2', 'MINIAGENT_DB': str(Path(directory) / 'db.sqlite')})
            result = subprocess.run([sys.executable, '-m', 'miniagent', 'eval-planner'], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertIn('requires --live', result.stderr)


if __name__ == '__main__': unittest.main()
