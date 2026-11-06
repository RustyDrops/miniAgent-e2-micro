"""Deterministic AST-based unittest scaffold generator for Python drafts."""
import ast


def generate_test_scaffold(source_code: str, module_name: str = 'subject') -> str:
    """Analyze Python AST and produce a runnable unittest.TestCase scaffold."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        return f'# Syntax error in source code: {exc}'

    test_methods = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name
            args = [a.arg for a in node.args.args if a.arg != 'self']
            args_str = ', '.join(args)
            test_methods.append(f'''    def test_{func_name}_basic(self):
        # Test {func_name}({args_str})
        result = {module_name}.{func_name}({', '.join(['None'] * len(args)) if args else ''})
        self.assertIsNotNone(result)
''')
        elif isinstance(node, ast.ClassDef):
            class_name = node.name
            test_methods.append(f'''    def test_{class_name}_instantiation(self):
        instance = {module_name}.{class_name}()
        self.assertIsInstance(instance, {module_name}.{class_name})
''')

    if not test_methods:
        test_methods.append('''    def test_module_imports(self):
        self.assertTrue(hasattr(subject, '__name__'))
''')

    body = '\n'.join(test_methods)
    return f'''import unittest
import {module_name}


class Test{module_name.capitalize()}(unittest.TestCase):
{body}

if __name__ == '__main__':
    unittest.main()
'''
