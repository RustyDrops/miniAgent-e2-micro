import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from miniagent import sandbox


class SandboxTests(unittest.TestCase):
    def test_smoke_fixture_and_resource_wrapper_are_valid_python(self):
        from deploy.check_sandbox import TEST
        compile(TEST, 'sandbox-smoke', 'exec')
        compile(sandbox.WRAPPER, 'sandbox-wrapper', 'exec')
        self.assertIn('CLONE_NEWUSER', TEST)

    def test_disabled_or_wrong_platform_never_launches(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sandbox.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                sandbox.run_python_tests(Path('source.py'), Path('test.py'))
            run.assert_not_called()
        with patch.dict(os.environ, {'MINIAGENT_ENABLE_SANDBOX': '1'}, clear=True), patch.object(sandbox.sys, 'platform', 'win32'), patch.object(sandbox.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                sandbox.run_python_tests(Path('source.py'), Path('test.py'))
            run.assert_not_called()

    def test_command_requires_network_and_pid_isolation_and_binds_before_masking(self):
        with patch.object(Path, 'is_symlink', return_value=False), patch.object(Path, 'is_dir', return_value=False):
            command = sandbox.sandbox_command('/tmp/test-work')
        for flag in ('--unshare-user', '--disable-userns', '--unshare-pid', '--unshare-net', '--clearenv', '--die-with-parent', '--new-session'):
            self.assertIn(flag, command)
        self.assertLess(command.index('/tmp/test-work'), command.index('--tmpfs'))
        self.assertEqual(command[command.index('--size') + 1], '8388608')
        self.assertNotIn('--share-net', command)

    def test_execution_does_not_inherit_secrets(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            source, test = Path(directory) / 'source.py', Path(directory) / 'test.py'
            source.write_text('x=1', encoding='utf-8')
            test.write_text('import subject', encoding='utf-8')
            env = {'MINIAGENT_ENABLE_SANDBOX': '1', 'SECRET_CANARY': 'hidden'}
            with patch.dict(os.environ, env, clear=True), patch.object(sandbox.sys, 'platform', 'linux'), \
                 patch.object(Path, 'is_file', return_value=True), patch.object(sandbox, 'sandbox_command', return_value=['/usr/bin/bwrap']), \
                 patch.object(sandbox.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
                result = sandbox.run_python_tests(source, test)
            self.assertEqual(result['status'], 'passed')
            kwargs = run.call_args.kwargs
            self.assertNotIn('SECRET_CANARY', kwargs['env'])
            self.assertEqual(kwargs['timeout'], 15)
            self.assertTrue(kwargs['close_fds'])
            self.assertNotIn('shell', kwargs)

    def test_failed_bubblewrap_never_falls_back_to_direct_execution(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            source, test = Path(directory) / 'source.py', Path(directory) / 'test.py'
            source.write_text('x=1', encoding='utf-8')
            test.write_text('import subject', encoding='utf-8')
            with patch.dict(os.environ, {'MINIAGENT_ENABLE_SANDBOX': '1'}, clear=True), patch.object(sandbox.sys, 'platform', 'linux'), \
                 patch.object(Path, 'is_file', return_value=True), patch.object(sandbox, 'sandbox_command', return_value=['/usr/bin/bwrap', '--disable-userns']), \
                 patch.object(sandbox.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
                result = sandbox.run_python_tests(source, test)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][0], '/usr/bin/bwrap')


if __name__ == '__main__':
    unittest.main()
