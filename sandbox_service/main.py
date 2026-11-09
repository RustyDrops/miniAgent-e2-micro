"""FastAPI ephemeral code execution sandbox service for Cloud Run."""

import subprocess
import sys
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="MiniAgent Ephemeral Sandbox Service", version="1.0.0")


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
    """Execute arbitrary Python code inside ephemeral container."""
    if request.runtime != "python3":
        return ExecResponse(
            stdout="",
            stderr=f"Unsupported runtime '{request.runtime}'. Only 'python3' is supported.",
            exit_code=1,
        )

    try:
        proc = subprocess.run(
            ["python3", "-c", request.code],
            capture_output=True,
            text=True,
            timeout=request.timeout,
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
