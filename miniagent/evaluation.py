"""Small opt-in planner routing evaluation. It never executes fixture tasks."""
import time


CASES = (
    ('greeting', 'Say hello in one sentence.', ('reviewer',)),
    ('explain', 'Explain recursion from existing knowledge; do not research or create files.', ('reviewer',)),
    ('paper', 'Research a recent paper on agent memory and cite sources; do not create files.', ('researcher', 'reviewer')),
    ('docs', 'Find official documentation about Python context managers; do not write code.', ('researcher', 'reviewer')),
    ('create', 'Create a Python draft that prints hello; no research is needed.', ('builder', 'reviewer')),
    ('edit', 'Edit the existing draft notes.txt to correct a typo; do not research.', ('builder', 'reviewer')),
    ('research_build', 'Research a small agent optimization and create a Python draft based on it.', ('researcher', 'builder', 'reviewer')),
    ('research_test', 'Investigate a suitable design for a small cache, then draft the code and tests.', ('researcher', 'builder', 'reviewer')),
)


def evaluate_planner(agent, budget):
    """Use only the planner; no role execution or workspace tool is invoked."""
    before, limit = budget.today()
    start = time.monotonic()
    results = []
    error = None
    for name, prompt, expected in CASES:
        try:
            actual, fallback = agent.plan_roles(prompt)
        except Exception as exc:
            # Exception text may contain provider details or credentials.
            error = type(exc).__name__
            break
        expected_set, actual_set = set(expected), set(actual)
        results.append({'case': name, 'expected': list(expected), 'actual': list(actual),
                        'missing': sorted(expected_set - actual_set), 'extra': sorted(actual_set - expected_set),
                        'fallback': bool(fallback)})
    after, _ = budget.today()
    return {'cases': results, 'planned': len(CASES), 'completed': len(results),
            'exact': sum(row['expected'] == row['actual'] for row in results),
            'missing_cases': sum(bool(row['missing']) for row in results),
            'fallbacks': sum(row['fallback'] for row in results),
            'ledger_change_microdollars': after - before, 'ledger_limit_microdollars': limit,
            'elapsed_seconds': round(time.monotonic() - start, 2), 'error': error}
