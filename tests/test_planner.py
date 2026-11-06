import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from miniagent.agent import Agent, DEFAULT_PLAN
from miniagent.budget import BudgetExceeded
from miniagent.config import Config


class PlannedProvider:
    def __init__(self, response):
        self.response = response
        self.roles = []
        self.planner_tools = 'not-called'

    def complete(self, messages, tools=None):
        text = messages[0]['content']
        if 'Choose the smallest suitable sequence' in text:
            self.planner_tools = tools
            if isinstance(self.response, Exception): raise self.response
            return {'role': 'assistant', 'content': self.response}
        for role in ('researcher', 'builder', 'reviewer'):
            if 'Role: ' + role + '.' in text:
                self.roles.append(role)
                return {'role': 'assistant', 'content': role + ' finished'}
        raise AssertionError('Unexpected role')


class PlannerTests(unittest.TestCase):
    def test_valid_plan_selects_roles_and_reviewer(self):
        fake = PlannedProvider(json.dumps({'roles': ['researcher', 'reviewer']}))
        result = Agent(SimpleNamespace(max_tool_rounds=2, planner_enabled=True), provider=fake).run_task('Research a topic')
        self.assertEqual(fake.roles, ['researcher', 'reviewer'])
        self.assertIsNone(fake.planner_tools)
        self.assertIn('[plan] researcher → reviewer', result)

    def test_invalid_or_unsafe_plans_fall_back_to_full_pipeline(self):
        for response in ('not json', '{"roles":["builder"]}', '{"roles":["reviewer","builder"]}', '{"roles":["administrator","reviewer"]}', '{"roles":["reviewer","reviewer"]}'):
            with self.subTest(response=response):
                fake = PlannedProvider(response)
                result = Agent(SimpleNamespace(max_tool_rounds=2, planner_enabled=True), provider=fake).run_task('Do work')
                self.assertEqual(fake.roles, list(DEFAULT_PLAN))
                self.assertIn('[plan; fallback]', result)

    def test_planner_budget_error_does_not_trigger_unplanned_calls(self):
        fake = PlannedProvider(BudgetExceeded('budget exhausted'))
        with self.assertRaises(BudgetExceeded):
            Agent(SimpleNamespace(max_tool_rounds=2, planner_enabled=True), provider=fake).run_task('Do work')
        self.assertEqual(fake.roles, [])

    def test_disabled_planner_does_not_make_planning_call(self):
        fake = PlannedProvider('should not be used')
        result = Agent(SimpleNamespace(max_tool_rounds=2, planner_enabled=False), provider=fake).run_task('Do work')
        self.assertEqual(fake.roles, list(DEFAULT_PLAN))
        self.assertEqual(fake.planner_tools, 'not-called')
        self.assertNotIn('[plan]', result)

    def test_real_provider_planner_uses_small_output_cap_and_shared_budget(self):
        env = {'MINIAGENT_API_KEY': 'key', 'MINIAGENT_BASE_URL': 'https://example.com/v1', 'MINIAGENT_MODEL': 'model',
               'MINIAGENT_INPUT_USD_PER_MILLION': '0.1', 'MINIAGENT_OUTPUT_USD_PER_MILLION': '0.2', 'MINIAGENT_PLANNER': '1'}
        with patch.dict(os.environ, env, clear=True), patch('miniagent.agent.ChatProvider') as constructor:
            config = Config.from_env()
            primary = constructor.return_value
            Agent(config)
            self.assertEqual(constructor.call_count, 2)
            planner_config, ledger = constructor.call_args_list[1].args
            self.assertEqual(planner_config.max_output_tokens, 128)
            self.assertIs(ledger, primary.budget)

    def test_invalid_planner_configuration_is_rejected(self):
        env = {'MINIAGENT_API_KEY': 'key', 'MINIAGENT_BASE_URL': 'https://example.com/v1', 'MINIAGENT_MODEL': 'model',
               'MINIAGENT_INPUT_USD_PER_MILLION': '0.1', 'MINIAGENT_OUTPUT_USD_PER_MILLION': '0.2', 'MINIAGENT_PLANNER': 'yes'}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError): Config.from_env()


if __name__ == '__main__': unittest.main()
