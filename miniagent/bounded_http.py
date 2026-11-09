"""Bounded HTTP streaming reader to protect low-RAM environments from memory spikes."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ResponseTooLarge(ValueError):
    """Raised when an HTTP response exceeds the configured maximum byte ceiling."""
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def bounded_read(url: str, max_bytes: int = 200000, timeout: int = 15, headers: dict | None = None) -> bytes:
    """Stream an HTTP response in bounded chunks, raising ResponseTooLarge if it exceeds max_bytes."""
    req_headers = {
        "User-Agent": "MiniAgent/1.0 (e2-micro; constrained-agent)",
        "Accept": "*/*",
    }
    if headers:
        req_headers.update(headers)

    req = Request(url, headers=req_headers)
    opener = build_opener(NoRedirect())

    data = bytearray()
    chunk_size = 4096

    with opener.open(req, timeout=timeout) as response:
        while True:
            # Read at most chunk_size or one byte over max_bytes to detect overflow early
            remaining = (max_bytes + 1) - len(data)
            to_read = min(chunk_size, max(1, remaining))
            chunk = response.read(to_read)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                raise ResponseTooLarge(f"HTTP response from {url[:80]} exceeded maximum allowed size of {max_bytes} bytes.")

    return bytes(data)


def bounded_fetch_json(url: str, max_bytes: int = 200000, timeout: int = 15, headers: dict | None = None) -> dict:
    """Fetch an HTTP endpoint with strict memory limits and parse as JSON."""
    raw = bounded_read(url, max_bytes=max_bytes, timeout=timeout, headers=headers)
    return json.loads(raw.decode("utf-8", errors="replace"))
