"""FastAPI ephemeral code execution sandbox service for Cloud Run with hardened isolation."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="MiniAgent Ephemeral Sandbox Service", version="1.1.0")

MAX_CODE_BYTES = 65536  # 64 KB limit to prevent payload-based disk/memory exhaustion


class ExecRequest(BaseModel):
    code: str
    runtime: str = "python3"
    timeout: int = Field(default=30, ge=1, le=300)


class ExecResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


@app.post("/exec", response_model=ExecResponse)
def execute_code(request: ExecRequest) -> ExecResponse:
    """Execute arbitrary Python code inside an ephemeral, isolated container environment."""
    if request.runtime != "python3":
        return ExecResponse(
            stdout="",
            stderr=f"Unsupported runtime '{request.runtime}'. Only 'python3' is supported.",
            exit_code=1,
        )

    code_bytes = request.code.encode("utf-8")
    if len(code_bytes) > MAX_CODE_BYTES:
        return ExecResponse(
            stdout="",
            stderr=f"Payload rejected: Code size ({len(code_bytes)} bytes) exceeds limit of {MAX_CODE_BYTES} bytes.",
            exit_code=1,
        )

    # Isolated ephemeral directory for each execution (prevents cross-request state pollution)
    with tempfile.TemporaryDirectory(prefix="sandbox_run_") as temp_dir:
        script_path = Path(temp_dir) / "script.py"
        script_path.write_bytes(code_bytes)

        # Sanitized, minimal execution environment:
        # - Block metadata server & outbound SSRF via dummy proxy for default HTTP libs
        # - Direct temporary files to the isolated ephemeral directory
        # - Suppress Python bytecode caching
        sanitized_env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": temp_dir,
            "TEMP": temp_dir,
            "TMP": temp_dir,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "http_proxy": "http://127.0.0.1:0",
            "https_proxy": "http://127.0.0.1:0",
            "HTTP_PROXY": "http://127.0.0.1:0",
            "HTTPS_PROXY": "http://127.0.0.1:0",
        }

        try:
            # -I runs in isolated mode (ignores PYTHON* env vars, current directory on sys.path, and user site packages)
            proc = subprocess.run(
                ["python3", "-I", str(script_path)],
                capture_output=True,
                text=True,
                timeout=request.timeout,
                cwd=temp_dir,
                env=sanitized_env,
            )
            return ExecResponse(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            timeout_msg = f"Execution timed out after {request.timeout} seconds."
            stderr = f"{stderr}\n{timeout_msg}".strip() if stderr else timeout_msg
            return ExecResponse(
                stdout=stdout,
                stderr=stderr,
                exit_code=124,
            )
        except Exception as exc:
            return ExecResponse(
                stdout="",
                stderr=f"Sandbox error: {exc}",
                exit_code=1,
            )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "python": sys.version}
