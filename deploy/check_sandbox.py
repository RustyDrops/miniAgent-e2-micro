"""Run a controlled sandbox smoke check on the target Linux VM."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from miniagent.sandbox import run_python_tests

TEST = '''import ctypes, os, socket, unittest
import subject
class SandboxCheck(unittest.TestCase):
    def test_import(self): self.assertEqual(subject.answer(), 42)
    def test_secrets_not_visible(self):
        self.assertNotIn("MINIAGENT_SANDBOX_CANARY", os.environ)
        self.assertFalse(os.path.exists("/etc/miniagent.env"))
    def test_metadata_unreachable(self):
        for family, address in ((socket.AF_INET, ("169.254.169.254", 80)),
                                (socket.AF_INET6, ("fd20:ce::254", 80))):
            try: sock = socket.socket(family)
            except OSError: continue
            sock.settimeout(1)
            try:
                with self.assertRaises(OSError): sock.connect(address)
            finally: sock.close()
    def test_nested_user_namespace_disabled(self):
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.unshare(0x10000000)  # CLONE_NEWUSER
        self.assertEqual(result, -1, "nested user namespace unexpectedly succeeded")
if __name__ == "__main__": unittest.main()
'''

def main():
    if sys.platform != 'linux':
        print('Sandbox unavailable: this check requires Linux.')
        return 1
    if os.environ.get('MINIAGENT_ENABLE_SANDBOX') != '1':
        print('Sandbox unavailable: set MINIAGENT_ENABLE_SANDBOX=1 for this check.')
        return 1
    os.environ['MINIAGENT_SANDBOX_CANARY'] = 'do-not-expose'
    with tempfile.TemporaryDirectory(prefix='miniagent-check-') as temp:
        source = Path(temp) / 'source.py'
        test = Path(temp) / 'test.py'
        source.write_text('def answer(): return 42\n', encoding='utf-8')
        test.write_text(TEST, encoding='utf-8')
        try:
            result = run_python_tests(source, test)
        except (RuntimeError, OSError, ValueError) as exc:
            print('Sandbox unavailable:', type(exc).__name__, str(exc))
            return 1
        print('Sandbox check:', result['status'])
        print(result['output'])
        return 0 if result['status'] == 'passed' else 1

if __name__ == '__main__':
    raise SystemExit(main())
