"""Sequential canary verification harness for safe self-updates."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_canary_tests(workspace_dir: str | None = None, timeout_seconds: int = 45) -> dict:
    """Execute the offline test suite against a candidate environment sequentially."""
    cmd = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests']
    env = os.environ.copy()
    if workspace_dir:
        env['PYTHONPATH'] = str(Path(workspace_dir).resolve())

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            env=env
        )
        passed = (proc.returncode == 0)
        return {
            'passed': passed,
            'exit_code': proc.returncode,
            'output': proc.stdout[-1500:] if proc.stdout else '',
            'status': 'verified_clean' if passed else 'tests_failed'
        }
    except subprocess.TimeoutExpired:
        return {'passed': False, 'status': 'timeout', 'error': 'Canary test execution exceeded timeout.'}
    except Exception as exc:
        return {'passed': False, 'status': 'error', 'error': f'Canary runner failed: {type(exc).__name__}'}
