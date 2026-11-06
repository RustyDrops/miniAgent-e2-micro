import json
import io
import os
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from miniagent.config import Config
from miniagent.doctor import diagnose, endpoint_reachable


class DoctorTests(unittest.TestCase):
    def test_telegram_probe_accepts_only_successful_bot_response(self):
        with patch('miniagent.doctor.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(b'{"ok":true,"result":{"is_bot":true}}')
            self.assertTrue(endpoint_reachable('https://api.telegram.org/botTOKEN/getMe', telegram=True))
            opener.return_value.open.return_value = io.BytesIO(b'{"ok":true,"result":{"is_bot":false}}')
            self.assertFalse(endpoint_reachable('https://api.telegram.org/botTOKEN/getMe', telegram=True))
    def environment(self, directory):
        return {'MINIAGENT_API_KEY': 'primary-secret', 'MINIAGENT_BASE_URL': 'https://example.com/v1',
                'MINIAGENT_MODEL': 'primary', 'MINIAGENT_INPUT_USD_PER_MILLION': '0.1',
                'MINIAGENT_OUTPUT_USD_PER_MILLION': '0.2', 'MINIAGENT_DB': str(Path(directory) / 'state.db'),
                'MINIAGENT_WORKSPACE': str(Path(directory) / 'workspace'),
                'TELEGRAM_BOT_TOKEN': 'telegram-secret', 'TELEGRAM_USER_ID': '1', 'TELEGRAM_CHAT_ID': '2'}

    def test_default_checks_do_not_call_network_or_leak_secrets(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            with patch.dict(os.environ, self.environment(directory), clear=True), patch('miniagent.doctor.ChatProvider') as provider, patch('miniagent.doctor.endpoint_reachable') as endpoint, patch('miniagent.doctor.metadata_reachable') as metadata:
                checks = diagnose(Config.from_env())
                provider.assert_not_called()
                endpoint.assert_not_called()
                metadata.assert_not_called()
            self.assertTrue(all(check['ok'] for check in checks))
            text = json.dumps(checks)
            self.assertNotIn('primary-secret', text)
            self.assertNotIn('telegram-secret', text)
            self.assertIn('Not run', text)

    def test_network_check_warns_about_metadata_without_printing_token(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            with patch.dict(os.environ, self.environment(directory), clear=True), patch('miniagent.doctor.endpoint_reachable', return_value=True) as endpoint, patch('miniagent.doctor.metadata_reachable', return_value=['169.254.169.254']):
                checks = diagnose(Config.from_env(), network=True)
            self.assertEqual(endpoint.call_count, 4)
            warning = next(check for check in checks if check['check'] == 'Cloud metadata exposure')
            self.assertTrue(warning['warning'])
            self.assertNotIn('telegram-secret', json.dumps(checks))

    def test_live_checks_both_models_with_shared_ledger_and_no_error_text(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            env = self.environment(directory)
            env.update({'MINIAGENT_SECONDARY_API_KEY': 'secondary-secret', 'MINIAGENT_SECONDARY_BASE_URL': 'https://example.org/v1',
                        'MINIAGENT_SECONDARY_MODEL': 'gpt-6-luna', 'MINIAGENT_SECONDARY_INPUT_USD_PER_MILLION': '0.125',
                        'MINIAGENT_SECONDARY_OUTPUT_USD_PER_MILLION': '0.5', 'MINIAGENT_SECONDARY_SERVICE_TIER': 'flex'})
            with patch.dict(os.environ, env, clear=True), patch('miniagent.doctor.ChatProvider') as provider:
                provider.return_value.complete.side_effect = [{'role': 'assistant', 'content': 'OK'}, RuntimeError('secondary-secret')]
                checks = diagnose(Config.from_env(), live=True)
                self.assertEqual(provider.call_count, 2)
                self.assertIs(provider.call_args_list[0].args[1], provider.call_args_list[1].args[1])
                self.assertEqual(provider.call_args_list[1].args[0].service_tier, 'flex')
                self.assertEqual(provider.call_args_list[1].args[0].max_output_tokens, 128)
            self.assertFalse(next(x for x in checks if x['check'] == 'Reviewer model')['ok'])
            self.assertNotIn('secret', json.dumps(checks))

    def test_cli_doctor_without_live_returns_success(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            env = dict(os.environ)
            env.update(self.environment(directory))
            for name in list(env):
                if name.startswith('MINIAGENT_SECONDARY_'):
                    del env[name]
            env.pop('MINIAGENT_ENABLE_SANDBOX', None)
            result = subprocess.run([sys.executable, '-m', 'miniagent', 'doctor'], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('OK Budget ledger', result.stdout)
            self.assertIn('Not run', result.stdout)
            self.assertNotIn('secret', result.stdout)


if __name__ == '__main__': unittest.main()
