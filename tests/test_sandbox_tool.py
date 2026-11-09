"""Tests for the ephemeral Cloud Run sandbox tool."""

import os
import unittest
from unittest.mock import patch, MagicMock

try:
    import requests
    from requests.exceptions import RequestException, Timeout
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None
    class RequestException(Exception): pass
    class Timeout(RequestException): pass
    REQUESTS_AVAILABLE = False

from miniagent.tools.sandbox import (
    run_sandboxed_code,
    get_identity_token,
)


@unittest.skipUnless(REQUESTS_AVAILABLE, "requests required for sandbox tool tests")
class TestSandboxTool(unittest.TestCase):
    def test_missing_environment_variable(self):
        """Verify error dictionary returned when CLOUD_RUN_SANDBOX_URL is not set."""
        with patch.dict(os.environ, {}, clear=True):
            res = run_sandboxed_code("print('hello')")
            self.assertEqual(res["exit_code"], 1)
            self.assertEqual(res["stdout"], "")
            self.assertIn("CLOUD_RUN_SANDBOX_URL environment variable is not set", res["stderr"])

    def test_successful_execution(self):
        """Verify standard dictionary returned on successful 200 response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stdout": "Hello, Cloud Run!\n",
            "stderr": "",
            "exit_code": 0,
        }

        with patch.dict(os.environ, {"CLOUD_RUN_SANDBOX_URL": "https://sandbox-test.a.run.app"}), \
             patch("miniagent.tools.sandbox.requests.post", return_value=mock_response) as mock_post, \
             patch("miniagent.tools.sandbox.get_identity_token", return_value="fake-token"):
            
            res = run_sandboxed_code("print('Hello, Cloud Run!')", runtime="python3", timeout=15)
            self.assertEqual(res["stdout"], "Hello, Cloud Run!\n")
            self.assertEqual(res["stderr"], "")
            self.assertEqual(res["exit_code"], 0)

            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(args[0], "https://sandbox-test.a.run.app/exec")
            self.assertEqual(kwargs["json"]["code"], "print('Hello, Cloud Run!')")
            self.assertEqual(kwargs["json"]["runtime"], "python3")
            self.assertEqual(kwargs["json"]["timeout"], 15)
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-token")

    def test_server_error_response(self):
        """Verify handling of non-200 responses without crashing."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.dict(os.environ, {"CLOUD_RUN_SANDBOX_URL": "https://sandbox-test.a.run.app"}), \
             patch("miniagent.tools.sandbox.requests.post", return_value=mock_response), \
             patch("miniagent.tools.sandbox.get_identity_token", return_value=None):
            
            res = run_sandboxed_code("import sys; sys.exit(1)")
            self.assertEqual(res["exit_code"], 500)
            self.assertEqual(res["stdout"], "")
            self.assertIn("HTTP 500: Internal Server Error", res["stderr"])

    def test_timeout_exception(self):
        """Verify handling of request Timeout."""
        with patch.dict(os.environ, {"CLOUD_RUN_SANDBOX_URL": "https://sandbox-test.a.run.app"}), \
             patch("miniagent.tools.sandbox.requests.post", side_effect=Timeout("Request timed out")), \
             patch("miniagent.tools.sandbox.get_identity_token", return_value=None):
            
            res = run_sandboxed_code("import time; time.sleep(100)", timeout=10)
            self.assertEqual(res["exit_code"], 124)
            self.assertEqual(res["stdout"], "")
            self.assertIn("timed out after 10 seconds", res["stderr"])

    def test_request_exception(self):
        """Verify handling of generic RequestException."""
        with patch.dict(os.environ, {"CLOUD_RUN_SANDBOX_URL": "https://sandbox-test.a.run.app"}), \
             patch("miniagent.tools.sandbox.requests.post", side_effect=RequestException("Connection refused")), \
             patch("miniagent.tools.sandbox.get_identity_token", return_value=None):
            
            res = run_sandboxed_code("print('fail')")
            self.assertEqual(res["exit_code"], 1)
            self.assertEqual(res["stdout"], "")
            self.assertIn("Sandbox HTTP request failed: Connection refused", res["stderr"])

    def test_get_identity_token_with_google_auth(self):
        """Verify get_identity_token attempts id_token fetch."""
        with patch("miniagent.tools.sandbox.GoogleAuthRequest") as mock_req_cls, \
             patch("miniagent.tools.sandbox.id_token") as mock_id_token:
            mock_id_token.fetch_id_token.return_value = "mocked-id-token"
            token = get_identity_token("https://test.a.run.app")
            self.assertEqual(token, "mocked-id-token")
            mock_id_token.fetch_id_token.assert_called_once()


if __name__ == "__main__":
    unittest.main()
