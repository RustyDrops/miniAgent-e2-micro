import os
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from miniagent.budget import Budget, BudgetExceeded, microdollars
from miniagent.agent import Agent, role_schemas
from miniagent.config import Config
from miniagent.provider import ChatProvider, ProviderError
import json
import io
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getcwd())
        self.budget = Budget(os.path.join(self.tmp.name, 'test.db'), Decimal('0.001'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_reservation_and_settlement_persist(self):
        first = self.budget.reserve(800)
        with self.assertRaises(BudgetExceeded):
            self.budget.reserve(201)
        self.budget.settle(first, 100)
        self.budget.reserve(900)
        self.assertEqual(self.budget.today(), (1000, 1000))

    def test_unknown_failure_keeps_reservation(self):
        self.budget.reserve(999)
        reloaded = Budget(self.budget.db_path, Decimal('0.001'))
        self.assertEqual(reloaded.today()[0], 999)
        with self.assertRaises(BudgetExceeded):
            reloaded.reserve(2)

    def test_rounding_never_understates(self):
        self.assertEqual(microdollars(1, Decimal('0.1')), 1)

    def test_usage_reports_cache_and_unsettled_reservations(self):
        first = self.budget.reserve(400, model='muse', tier='standard')
        self.budget.settle(first, 80, input_tokens=500, output_tokens=40, cached_tokens=300)
        self.budget.reserve(200, model='muse', tier='standard')
        rows, truncated = self.budget.usage_today()
        self.assertFalse(truncated)
        self.assertEqual(rows[0]['committed_microdollars'], 280)
        self.assertEqual((rows[0]['input_tokens'], rows[0]['output_tokens'], rows[0]['cached_tokens']), (500, 40, 300))
        self.assertEqual((rows[0]['cache_reported_requests'], rows[0]['unsettled_requests']), (1, 1))

    def test_legacy_ledger_migration_retains_old_spending(self):
        path = os.path.join(self.tmp.name, 'legacy.db')
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE spend (id INTEGER PRIMARY KEY, day TEXT NOT NULL, reserved INTEGER NOT NULL, actual INTEGER, status TEXT NOT NULL)')
            db.execute('INSERT INTO spend(day,reserved,actual,status) VALUES(?,?,?,?)', (datetime.now(timezone.utc).date().isoformat(), 900, 800, 'complete'))
            db.commit()
        budget = Budget(path, Decimal('0.001'))
        self.assertEqual(budget.today()[0], 800)
        self.assertEqual(budget.usage_today()[0][0]['model'], 'unknown')
        with self.assertRaises(BudgetExceeded): budget.reserve(201)

class FakeProvider:
    def __init__(self):
        self.calls = []
    def complete(self, messages, tools=None):
        self.calls.append((messages[:], tools))
        if len(self.calls) == 1:
            return {'role': 'assistant', 'content': None, 'tool_calls': [{'id':'1', 'type':'function', 'function': {'name':'inspect', 'arguments':'{"path":"x"}'}}]}
        return {'role':'assistant', 'content': 'Finished and reviewed.'}

class AgentTests(unittest.TestCase):
    def test_specialist_tools_are_scoped_and_forbidden_calls_are_not_executed(self):
        from miniagent import tools
        class MisbehavingReviewer:
            def __init__(self): self.denial = ''
            def complete(self, messages, schemas=None):
                role = messages[0]['content']
                if 'Role: reviewer.' not in role:
                    return {'role': 'assistant', 'content': 'Done.'}
                output = [m for m in messages if m['role'] == 'tool']
                if output:
                    self.denial = output[-1]['content']
                    return {'role': 'assistant', 'content': 'Review complete.'}
                self.assert_review_schemas(schemas)
                return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': '1', 'type': 'function',
                    'function': {'name': 'write_draft', 'arguments': '{"path":"x","content":"bad"}'}}]}
            def assert_review_schemas(self, schemas):
                assert 'write_draft' not in [s['function']['name'] for s in schemas]
        fake = MisbehavingReviewer()
        seen = []
        Agent(SimpleNamespace(max_tool_rounds=2), lambda *args: seen.append(args), tools.SCHEMAS, provider=fake).run_task('Review')
        self.assertEqual(seen, [])
        self.assertIn('not available', fake.denial)
        full = len(json.dumps(tools.SCHEMAS).encode())
        self.assertTrue(all(len(json.dumps(role_schemas(role, tools.SCHEMAS)).encode()) < full for role in ('researcher', 'builder', 'reviewer')))

    def test_empty_specialist_response_is_failure(self):
        class Empty:
            def complete(self, messages, tools=None): return {'role': 'assistant', 'content': ''}
        with self.assertRaises(ProviderError):
            Agent(SimpleNamespace(max_tool_rounds=0), provider=Empty()).run_task('Do a task')

    def test_tools_are_executed_and_stages_are_bounded(self):
        fake = FakeProvider()
        seen = []
        cfg = SimpleNamespace(max_tool_rounds=2)
        agent = Agent(cfg, lambda name, args: seen.append((name, args)) or 'ok', [{'type':'function', 'function': {'name': 'inspect'}}], provider=fake)
        result = agent.run_task('Find the file')
        self.assertEqual(seen, [('inspect', {'path':'x'})])
        self.assertEqual(len(fake.calls), 4)
        self.assertIn('[reviewer]', result)
        self.assertEqual(fake.calls[1][0][-1]['content'], 'ok')

    def test_unknown_role_prices_are_not_accepted(self):
        env = {'MINIAGENT_API_KEY':'key', 'MINIAGENT_BASE_URL':'https://example.com/v1', 'MINIAGENT_MODEL':'model'}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                Config.from_env()

    def test_zero_pricing_is_not_accepted(self):
        env = {'MINIAGENT_API_KEY':'key', 'MINIAGENT_BASE_URL':'https://example.com/v1', 'MINIAGENT_MODEL':'model',
               'MINIAGENT_INPUT_USD_PER_MILLION':'0', 'MINIAGENT_OUTPUT_USD_PER_MILLION':'0.2'}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                Config.from_env()

    def test_specialist_loop_creates_reads_and_edits_real_draft(self):
        from miniagent import tools
        class Builder:
            def complete(self, messages, schemas=None):
                system = messages[0]['content']
                if 'Role: builder.' not in system:
                    return {'role': 'assistant', 'content': 'Done.'}
                tool_messages = [m for m in messages if m['role'] == 'tool']
                if len(tool_messages) == 0:
                    name, args = 'write_draft', {'path': 'demo.py', 'content': 'def answer():\n    return 1\n'}
                elif len(tool_messages) == 1:
                    name, args = 'read_draft', {'path': 'demo.py'}
                elif len(tool_messages) == 2:
                    digest = json.loads(tool_messages[-1]['content'])['sha256']
                    name, args = 'modify_draft', {'path': 'demo.py', 'expected_sha256': digest, 'mode': 'replace', 'find': 'return 1', 'content': 'return 42'}
                else:
                    return {'role': 'assistant', 'content': 'Draft updated; execution not verified.'}
                return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': str(len(tool_messages)), 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            result = Agent(SimpleNamespace(max_tool_rounds=3), tools.handle, tools.SCHEMAS, provider=Builder()).run_task('Create a small Python draft.')
            self.assertIn('execution not verified', result)
            self.assertIn('return 42', (Path(directory) / 'demo.py').read_text(encoding='utf-8'))

class ProviderTests(unittest.TestCase):
    def test_provider_records_reported_tokens_without_prompt_contents(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            ledger = Budget(os.path.join(directory, 'usage.db'), Decimal('0.01'))
            cfg = SimpleNamespace(model='muse', max_output_tokens=64, service_tier='', max_input_bytes=12000,
                input_price=Decimal('0.1'), output_price=Decimal('0.2'), base_url='https://example.com/v1', api_key='key', timeout_seconds=5)
            reply = {'choices': [{'message': {'role': 'assistant', 'content': 'ok'}}],
                     'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 70}}}
            with patch('urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = io.BytesIO(json.dumps(reply).encode())
                ChatProvider(cfg, ledger).complete([{'role': 'user', 'content': 'private-prompt-canary'}])
            row = ledger.usage_today()[0][0]
            self.assertEqual((row['model'], row['input_tokens'], row['output_tokens'], row['cached_tokens']), ('muse', 100, 20, 70))
            self.assertNotIn('private-prompt-canary', str(row))

    def test_flex_429_retries_same_request_with_new_reservation(self):
        class Ledger:
            def __init__(self): self.reserved, self.settled = [], []
            def reserve(self, amount, **metadata):
                self.reserved.append(amount)
                return len(self.reserved)
            def settle(self, ident, amount, **usage): self.settled.append((ident, amount))
        cfg = SimpleNamespace(model='gpt-6-luna', max_output_tokens=64, service_tier='flex', max_retries=1, retry_wait_seconds=5,
            max_input_bytes=12000, input_price=Decimal('0.1'), output_price=Decimal('0.5'),
            base_url='https://example.com/v1', api_key='x', timeout_seconds=5)
        ledger = Ledger()
        reply = {'service_tier': 'flex', 'choices': [{'message': {'role': 'assistant', 'content': 'ok'}}],
                 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
        error = HTTPError('https://example.com', 429, 'busy', {'Retry-After': '3'}, io.BytesIO(b''))
        with patch('urllib.request.build_opener') as opener, patch('miniagent.provider.time.sleep') as sleep:
            opener.return_value.open.side_effect = [error, io.BytesIO(json.dumps(reply).encode())]
            self.assertEqual(ChatProvider(cfg, ledger).complete([{'role': 'user', 'content': 'hi'}])['content'], 'ok')
            self.assertEqual(opener.return_value.open.call_count, 2)
            self.assertEqual(len(ledger.reserved), 2)
            self.assertEqual(ledger.settled, [(2, 4)])
            self.assertTrue(error.closed)
            sleep.assert_called_once_with(3)

    def test_no_retry_after_long_delay_or_uncertain_network_failure(self):
        class Ledger:
            def reserve(self, amount, **metadata): return 1
            def settle(self, ident, amount, **usage): pass
        cfg = SimpleNamespace(model='gpt-6-luna', max_output_tokens=64, service_tier='flex', max_retries=1, retry_wait_seconds=5,
            max_input_bytes=12000, input_price=Decimal('0.1'), output_price=Decimal('0.5'),
            base_url='https://example.com/v1', api_key='x', timeout_seconds=5)
        for error in (HTTPError('https://example.com', 429, 'busy', {'Retry-After': '60'}, io.BytesIO(b'')), URLError('unavailable')):
            with self.subTest(error=type(error).__name__), patch('urllib.request.build_opener') as opener, patch('miniagent.provider.time.sleep') as sleep:
                opener.return_value.open.side_effect = error
                with self.assertRaises(ProviderError): ChatProvider(cfg, Ledger()).complete([{'role': 'user', 'content': 'hi'}])
                self.assertEqual(opener.return_value.open.call_count, 1)
                sleep.assert_not_called()

    def test_luna_uses_none_and_flex_is_confirmed(self):
        class Ledger:
            def reserve(self, amount, **metadata): return 1
            def settle(self, reservation, amount, **usage): self.settled = amount
        cfg = SimpleNamespace(model='gpt-6-luna', max_output_tokens=64, service_tier='flex',
            max_input_bytes=12000, input_price=Decimal('0.1'), output_price=Decimal('0.5'),
            base_url='https://example.com/v1', api_key='x', timeout_seconds=5)
        ledger = Ledger()
        response = {'service_tier': 'flex', 'choices': [{'message': {'role':'assistant', 'content':'ok'}}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
            ChatProvider(cfg, ledger).complete([{'role':'user','content':'hi'}], [{'type':'function'}])
            payload = json.loads(opener.return_value.open.call_args.args[0].data)
            self.assertEqual(payload['reasoning_effort'], 'none')
            self.assertEqual(payload['service_tier'], 'flex')
            self.assertEqual(ledger.settled, 4)
        response['service_tier'] = 'default'
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
            with self.assertRaises(ProviderError):
                ChatProvider(cfg, ledger).complete([{'role':'user','content':'hi'}])

    def test_job_tool_handler_propose_question(self):
        from miniagent.__main__ import job_tool_handler
        from miniagent.queue import Queue
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            db_path = os.path.join(directory, 'test.db')
            q = Queue(db_path)
            jid = q.ingest(1, 'task')
            q.claim()
            b = Budget(db_path, Decimal('1.0'))
            handler = job_tool_handler(q, b, jid)
            res = handler('propose_question', {'question': 'Which style?', 'context': 'Formatting'})
            self.assertIn('Question 1 proposed', res)
            self.assertIn('rejected', handler('propose_question', {'question': 'Another?'}))

if __name__ == '__main__':
    unittest.main()

