"""Ephemeral Cloud Run Sandbox Tool for executing code safely without host OOM risks."""

import os
from typing import Dict, Any, Optional

try:
    import requests
    from requests.exceptions import RequestException, Timeout
except ImportError:
    requests = None

    class RequestException(Exception):
        """Fallback exception when requests is not installed."""
        pass

    class Timeout(RequestException):
        """Fallback timeout exception when requests is not installed."""
        pass

try:
    import google.auth
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import id_token
except ImportError:
    google = None
    GoogleAuthRequest = None
    id_token = None


def get_identity_token(audience: str) -> Optional[str]:
    """Generate an identity token from the GCP metadata server using google.auth."""
    if GoogleAuthRequest is None:
        return None
    try:
        auth_request = GoogleAuthRequest()
        if id_token is not None:
            return id_token.fetch_id_token(auth_request, audience)
    except Exception:
        # Fall back if id_token cannot fetch (e.g. running outside GCP metadata server)
        pass

    try:
        if google is not None and hasattr(google, "auth"):
            credentials, _ = google.auth.default()
            auth_request = GoogleAuthRequest()
            credentials.refresh(auth_request)
            return getattr(credentials, "token", None) or getattr(credentials, "id_token", None)
    except Exception:
        pass

    return None


def run_sandboxed_code(code: str, runtime: str = "python3", timeout: int = 30) -> Dict[str, Any]:
    """Dispatch code execution over HTTP to an external Cloud Run sandbox container.

    Returns a standardized dictionary:
        {"stdout": str, "stderr": str, "exit_code": int}
    """
    sandbox_url = os.environ.get("CLOUD_RUN_SANDBOX_URL", "").strip()
    if not sandbox_url:
        return {
            "stdout": "",
            "stderr": "CLOUD_RUN_SANDBOX_URL environment variable is not set",
            "exit_code": 1,
        }

    exec_url = sandbox_url if sandbox_url.endswith("/exec") else f"{sandbox_url.rstrip('/')}/exec"

    headers = {"Content-Type": "application/json"}

    # Attempt to generate an identity/access token from GCP metadata server
    token = get_identity_token(sandbox_url)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "code": code,
        "runtime": runtime,
        "timeout": timeout,
    }

    if requests is None:
        return {
            "stdout": "",
            "stderr": "requests library is required for HTTP sandbox execution",
            "exit_code": 1,
        }

    try:
        response = requests.post(
            exec_url,
            json=payload,
            headers=headers,
            timeout=timeout + 5,
        )
        if response.status_code == 200:
            data = response.json()
            return {
                "stdout": str(data.get("stdout", "")),
                "stderr": str(data.get("stderr", "")),
                "exit_code": int(data.get("exit_code", 0)),
            }
        else:
            return {
                "stdout": "",
                "stderr": f"HTTP {response.status_code}: {response.text}",
                "exit_code": response.status_code if response.status_code != 0 else 1,
            }
    except Timeout:
        return {
            "stdout": "",
            "stderr": f"Sandbox execution timed out after {timeout} seconds",
            "exit_code": 124,
        }
    except RequestException as exc:
        return {
            "stdout": "",
            "stderr": f"Sandbox HTTP request failed: {exc}",
            "exit_code": 1,
        }
    except Exception as exc:
        return {
            "stdout": "",
            "stderr": f"Unexpected error during sandboxed code execution: {exc}",
            "exit_code": 1,
        }
