import tempfile
import unittest
import base64
import json
import os
from pathlib import Path
from unittest.mock import patch
from miniagent import tools


class DraftToolsTests(unittest.TestCase):
    def test_workspace_confines_drafts(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            self.assertIn('created', tools.handle('write_draft', {'path': 'notes/idea.txt', 'content': 'hello'}))
            self.assertEqual(json.loads(tools.handle('read_draft', {'path': 'notes/idea.txt'}))['excerpt'], 'hello')
            self.assertIn('notes', tools.handle('list_drafts', {}))
            self.assertIn('failed', tools.handle('write_draft', {'path': '../escape.txt', 'content': 'bad'}))
            self.assertIn('failed', tools.handle('read_draft', {'path': '.env'}))

    def test_paged_editing_and_stale_hash_preserves_file(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            original = 'one\n' + 'é' * 900 + '\nlast\n'
            self.assertIn('created', tools.handle('write_draft', {'path': 'project.py', 'content': original}))
            self.assertIn('failed', tools.handle('write_draft', {'path': 'project.py', 'content': 'overwrite'}))
            page = json.loads(tools.handle('read_draft', {'path': 'project.py'}))
            pages = [page['excerpt']]
            digest = page['sha256']
            while page['next_offset'] is not None:
                page = json.loads(tools.handle('read_draft', {'path': 'project.py', 'offset': page['next_offset']}))
                pages.append(page['excerpt'])
                self.assertEqual(page['sha256'], digest)
            self.assertEqual(''.join(pages), original)
            changed = json.loads(tools.handle('modify_draft', {'path': 'project.py', 'expected_sha256': digest, 'mode': 'replace', 'find': 'last', 'content': 'final'}))
            self.assertNotEqual(changed['sha256'], digest)
            rejected = tools.handle('modify_draft', {'path': 'project.py', 'expected_sha256': digest, 'mode': 'append', 'content': 'stale'})
            self.assertIn('rejected', rejected)
            self.assertEqual((Path(directory) / 'project.py').read_text(encoding='utf-8'), original.replace('last', 'final'))
            self.assertIn('rejected', tools.handle('modify_draft', {'path': 'project.py', 'expected_sha256': changed['sha256'], 'mode': 'replace', 'find': 'é', 'content': 'x'}))

    def test_search_builds_fixed_host_request(self):
        with patch.object(tools, 'fetch_json', return_value={'items': [{'full_name': 'a/b', 'html_url': 'https://github.com/a/b', 'description': 'x'}]}) as fetch:
            self.assertIn('a/b', tools.handle('search_github', {'query': 'small tools'}))
            self.assertTrue(fetch.call_args.args[0].startswith('https://api.github.com/search/repositories?'))

    def test_read_public_github_file_returns_paged_immutable_source(self):
        content = ('source text ' * 150).encode()
        reply = {'type': 'file', 'encoding': 'base64', 'sha': 'a' * 40, 'content': base64.b64encode(content).decode()}
        with patch.object(tools, 'fetch_json', return_value=reply) as fetch:
            result = json.loads(tools.handle('read_github_file', {'repository': 'owner/project', 'path': 'docs/README.md'}))
            self.assertEqual(result['source'], 'https://api.github.com/repos/owner/project/git/blobs/' + 'a' * 40)
            self.assertTrue(result['excerpt'].startswith('source text'))
            self.assertIsNotNone(result['next_offset'])
            self.assertLess(len(json.dumps(result).encode()), 1800)
            self.assertTrue(fetch.call_args.args[0].startswith('https://api.github.com/repos/owner/project/contents/'))
            fetch.reset_mock()
            self.assertIn('failed', tools.handle('read_github_file', {'repository': 'owner/project', 'path': '../private'}))
            self.assertIn('failed', tools.handle('read_github_file', {'repository': 'localhost/../../bad', 'path': 'README.md'}))
            fetch.assert_not_called()

    def test_read_wikipedia_returns_canonical_title_and_offset(self):
        reply = {'query': {'pages': [{'title': 'Agent', 'extract': 'a' * 1000}]}}
        with patch.object(tools, 'fetch_json', return_value=reply):
            result = json.loads(tools.handle('read_wikipedia', {'title': 'agent', 'offset': 50}))
            self.assertEqual(result['source'], 'https://en.wikipedia.org/wiki/Agent')
            self.assertEqual(result['offset'], 50)
            self.assertGreater(result['next_offset'], 50)
            self.assertIn('failed', tools.handle('read_wikipedia', {'title': 'agent', 'offset': -1}))

    def test_build_blog_escapes_untrusted_text_and_confines_output(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            (Path(directory) / 'note.md').write_text('# A discovery\n<script>alert(1)</script>', encoding='utf-8')
            result = tools.handle('build_blog', {'title': 'Mini & Agent', 'description': '<Research>', 'paths': ['note.md']})
            self.assertIn('saved', result)
            page = (Path(directory) / 'site' / 'index.html').read_text(encoding='utf-8')
            self.assertIn('Mini &amp; Agent', page)
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
            self.assertNotIn('<script>', page)
            self.assertIn('A discovery', page)
            self.assertIn('failed', tools.handle('build_blog', {'title': 'x', 'description': 'y', 'paths': ['../secret']}))

    def test_learning_is_persistent_sourced_and_unverified(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            result = tools.handle('remember_learning', {'topic': 'Agent memory', 'lesson': 'Evaluate retrieval quality.', 'sources': ['https://example.org/paper']})
            ident = result.rsplit(' ', 1)[-1]
            matches = json.loads(tools.handle('find_learning', {'query': 'memory retrieval'}))
            self.assertEqual(matches[0]['id'], ident)
            note = json.loads(tools.handle('recall_learning', {'id': ident}))
            self.assertEqual(note['status'], 'unverified')
            self.assertEqual(note['sources'], ['https://example.org/paper'])
            self.assertIn('failed', tools.handle('remember_learning', {'topic': 'x', 'lesson': 'x', 'sources': ['file:///etc/passwd']}))
            self.assertIn('failed', tools.handle('recall_learning', {'id': '../secret'}))

    def test_deterministic_cost_saving_tools(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            # Test check_python_syntax
            good_code = 'def add(a, b):\n    """Sum two numbers."""\n    return a + b\n'
            bad_code = 'def broken(:\n    return\n'
            (Path(directory) / 'good.py').write_text(good_code, encoding='utf-8')
            (Path(directory) / 'bad.py').write_text(bad_code, encoding='utf-8')
            good_res = json.loads(tools.handle('check_python_syntax', {'path': 'good.py'}))
            self.assertEqual(good_res['status'], 'valid_syntax')
            bad_res = json.loads(tools.handle('check_python_syntax', {'path': 'bad.py'}))
            self.assertEqual(bad_res['status'], 'syntax_error')
            self.assertEqual(bad_res['line'], 1)

            # Test grep_draft
            text = 'line one\nfind_me here\nthird line\nfind_me again\n'
            (Path(directory) / 'search.txt').write_text(text, encoding='utf-8')
            grep_res = json.loads(tools.handle('grep_draft', {'path': 'search.txt', 'pattern': r'find_me'}))
            self.assertEqual(grep_res['count'], 2)
            self.assertEqual(grep_res['matches'][0]['line'], 2)
            self.assertEqual(grep_res['matches'][1]['line'], 4)

            # Test python_symbol_outline
            outline_res = json.loads(tools.handle('python_symbol_outline', {'path': 'good.py'}))
            self.assertEqual(len(outline_res['symbols']), 1)
            self.assertEqual(outline_res['symbols'][0]['name'], 'add')
            self.assertEqual(outline_res['symbols'][0]['args'], ['a', 'b'])
            self.assertIn('Sum two numbers', outline_res['symbols'][0]['doc'])

            # Test draft_diff
            (Path(directory) / 'v2.py').write_text(good_code.replace('return a + b', 'return a + b + 1'), encoding='utf-8')
            diff_res = tools.handle('draft_diff', {'old_path': 'good.py', 'new_path': 'v2.py'})
            self.assertIn('-    return a + b', diff_res)
            self.assertIn('+    return a + b + 1', diff_res)

            # Test extract_markdown_toc
            doc = '# Overview\nIntro\n## Section 1\nDetails\n### Subsection\nMore'
            (Path(directory) / 'doc.md').write_text(doc, encoding='utf-8')
            toc_res = json.loads(tools.handle('extract_markdown_toc', {'path': 'doc.md'}))
            self.assertEqual(len(toc_res['headings']), 3)
            self.assertEqual(toc_res['headings'][0]['heading'], 'Overview')
            self.assertEqual(toc_res['headings'][0]['level'], 1)
            self.assertEqual(toc_res['headings'][1]['heading'], 'Section 1')
            self.assertEqual(toc_res['headings'][1]['level'], 2)

            # Test check_url_validity
            with patch('miniagent.tools.build_opener') as opener:
                mock_resp = unittest.mock.MagicMock(status=200)
                mock_resp.__enter__.return_value = mock_resp
                opener.return_value.open.return_value = mock_resp
                url_res = json.loads(tools.handle('check_url_validity', {'url': 'https://example.com'}))
                self.assertTrue(url_res['valid'])
                self.assertEqual(url_res['http_code'], 200)

            # Test python_import_check
            code_imports = 'import sys\nimport os\nimport nonexistent_pkg\n'
            (Path(directory) / 'imports.py').write_text(code_imports, encoding='utf-8')
            imp_res = json.loads(tools.handle('python_import_check', {'path': 'imports.py'}))
            self.assertIn('nonexistent_pkg', imp_res['third_party_or_missing'])
            self.assertNotIn('sys', imp_res['third_party_or_missing'])

            # Test draft_stats
            stats_res = json.loads(tools.handle('draft_stats', {'path': 'imports.py'}))
            self.assertEqual(stats_res['lines'], 3)
            self.assertGreater(stats_res['bytes'], 10)
            self.assertIn('sha256', stats_res)

            # Test strip_comments_and_docstrings
            code_with_comments = '# comment\ndef foo():\n    # inside comment\n    return 42\n'
            (Path(directory) / 'comments.py').write_text(code_with_comments, encoding='utf-8')
            stripped = tools.handle('strip_comments_and_docstrings', {'path': 'comments.py'})
            self.assertNotIn('# comment', stripped)
            self.assertIn('def foo():', stripped)

            # Test json_schema_validator
            val_ok = json.loads(tools.handle('json_schema_validator', {'text': '{"a": 1, "b": 2}', 'required_keys': ['a', 'b']}))
            self.assertTrue(val_ok['valid'])
            val_bad = json.loads(tools.handle('json_schema_validator', {'text': '{"a": 1}', 'required_keys': ['a', 'b']}))
            self.assertFalse(val_bad['valid'])
            self.assertEqual(val_bad['missing_keys'], ['b'])

    def test_tinyfish_web_search_and_fetch(self):
        with tempfile.TemporaryDirectory() as td, patch.object(tools, 'ROOT', Path(td).resolve()), patch.dict(os.environ, {'MINIAGENT_DB': os.path.join(td, 'cache.db')}):
            # When TINYFISH_API_KEY is not configured
            with patch.dict(os.environ, {'TINYFISH_API_KEY': ''}):
                res_search = json.loads(tools.handle('web_search', {'query': 'python release'}))
                self.assertIn('not configured', res_search.get('error', ''))
                res_fetch = json.loads(tools.handle('web_fetch', {'url': 'https://python.org'}))
                self.assertIn('not configured', res_fetch.get('error', ''))

            # When TINYFISH_API_KEY is configured
            with patch.dict(os.environ, {'TINYFISH_API_KEY': 'tf_test_key_123'}):
                # Test web_search
                mock_search_data = {
                    'query': 'python 3.12',
                    'results': [
                        {'title': 'Python 3.12 Release Notes', 'url': 'https://docs.python.org/3.12/', 'snippet': 'New features in Python 3.12.'},
                        {'title': 'YouTube Video on 3.12', 'url': 'https://www.youtube.com/watch?v=123', 'snippet': 'Watch video.'},
                        {'title': 'PEP 695 Type Parameter Syntax', 'url': 'https://peps.python.org/pep-0695/', 'snippet': 'Type parameters syntax.'}
                    ]
                }
                with patch('miniagent.tools.build_opener') as opener:
                    mock_resp = unittest.mock.MagicMock()
                    mock_resp.read.return_value = json.dumps(mock_search_data).encode('utf-8')
                    mock_resp.__enter__.return_value = mock_resp
                    opener.return_value.open.return_value = mock_resp

                    res = json.loads(tools.handle('web_search', {'query': 'python 3.12'}))
                    self.assertEqual(res['query'], 'python 3.12')
                    # YouTube was filtered out by LOW_SIGNAL_DOMAINS
                    self.assertEqual(res['count'], 2)
                    urls = [r['url'] for r in res['results']]
                    self.assertIn('https://docs.python.org/3.12/', urls)
                    self.assertNotIn('https://www.youtube.com/watch?v=123', urls)

                    # Verify request header and URL
                    call_args = opener.return_value.open.call_args[0]
                    req = call_args[0]
                    self.assertEqual(req.headers.get('X-api-key'), 'tf_test_key_123')
                    self.assertTrue(req.full_url.startswith('https://api.search.tinyfish.ai?'))

                # Test web_fetch
                mock_fetch_data = {
                    'results': [
                        {
                            'url': 'https://docs.python.org/3.12/',
                            'title': 'Python 3.12 Documentation',
                            'text': '# Python 3.12\n\nWelcome to Python 3.12 release notes.' + ' Details...' * 100,
                            'format': 'markdown'
                        }
                    ],
                    'errors': []
                }
                with patch('miniagent.tools.build_opener') as opener:
                    mock_resp = unittest.mock.MagicMock()
                    mock_resp.read.return_value = json.dumps(mock_fetch_data).encode('utf-8')
                    mock_resp.__enter__.return_value = mock_resp
                    opener.return_value.open.return_value = mock_resp

                    res = json.loads(tools.handle('web_fetch', {'url': 'https://docs.python.org/3.12/'}))
                    self.assertEqual(res['source'], 'https://docs.python.org/3.12/')
                    self.assertEqual(res['title'], 'Python 3.12 Documentation')
                    self.assertTrue(res['excerpt'].startswith('# Python 3.12'))
                    self.assertIsNotNone(res['next_offset'])

                    call_args = opener.return_value.open.call_args[0]
                    req = call_args[0]
                    self.assertEqual(req.headers.get('X-api-key'), 'tf_test_key_123')
                    self.assertEqual(req.get_method(), 'POST')

    def test_task_history_cost_estimator_and_ast_linter(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory, patch.object(tools, 'ROOT', Path(directory).resolve()):
            # Test estimate_token_cost
            cost_res = json.loads(tools.handle('estimate_token_cost', {'text': 'a' * 400}))
            self.assertEqual(cost_res['bytes'], 400)
            self.assertEqual(cost_res['estimated_tokens'], 100)
            self.assertGreater(cost_res['input_cost_usd'], 0)

            # Test ast_linter
            code_with_bare_except = "try:\n    x = 1\nexcept:\n    pass\n"
            (Path(directory) / 'lint_target.py').write_text(code_with_bare_except, encoding='utf-8')
            linter_res = json.loads(tools.handle('ast_linter', {'path': 'lint_target.py'}))
            self.assertEqual(linter_res['status'], 'warnings_found')
            types = [iss['type'] for iss in linter_res['issues']]
            self.assertIn('bare_except', types)

            # Test inspect_task_history
            from miniagent.queue import Queue
            db_p = os.path.join(directory, 'test.db')
            with patch.dict(os.environ, {'MINIAGENT_DB': db_p}):
                q = Queue(db_p)
                jid = q.ingest(1, 'task history tool test')
                q.claim()
                q.finish(jid, 'success', duration_ms=800, tool_calls_count=2)
                hist_res = json.loads(tools.handle('inspect_task_history', {'limit': 5}))
                self.assertEqual(len(hist_res), 1)
                self.assertEqual(hist_res[0]['job_id'], jid)
                self.assertEqual(hist_res[0]['state'], 'done')
                self.assertEqual(hist_res[0]['duration_ms'], 800)


if __name__ == '__main__':
    unittest.main()
