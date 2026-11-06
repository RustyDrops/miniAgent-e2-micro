import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from miniagent import tools
from miniagent.github import GitHub, GitHubError, GitHubNotFound, read_draft, read_bundle


class GitHubTests(unittest.TestCase):
    def test_exact_previewed_bytes_become_draft_pr_on_new_branch(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            (Path(directory) / 'report.md').write_bytes(b'hello\n')
            _, _, digest = read_draft('report.md')
            gh = GitHub('owner/repo', 'secret')
            calls = []
            def request(method, path, payload=None):
                calls.append((method, path, payload))
                if path == '': return {'default_branch': 'main'}
                if path.startswith('/git/ref/heads/'): return {'object': {'sha': 'a' * 40}}
                if path == '/pulls': return {'html_url': 'https://github.com/owner/repo/pull/7'}
                return {}
            with patch.object(gh, 'request', side_effect=request):
                self.assertEqual(gh.publish('report.md', digest), 'https://github.com/owner/repo/pull/7')
            self.assertEqual([c[0] for c in calls], ['GET', 'GET', 'POST', 'PUT', 'POST'])
            branch = calls[2][2]['ref'].removeprefix('refs/heads/')
            self.assertTrue(branch.startswith('miniagent/draft-'))
            self.assertEqual(calls[3][2]['branch'], branch)
            self.assertEqual(base64.b64decode(calls[3][2]['content']), b'hello\n')
            self.assertTrue(calls[4][2]['draft'])
            self.assertEqual(calls[4][2]['base'], 'main')
            self.assertEqual(calls[4][2]['head'], branch)
            self.assertIn(digest, calls[4][2]['body'])

    def test_changed_draft_and_invalid_paths_do_not_call_api(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            (Path(directory) / 'report.md').write_text('changed')
            gh = GitHub('owner/repo', 'secret')
            with patch.object(gh, 'request') as request:
                with self.assertRaises(ValueError):
                    gh.publish('report.md', hashlib.sha256(b'original').hexdigest())
                with self.assertRaises(ValueError):
                    gh.publish('../secret', '0' * 64)
                request.assert_not_called()

    def test_uncertain_failure_reports_branch_without_secret(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            (Path(directory) / 'x.md').write_text('x')
            gh = GitHub('owner/repo', 'secret')
            with patch.object(gh, 'request', side_effect=[{'default_branch': 'main'}, {'object': {'sha': 'a' * 40}}, RuntimeError('secret')]):
                with self.assertRaises(GitHubError) as error:
                    gh.publish('x.md', hashlib.sha256(b'x').hexdigest())
            self.assertIn('miniagent/draft-', str(error.exception))
            self.assertNotIn('secret', str(error.exception))

    def test_bundle_publishes_exact_snapshot_in_one_draft_pr(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            root = Path(directory) / 'project'
            (root / 'tests').mkdir(parents=True)
            (root / 'tool.py').write_bytes(b'def f(): return 1\n')
            (root / 'tests' / 'test_tool.py').write_bytes(b'assert True\n')
            files, manifest, digest = read_bundle('project')
            self.assertEqual([x['path'] for x in manifest], ['tests/test_tool.py', 'tool.py'])
            gh = GitHub('owner/repo', 'secret')
            calls = []
            def request(method, path, payload=None):
                calls.append((method, path, payload))
                if path == '': return {'default_branch': 'main'}
                if path.startswith('/git/ref/heads/'): return {'object': {'sha': 'a' * 40}}
                if path == '/pulls': return {'html_url': 'https://github.com/owner/repo/pull/7'}
                return {}
            with patch.object(gh, 'request', side_effect=request):
                self.assertEqual(gh.publish_bundle('project', digest), 'https://github.com/owner/repo/pull/7')
            puts = [c for c in calls if c[0] == 'PUT']
            self.assertEqual(len(puts), 2)
            self.assertTrue(puts[0][1].endswith('/tests/test_tool.py'))
            self.assertEqual([base64.b64decode(c[2]['content']) for c in puts], [content for _, content in files])
            self.assertTrue(calls[-1][2]['draft'])
            self.assertIn(digest, calls[-1][2]['body'])
            (root / 'tool.py').write_bytes(b'changed')
            with patch.object(gh, 'request') as request_mock:
                with self.assertRaises(ValueError): gh.publish_bundle('project', digest)
                request_mock.assert_not_called()

    def test_bundle_rejects_hidden_binary_and_too_many_files(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            root = Path(directory) / 'project'
            root.mkdir()
            (root / '.secret').write_text('x')
            with self.assertRaises(ValueError): read_bundle('project')
            (root / '.secret').unlink()
            (root / 'bad.bin').write_bytes(b'\xff')
            with self.assertRaises(UnicodeError): read_bundle('project')
            (root / 'bad.bin').unlink()
            for n in range(9): (root / f'{n}.txt').write_text('x')
            with self.assertRaises(ValueError): read_bundle('project')

    def test_homepage_creates_or_updates_only_root_index(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
                site = Path(directory) / 'site'
                site.mkdir()
                content = b'<html>Reviewed</html>'
                (site / 'index.html').write_bytes(content)
                digest = hashlib.sha256(content).hexdigest()
                calls = []
                gh = GitHub('owner/repo', 'secret')
                def request(method, path, payload=None):
                    calls.append((method, path, payload))
                    if path == '': return {'default_branch': 'main'}
                    if path.startswith('/git/ref/heads/'): return {'object': {'sha': 'a' * 40}}
                    if path.startswith('/contents/index.html?'):
                        if not existing: raise GitHubNotFound('missing')
                        return {'type': 'file', 'sha': 'b' * 40}
                    if path == '/pulls': return {'html_url': 'https://github.com/owner/repo/pull/8'}
                    return {}
                with patch.object(gh, 'request', side_effect=request):
                    self.assertTrue(gh.publish_site(digest).endswith('/pull/8'))
                put = next(c for c in calls if c[0] == 'PUT')
                self.assertEqual(put[1], '/contents/index.html')
                self.assertEqual(base64.b64decode(put[2]['content']), content)
                self.assertEqual(put[2].get('sha'), 'b' * 40 if existing else None)
                self.assertTrue(calls[-1][2]['draft'])
                with patch.object(gh, 'request') as api:
                    with self.assertRaises(ValueError): gh.publish_site('0' * 64)
                    api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
