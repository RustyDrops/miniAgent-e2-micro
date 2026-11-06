"""Post-mortem analysis for task executions, errors, and failure patterns."""
from collections import Counter
from datetime import datetime, timezone


def generate_postmortem_report(queue, limit: int = 50) -> str:
    """Analyze recent task history from SQLite and produce a structured diagnostic report."""
    history = queue.get_history(limit=limit)
    if not history:
        return 'No task history recorded yet. Run tasks to build historical diagnostics.'

    total = len(history)
    states = Counter(h[4] for h in history)
    failures = [h for h in history if h[4] in ('failed', 'interrupted', 'cancelled')]
    error_types = Counter(h[10] for h in failures if h[10])

    completed = states.get('done', 0)
    success_rate = (completed / total) * 100 if total > 0 else 0.0

    durations = [h[7] for h in history if h[7] is not None and h[7] > 0]
    avg_duration_sec = (sum(durations) / len(durations) / 1000.0) if durations else 0.0

    tool_counts = [h[9] for h in history if h[9] is not None]
    avg_tools = (sum(tool_counts) / len(tool_counts)) if tool_counts else 0.0

    lines = [
        '# MiniAgent Task Execution Post-Mortem',
        f'Analyzed **{total}** recorded task(s):',
        f'- **Success Rate**: {completed}/{total} ({success_rate:.1f}%)',
        f'- **Average Task Duration**: {avg_duration_sec:.2f}s',
        f'- **Average Tool Invocations**: {avg_tools:.1f} per task',
        '',
        '## Execution State Breakdown',
    ]
    for state, count in states.most_common():
        pct = (count / total) * 100
        lines.append(f'- `{state}`: {count} ({pct:.1f}%)')

    if error_types:
        lines.append('')
        lines.append('## Failure Categories')
        for err, count in error_types.most_common():
            lines.append(f'- `{err}`: {count}')

    lines.append('')
    lines.append('## Recommendations')
    if error_types.get('BudgetExceeded', 0) > 0:
        lines.append('- **Budget Exhaustion**: Tasks hit the daily USD ceiling. Consider lowering `MINIAGENT_MAX_TOOL_ROUNDS` or increasing `MINIAGENT_DAILY_USD`.')
    if error_types.get('ProviderError', 0) > 0:
        lines.append('- **Provider Failures**: 429 rate limits or upstream timeouts observed. Verify model quotas and consider setting `MINIAGENT_MAX_RETRIES=2`.')
    if error_types.get('InterruptedByRestart', 0) > 0:
        lines.append('- **Service Restarts**: Tasks interrupted by restart. Check systemd service memory limits and VM OOM killer logs.')
    if not failures:
        lines.append('- **All Systems Healthy**: No recent task failures detected.')

    if failures:
        lines.append('')
        lines.append('## Recent Failed / Interrupted Tasks')
        for f in failures[:5]:
            job_id, task, orig, st, dur, err = f[1], f[2][:60], f[3], f[4], f[7], f[10]
            dur_str = f'{dur/1000:.1f}s' if dur else 'N/A'
            lines.append(f'- Job #{job_id} (`{st}`): "{task}" | Error: `{err}` ({dur_str})')

    return '\n'.join(lines)
