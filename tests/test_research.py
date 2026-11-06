import json
import unittest
from unittest.mock import patch

from miniagent import research, tools

FEED = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2301.00001v1</id><title>A useful paper</title>
<published>2023-01-01T00:00:00Z</published><summary>First sentence. Second sentence.</summary></entry>
</feed>'''


class ResearchTests(unittest.TestCase):
    def test_atom_search_normalizes_links_and_uses_fixed_query(self):
        papers = research.parse_feed(FEED)
        self.assertEqual(papers[0]['url'], 'https://arxiv.org/abs/2301.00001v1')
        with patch.object(research, 'fetch', return_value=papers) as fetch:
            result = json.loads(tools.handle('search_arxiv', {'query': 'agent memory'}))
            self.assertEqual(result[0]['title'], 'A useful paper')
            self.assertEqual(fetch.call_args.args[0]['search_query'], 'all:agent AND all:memory')
            self.assertLess(len(json.dumps(result).encode()), 1800)

    def test_abstract_paging_and_identifier_validation(self):
        paper = {'id': '2301.00001v1', 'title': 'Paper', 'abstract': 'abc ' * 300,
                 'published': '2023-01-01', 'url': 'https://arxiv.org/abs/2301.00001v1'}
        with patch.object(research, 'fetch', side_effect=lambda params: [dict(paper)]) as fetch:
            first = json.loads(tools.handle('read_arxiv_abstract', {'id': '2301.00001'}))
            second = json.loads(tools.handle('read_arxiv_abstract', {'id': '2301.00001', 'offset': first['next_offset']}))
            self.assertEqual(first['abstract_excerpt'] + second['abstract_excerpt'], paper['abstract'][:800])
            fetch.reset_mock()
            self.assertIn('failed', tools.handle('read_arxiv_abstract', {'id': 'http://localhost/private'}))
            fetch.assert_not_called()

    def test_rejects_dtd_and_oversized_feed(self):
        with self.assertRaises(ValueError): research.parse_feed(b'<!DOCTYPE x [<!ENTITY e "x">]><x/>')
        with self.assertRaises(ValueError): research.parse_feed(b'x' * 200001)


if __name__ == '__main__': unittest.main()
