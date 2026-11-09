"""Tests for the Cloud Run sandbox service FastAPI application with security hardening."""

import subprocess
import unittest
from unittest.mock import patch, MagicMock

try:
    from sandbox_service.main import app, ExecRequest, ExecResponse, MAX_CODE_BYTES
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi and pydantic required for sandbox_service tests")
class TestSandboxService(unittest.TestCase):
    def test_exec_unsupported_runtime(self):
        req = ExecRequest(code="print('hello')", runtime="ruby")
        from sandbox_service.main import execute_code
        res = execute_code(req)
        self.assertEqual(res.exit_code, 1)
        self.assertIn("Unsupported runtime", res.stderr)

    def test_exec_code_size_limit_rejection(self):
        oversized = "a = 1\n" * ((MAX_CODE_BYTES // 6) + 10)
        from sandbox_service.main import execute_code
        res = execute_code(ExecRequest(code=oversized))
        self.assertEqual(res.exit_code, 1)
        self.assertIn("Payload rejected", res.stderr)
        self.assertIn("exceeds limit", res.stderr)

    def test_exec_success(self):
        mock_proc = MagicMock()
        mock_proc.stdout = "42\n"
        mock_proc.stderr = ""
        mock_proc.returncode = 0

        with patch("sandbox_service.main.subprocess.run", return_value=mock_proc) as mock_run:
            from sandbox_service.main import execute_code
            res = execute_code(ExecRequest(code="print(42)"))
            self.assertEqual(res.stdout, "42\n")
            self.assertEqual(res.stderr, "")
            self.assertEqual(res.exit_code, 0)

            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            cmd = args[0]
            self.assertEqual(cmd[0], "python3")
            self.assertEqual(cmd[1], "-I")
            self.assertTrue(cmd[2].endswith("script.py"))
            self.assertEqual(kwargs["timeout"], 30)
            self.assertTrue(kwargs["capture_output"])
            # Verify environment sanitization & anti-SSRF dummy proxy
            env = kwargs["env"]
            self.assertEqual(env["http_proxy"], "http://127.0.0.1:0")
            self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertIn("TMPDIR", env)

    def test_exec_timeout(self):
        exc = subprocess.TimeoutExpired(cmd=["python3", "-I", "..."], timeout=5, output="partial stdout", stderr="partial stderr")

        with patch("sandbox_service.main.subprocess.run", side_effect=exc):
            from sandbox_service.main import execute_code
            res = execute_code(ExecRequest(code="while True: pass", timeout=5))
            self.assertEqual(res.exit_code, 124)
            self.assertEqual(res.stdout, "partial stdout")
            self.assertIn("Execution timed out after 5 seconds.", res.stderr)

    def test_exec_general_exception(self):
        with patch("sandbox_service.main.subprocess.run", side_effect=RuntimeError("Subprocess failed to launch")):
            from sandbox_service.main import execute_code
            res = execute_code(ExecRequest(code="print('hi')"))
            self.assertEqual(res.exit_code, 1)
            self.assertIn("Sandbox error: Subprocess failed to launch", res.stderr)

    def test_health(self):
        from sandbox_service.main import health
        h = health()
        self.assertEqual(h["status"], "ok")


if __name__ == "__main__":
    unittest.main()
