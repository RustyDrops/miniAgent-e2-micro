"""Optional Linux-only, offline bubblewrap runner for two small Python drafts.

This limits exposure but is not a hardened boundary against kernel exploits.
Never fall back to running the files directly when sandbox setup fails.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

WRAPPER = '''import resource, runpy, sys
for key, value in ((resource.RLIMIT_CPU, 5), (resource.RLIMIT_AS, 268435456),
                   (resource.RLIMIT_DATA, 67108864), (resource.RLIMIT_FSIZE, 1048576),
                   (resource.RLIMIT_NOFILE, 32), (resource.RLIMIT_NPROC, 16),
                   (resource.RLIMIT_CORE, 0)):
    resource.setrlimit(key, (value, value))
sys.path.insert(0, "/work")
sys.argv = ["/work/test_subject.py"]
runpy.run_path("/work/test_subject.py", run_name="__main__")
'''


def sandbox_command(workdir):
    command = ['/usr/bin/bwrap', '--unshare-user', '--disable-userns', '--unshare-pid', '--unshare-net',
               '--unshare-ipc', '--unshare-uts', '--new-session', '--die-with-parent',
               '--clearenv', '--setenv', 'PATH', '/usr/bin', '--setenv', 'HOME', '/tmp',
               '--ro-bind', '/usr', '/usr']
    # Debian/Ubuntu can use merged-/usr symlinks or real library directories.
    for name in ('lib', 'lib64', 'bin'):
        path = Path('/') / name
        if path.is_symlink():
            target = os.readlink(path)
            if target.startswith('/') or '..' in Path(target).parts:
                raise RuntimeError('Unsupported system library layout')
            command += ['--symlink', target, '/' + name]
        elif path.is_dir():
            command += ['--ro-bind', str(path), str(path)]
    # Bind the host temporary directory before masking /tmp inside the sandbox.
    command += ['--ro-bind', str(workdir), '/work', '--proc', '/proc', '--dev', '/dev',
                '--size', '8388608', '--tmpfs', '/tmp', '--chdir', '/work',
                '/usr/bin/python3', '-I', '-B', '-c', WRAPPER]
    return command


def run_python_tests(source_path, test_path):
    if os.environ.get('MINIAGENT_ENABLE_SANDBOX') != '1':
        raise RuntimeError('Sandbox is disabled. Install and verify bubblewrap before enabling it.')
    if sys.platform != 'linux' or not Path('/usr/bin/bwrap').is_file() or not Path('/usr/bin/python3').is_file():
        raise RuntimeError('Linux bubblewrap and /usr/bin/python3 are required; no unsandboxed fallback exists.')
    if source_path.suffix != '.py' or test_path.suffix != '.py':
        raise ValueError('Both drafts must be Python files')
    if source_path.stat().st_size > 20000 or test_path.stat().st_size > 20000:
        raise ValueError('Python drafts must each be under 20 KB')
    source = source_path.read_text(encoding='utf-8')
    tests = test_path.read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='miniagent-test-') as directory:
        workdir = Path(directory)
        (workdir / 'subject.py').write_text(source, encoding='utf-8')
        (workdir / 'test_subject.py').write_text(tests, encoding='utf-8')
        command = sandbox_command(workdir)
        # A regular temporary file avoids unbounded in-memory PIPE capture. The
        # child's file-size limit bounds output once the trusted wrapper starts.
        timeout_seconds = int(os.environ.get('MINIAGENT_SANDBOX_TIMEOUT_SECONDS', '15'))
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                    stderr=subprocess.STDOUT, timeout=timeout_seconds, check=False,
                    env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, close_fds=True)
            except subprocess.TimeoutExpired:
                return {'status': 'timeout', 'output': f'Sandbox exceeded {timeout_seconds} seconds.'}
            output.seek(0)
            text = output.read(1200).decode('utf-8', 'replace')
        return {'status': 'passed' if result.returncode == 0 else 'failed',
                'exit_code': result.returncode, 'output': text,
                'warning': 'Test results are untrusted; a zero exit code does not prove safety or correctness.'}
