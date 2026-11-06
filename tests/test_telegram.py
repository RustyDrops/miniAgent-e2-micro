import os
import tempfile
import unittest
from decimal import Decimal
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from miniagent.__main__ import telegram_loop, task_error_message, telegram_chunks
from miniagent.provider import ProviderError
from miniagent.budget import Budget
from miniagent.queue import Queue
from miniagent import tools
from miniagent.github import read_bundle


class TelegramIntegrationTests(unittest.TestCase):
    def test_health_command_returns_snapshot_to_authorized_chat(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            cfg = SimpleNamespace(db_path=os.path.join(directory, 'state.db'), daily_usd=Decimal('0.5'))
            update = {'update_id': 1, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': '/health'}}
            sent = []
            def api(token, method, data, timeout=40):
                if method == 'sendMessage': sent.append(data['text']); return {}
                if data['offset'] == 0: return [update]
                raise KeyboardInterrupt
            class NoThread:
                def __init__(self, **kwargs): pass
                def start(self): pass
            env = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_USER_ID': '1', 'TELEGRAM_CHAT_ID': '2', 'MINIAGENT_STATE_DIR': directory}
            with patch.dict(os.environ, env, clear=True), patch('miniagent.__main__.telegram_api', side_effect=api), patch('miniagent.__main__.threading.Thread', NoThread), patch('miniagent.health.collect', return_value={'vm_memory_available_mib': 512}):
                with self.assertRaises(KeyboardInterrupt): telegram_loop(cfg)
            self.assertTrue(any('vm_memory_available_mib' in text and '512' in text for text in sent))
            self.assertNotIn('secret', ''.join(sent))

    def test_budget_command_reports_usage_without_secrets(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            db_path = os.path.join(directory, 'state.db')
            ledger = Budget(db_path, Decimal('0.5'))
            ident = ledger.reserve(100, model='muse', tier='standard')
            ledger.settle(ident, 20, input_tokens=50, output_tokens=10, cached_tokens=30)
            cfg = SimpleNamespace(db_path=db_path, daily_usd=Decimal('0.5'))
            update = {'update_id': 1, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': '/budget'}}
            sent = []
            def api(token, method, data, timeout=40):
                if method == 'sendMessage': sent.append(data['text']); return {}
                if data['offset'] == 0: return [update]
                raise KeyboardInterrupt
            class NoThread:
                def __init__(self, **kwargs): pass
                def start(self): pass
            env = {'TELEGRAM_BOT_TOKEN': 'token-secret', 'TELEGRAM_USER_ID': '1', 'TELEGRAM_CHAT_ID': '2', 'MINIAGENT_STATE_DIR': directory}
            with patch.dict(os.environ, env, clear=True), patch('miniagent.__main__.telegram_api', side_effect=api), patch('miniagent.__main__.threading.Thread', NoThread):
                with self.assertRaises(KeyboardInterrupt): telegram_loop(cfg)
            self.assertTrue(any('muse [standard]' in text and '30 cached' in text for text in sent))
            self.assertNotIn('token-secret', ''.join(sent))

    def test_long_unicode_messages_are_split_without_losing_text(self):
        text = 'start ' + '🧪' * 5000 + ' end'
        chunks = list(telegram_chunks(text))
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(len(chunk.encode('utf-16-le')) // 2 <= 3500 for chunk in chunks))

    def test_task_inspection_and_cancel_commands(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            db_path = os.path.join(directory, 'state.db')
            ident = Queue(db_path).ingest(1, 'an existing task')
            cfg = SimpleNamespace(db_path=db_path, daily_usd=Decimal('0.5'))
            commands = ['/jobs', f'/job {ident}', f'/cancel {ident}', f'/job {ident}', '/cancel 9999999999999999999999999999']
            updates = [{'update_id': i + 2, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': command}} for i, command in enumerate(commands)]
            sent = []
            def api(token, method, data, timeout=40):
                if method == 'sendMessage':
                    sent.append(data['text'])
                    return {}
                if data['offset'] == 2: return updates
                raise KeyboardInterrupt
            class NoThread:
                def __init__(self, **kwargs): pass
                def start(self): pass
            env = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_USER_ID': '1', 'TELEGRAM_CHAT_ID': '2', 'MINIAGENT_STATE_DIR': directory}
            with patch.dict(os.environ, env, clear=True), patch('miniagent.__main__.telegram_api', side_effect=api), patch('miniagent.__main__.threading.Thread', NoThread):
                with self.assertRaises(KeyboardInterrupt): telegram_loop(cfg)
            self.assertTrue(any('an existing task' in text and 'queued' in text for text in sent))
            self.assertTrue(any('Task cancelled' in text for text in sent))
            self.assertTrue(any('cancelled' in text and 'Result:' in text for text in sent))
            self.assertTrue(any('valid positive' in text for text in sent))

    def test_failure_message_exposes_only_safe_provider_errors(self):
        self.assertIn('HTTP 429', task_error_message(ProviderError('Model provider returned HTTP 429; reservation retained.')))
        self.assertNotIn('secret', task_error_message(RuntimeError('secret')))

    def test_homepage_command_uses_preview_hash(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            site = Path(directory) / 'site'
            site.mkdir()
            content = b'<html>hello</html>'
            (site / 'index.html').write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            cfg = SimpleNamespace(db_path=os.path.join(directory, 'state.db'), daily_usd=Decimal('0.5'))
            messages = ['/preview site/index.html', '/publish_site ' + digest]
            updates = [{'update_id': i + 1, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': message}} for i, message in enumerate(messages)]
            sent = []
            def api(token, method, data, timeout=40):
                if method == 'sendMessage':
                    sent.append(data['text'])
                    return {}
                if data['offset'] == 0: return updates
                raise KeyboardInterrupt
            class NoThread:
                def __init__(self, **kwargs): pass
                def start(self): pass
            env = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_USER_ID': '1', 'TELEGRAM_CHAT_ID': '2', 'MINIAGENT_STATE_DIR': directory}
            with patch.dict(os.environ, env, clear=True), patch('miniagent.__main__.telegram_api', side_effect=api), patch('miniagent.__main__.Agent'), patch('miniagent.__main__.threading.Thread', NoThread), patch('miniagent.__main__.configured_github') as github:
                github.return_value.publish_site.return_value = 'https://github.com/owner/repo/pull/1'
                with self.assertRaises(KeyboardInterrupt): telegram_loop(cfg)
                github.return_value.publish_site.assert_called_once_with(digest)
            self.assertTrue(any('/publish_site ' + digest in message for message in sent))
            self.assertTrue(any('Homepage draft pull request created' in message for message in sent))

    def test_bundle_commands_preview_and_forward_verified_manifest(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            project = Path(directory) / 'project'
            project.mkdir()
            (project / 'tool.py').write_text('print(42)', encoding='utf-8')
            _, _, digest = read_bundle('project')
            cfg = SimpleNamespace(db_path=os.path.join(directory, 'state.db'), daily_usd=Decimal('0.5'))
            messages = ['/preview_bundle project', '/publish_bundle project ' + digest]
            updates = [{'update_id': i + 1, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': message}} for i, message in enumerate(messages)]
            sent = []
            def api(token, method, data, timeout=40):
                if method == 'sendMessage':
                    sent.append(data['text'])
                    return {}
                if data['offset'] == 0: return updates
                raise KeyboardInterrupt
            class NoThread:
                def __init__(self, **kwargs): pass
                def start(self): pass
            env = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_USER_ID': '1', 'TELEGRAM_CHAT_ID': '2', 'MINIAGENT_STATE_DIR': directory}
            with patch.dict(os.environ, env, clear=True), patch('miniagent.__main__.telegram_api', side_effect=api), patch('miniagent.__main__.Agent'), patch('miniagent.__main__.threading.Thread', NoThread), patch('miniagent.__main__.configured_github') as github:
                github.return_value.publish_bundle.return_value = 'https://github.com/owner/repo/pull/1'
                with self.assertRaises(KeyboardInterrupt): telegram_loop(cfg)
                github.return_value.publish_bundle.assert_called_once_with('project', digest)
            self.assertTrue(any('tool.py' in message and digest in message for message in sent))
            self.assertTrue(any('Draft pull request created' in message for message in sent))

    def test_private_updates_become_durable_jobs_and_commands(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            db_path = os.path.join(directory, 'state.db')
            cfg = SimpleNamespace(db_path=db_path, daily_usd=Decimal('0.5'))
            events = []
            updates = [
                {'update_id': 1, 'message': {'from': {'id': 9}, 'chat': {'id': 10, 'type': 'private'}, 'text': 'forbidden'}},
                {'update_id': 2, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': 'make a draft'}},
                {'update_id': 3, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': '/pause'}},
            ]
            def api(token, method, data, timeout=40):
                events.append((method, data))
                if method == 'getUpdates':
                    if data['offset'] == 0:
                        return updates
                    raise KeyboardInterrupt
                return {}
            class NoThread:
                def __init__(self, **kwargs): pass
                def start(self): pass
            env = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_USER_ID': '1', 'TELEGRAM_CHAT_ID': '2', 'MINIAGENT_STATE_DIR': directory}
            with patch.dict(os.environ, env, clear=True), patch('miniagent.__main__.telegram_api', side_effect=api), patch('miniagent.__main__.Agent'), patch('miniagent.__main__.threading.Thread', NoThread):
                with self.assertRaises(KeyboardInterrupt):
                    telegram_loop(cfg)
            queue = Queue(db_path)
            self.assertEqual(queue.offset(), 4)
            self.assertTrue(queue.paused())
            self.assertEqual(queue.counts(), {'queued': 1})
            self.assertTrue(any('queued' in data['text'] for method, data in events if method == 'sendMessage'))

    def test_questions_and_answer_commands(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            db_path = os.path.join(directory, 'state.db')
            q = Queue(db_path)
            jid = q.ingest(1, 'an ambiguous task')
            q.claim()
            qid = q.propose_question(jid, 'Do you want SQLite or PostgreSQL?', 'DB choice')
            q.finish(jid, 'Awaiting answer')
            cfg = SimpleNamespace(db_path=db_path, daily_usd=Decimal('0.5'))
            updates = [
                {'update_id': 2, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': '/questions'}},
                {'update_id': 3, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': f'/answer {qid} Use SQLite'}},
                {'update_id': 4, 'message': {'from': {'id': 1}, 'chat': {'id': 2, 'type': 'private'}, 'text': '/questions'}},
            ]
            sent = []
            def api(token, method, data, timeout=40):
                if method == 'sendMessage':
                    sent.append(data['text'])
                    return {}
                if data['offset'] == 2:
                    return updates
                raise KeyboardInterrupt
            class NoThread:
                def __init__(self, **kwargs): pass
                def start(self): pass
            env = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_USER_ID': '1', 'TELEGRAM_CHAT_ID': '2', 'MINIAGENT_STATE_DIR': directory}
            with patch.dict(os.environ, env, clear=True), patch('miniagent.__main__.telegram_api', side_effect=api), patch('miniagent.__main__.threading.Thread', NoThread):
                with self.assertRaises(KeyboardInterrupt): telegram_loop(cfg)
            self.assertTrue(any('Do you want SQLite or PostgreSQL?' in text for text in sent))
            self.assertTrue(any('Answer accepted. Continuing task as job' in text for text in sent))
            self.assertTrue(any('No open questions.' in text for text in sent))


if __name__ == '__main__':
    unittest.main()
