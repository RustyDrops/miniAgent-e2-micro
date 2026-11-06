import unittest
from miniagent.compactor import compact_text, compact_messages


class CompactorTests(unittest.TestCase):
    def test_compact_text_removes_preamble_and_collapses_whitespace(self):
        raw = "Certainly! Here is the code you requested:\n\n\n\ndef add(a, b):\n    return a + b\n\n\n"
        compacted = compact_text(raw)
        self.assertNotIn("Certainly!", compacted)
        self.assertIn("def add(a, b):", compacted)
        self.assertNotIn("\n\n\n", compacted)

    def test_compact_messages(self):
        msgs = [
            {'role': 'system', 'content': 'Instructions here.\n\n\nMore info.'},
            {'role': 'user', 'content': 'Sure, here is the answer: do this.'}
        ]
        compacted = compact_messages(msgs)
        self.assertEqual(len(compacted), 2)
        self.assertNotIn("\n\n\n", compacted[0]['content'])
        self.assertFalse(compacted[1]['content'].startswith("Sure, here is"))


if __name__ == '__main__':
    unittest.main()
