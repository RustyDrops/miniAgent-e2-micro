import os
import tempfile
import unittest
from pathlib import Path

from miniagent.test_generator import generate_test_scaffold
from miniagent.diagram import generate_mermaid_diagram
from miniagent.canary import run_canary_tests
from miniagent.knowledge import remember, groom, recall


class ExtensionsTests(unittest.TestCase):
    def test_generate_test_scaffold(self):
        source = 'def calculate(x, y):\n    return x + y\n\nclass Runner:\n    pass\n'
        scaffold = generate_test_scaffold(source, 'math_mod')
        self.assertIn('import unittest', scaffold)
        self.assertIn('import math_mod', scaffold)
        self.assertIn('def test_calculate_basic', scaffold)
        self.assertIn('def test_Runner_instantiation', scaffold)

    def test_generate_mermaid_diagram(self):
        diagram = generate_mermaid_diagram(None, None)
        self.assertTrue(diagram.startswith('```mermaid'))
        self.assertIn('flowchart TD', diagram)
        self.assertIn('Researcher', diagram)
        self.assertIn('Builder', diagram)
        self.assertIn('Reviewer', diagram)

    def test_run_canary_tests_invokes_runner(self):
        result = run_canary_tests(timeout_seconds=10)
        self.assertIn('passed', result)
        self.assertIn('status', result)

    def test_knowledge_groom_removes_duplicates(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as directory:
            root = Path(directory).resolve()
            # Remember note 1
            id1 = remember(root, 'Topic Alpha', 'Lesson 1', ['https://example.com/1'])
            # Remember duplicate topic note 2
            id2 = remember(root, 'Topic Alpha', 'Lesson 2 duplicate', ['https://example.com/2'])
            # Remember unique topic note 3
            id3 = remember(root, 'Topic Beta', 'Lesson 3', ['https://example.com/3'])

            res = groom(root)
            self.assertEqual(res['pruned'], 1)
            self.assertEqual(res['remaining'], 2)
            matches_alpha = [f for f in (root / 'knowledge').glob('*.json') if f.name in (f'{id1}.json', f'{id2}.json')]
            self.assertEqual(len(matches_alpha), 1)
            self.assertEqual(recall(root, id3)['topic'], 'Topic Beta')


if __name__ == '__main__':
    unittest.main()
