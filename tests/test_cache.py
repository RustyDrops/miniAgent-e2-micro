import os
import tempfile
import unittest
from contextlib import closing

from miniagent.cache import ToolCache


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getcwd())
        self.db_path = os.path.join(self.tmp.name, 'cache_test.db')
        self.cache = ToolCache(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_put_get_and_expiration(self):
        # Initial get is None
        self.assertIsNone(self.cache.get('check_python_syntax', {'path': 'test.py'}, target_sha='abc123'))

        # Put item
        self.cache.put('check_python_syntax', {'path': 'test.py'}, '{"status": "valid"}', ttl_seconds=60, target_sha='abc123')
        self.assertEqual(self.cache.get('check_python_syntax', {'path': 'test.py'}, target_sha='abc123'), '{"status": "valid"}')

        # Different target SHA yields miss
        self.assertIsNone(self.cache.get('check_python_syntax', {'path': 'test.py'}, target_sha='xyz999'))

        # Different tool yields miss
        self.assertIsNone(self.cache.get('ast_linter', {'path': 'test.py'}, target_sha='abc123'))

    def test_clear_expired(self):
        # Put item with 0 ttl (already expired relative to future)
        self.cache.put('tool', {'a': 1}, 'val', ttl_seconds=60)
        # Artificially expire
        with closing(self.cache._connect()) as db:
            db.execute('UPDATE tool_cache SET expires_at=?', (100,))
        pruned = self.cache.clear_expired()
        self.assertEqual(pruned, 1)
        self.assertIsNone(self.cache.get('tool', {'a': 1}))


if __name__ == '__main__':
    unittest.main()
