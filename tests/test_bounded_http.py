"""Tests for the bounded HTTP streaming client."""

import io
import json
import unittest
from unittest.mock import patch, MagicMock

from miniagent.bounded_http import bounded_read, bounded_fetch_json, ResponseTooLarge


class TestBoundedHTTP(unittest.TestCase):
    def test_bounded_read_success(self):
        mock_response = io.BytesIO(b"Hello world from bounded HTTP")
        with patch("miniagent.bounded_http.build_opener") as mock_opener:
            mock_client = MagicMock()
            mock_client.open.return_value.__enter__.return_value = mock_response
            mock_opener.return_value = mock_client

            data = bounded_read("https://api.example.com/test", max_bytes=100)
            self.assertEqual(data, b"Hello world from bounded HTTP")

    def test_bounded_read_exceeds_ceiling_raises(self):
        mock_response = io.BytesIO(b"A" * 150)
        with patch("miniagent.bounded_http.build_opener") as mock_opener:
            mock_client = MagicMock()
            mock_client.open.return_value.__enter__.return_value = mock_response
            mock_opener.return_value = mock_client

            with self.assertRaises(ResponseTooLarge):
                bounded_read("https://api.example.com/huge", max_bytes=100)

    def test_bounded_fetch_json(self):
        payload = {"status": "ok", "items": [1, 2, 3]}
        mock_response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        with patch("miniagent.bounded_http.build_opener") as mock_opener:
            mock_client = MagicMock()
            mock_client.open.return_value.__enter__.return_value = mock_response
            mock_opener.return_value = mock_client

            data = bounded_fetch_json("https://api.example.com/json", max_bytes=500)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["items"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
