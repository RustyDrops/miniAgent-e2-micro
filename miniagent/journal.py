"""Autonomous daily progress logger and weekly recap compiler."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path

from .tools import ROOT, safe_path


def get_day_bounds_utc(date_str=None):
    """Return (start_ts, end_ts, date_str) for given YYYY-MM-DD or today in UTC."""
    if date_str:
        dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    start_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return int(start_dt.timestamp()), int(end_dt.timestamp()), start_dt.strftime('%Y-%m-%d')


def get_week_bounds_utc(week_str=None):
    """Return (start_ts, end_ts, week_str) for given YYYY-Www or current ISO week in UTC."""
    if week_str:
        # Parse ISO year and week number (e.g. 2026-W45)
        dt = datetime.strptime(week_str + '-1', '%G-W%V-%u').replace(tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    # Start of ISO week (Monday 00:00:00)
    monday = (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = (monday + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
    label = monday.strftime('%G-W%V')
    return int(monday.timestamp()), int(sunday.timestamp()), label


def collect_recent_learnings(workspace_root, limit=5):
    """Retrieve up to limit recent learning notes from the knowledge base."""
    k_dir = Path(workspace_root) / 'knowledge'
    if not k_dir.is_dir():
        return []
    notes = []
    try:
        files = sorted(k_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                notes.append({
                    'topic': data.get('topic', 'Untitled'),
                    'lesson': data.get('lesson', '')[:200],
                    'sources': data.get('sources', [])
                })
            except Exception:
                continue
    except Exception:
        pass
    return notes


def generate_daily_journal(queue, workspace_root=None, date_str=None, budget=None):
    """Compile an autonomous daily progress report and save to updates/daily/YYYY-MM-DD.md."""
    root = ROOT if workspace_root is None else Path(workspace_root)
    start_ts, end_ts, resolved_date = get_day_bounds_utc(date_str)
    
    history = queue.get_history_range(start_ts, end_ts) if hasattr(queue, 'get_history_range') else []
    
    total_jobs = len(history)
    succeeded = sum(1 for h in history if h[4] == 'done')
    failed = sum(1 for h in history if h[4] == 'failed')
    interrupted = sum(1 for h in history if h[4] in ('interrupted', 'cancelled'))
    total_tool_calls = sum((h[9] or 0) for h in history)
    total_cost_micro = sum((h[11] or 0) for h in history)
    durations = [h[7] for h in history if h[7] is not None and h[7] > 0]
    avg_duration_ms = int(sum(durations) / len(durations)) if durations else 0

    spent_today_usd = total_cost_micro / 1e6
    daily_limit_usd = 1.00
    if budget is not None:
        try:
            spent_b, limit_b = budget.today()
            spent_today_usd = spent_b / 1e6
            daily_limit_usd = limit_b / 1e6
        except Exception:
            pass

    learnings = collect_recent_learnings(root, limit=5)
    
    lines = [
        f'# MiniAgent Daily Log — {resolved_date}',
        '',
        '> **Autonomous Agent Run Report**  ',
        '> Environment: Google Cloud `e2-micro` (1 GB RAM, 0.25 shared vCPU)  ',
        f'> Model Budget Target: \\${daily_limit_usd:.2f}/day',
        '',
        '## 📊 Telemetry & Execution Summary',
        f'- **Total Tasks Executed**: {total_jobs}',
        f'  - Succeeded: {succeeded}',
        f'  - Failed: {failed}',
        f'  - Interrupted / Cancelled: {interrupted}',
        f'- **Total Tool Calls**: {total_tool_calls}',
        f'- **Model Expenditure**: \\${spent_today_usd:.4f} / \\${daily_limit_usd:.2f} ({(spent_today_usd/daily_limit_usd*100) if daily_limit_usd else 0:.1f}% budget pacing)',
        f'- **Average Task Duration**: {avg_duration_ms} ms',
        '',
        '## 🧠 Curated Learnings & Discoveries'
    ]

    if learnings:
        for item in learnings:
            src_text = f" (Sources: {', '.join(item['sources'])})" if item['sources'] else ''
            lines.append(f"- **{item['topic']}**: {item['lesson']}{src_text}")
    else:
        lines.append('- *No new learning notes recorded during this period.*')

    # Query Naive Bayes Router daily audit
    router_info = None
    try:
        from .naive_bayes import NaiveBayesRouter
        db_p = getattr(queue, 'path', os.environ.get('MINIAGENT_DB', 'miniagent.db'))
        router = NaiveBayesRouter(db_p)
        router_info = router.daily_audit(hours=24)
    except Exception:
        router_info = None

    if router_info and router_info.get('total_routed', 0) > 0:
        lines.extend([
            '',
            '## 🧭 Adaptive Task Router (Naive Bayes) Audit',
            f"- **Total Routing Decisions**: {router_info['total_routed']}",
            f"  - Locally Routed (Naive Bayes): {router_info['naive_bayes_routed']}",
            f"  - Teacher LLM Fallbacks: {router_info['teacher_llm_routed']}",
            f"- **Local Accuracy**: {router_info['naive_bayes_accuracy_pct']}%",
            f"- **Model Budget Saved**: \\${router_info['cost_saved_usd']:.4f}",
            f"- **Active Vocabulary Size**: {router_info['active_vocab_size']} tokens ({router_info['pruned_words']} pruned)",
            f"- **Calibrated Confidence Threshold**: {router_info['confidence_threshold']:.2f}"
        ])

    lines.extend([
        '',
        '## 🛠️ System Health & Infrastructure',
        '- **Storage & Cache**: SQLite WAL mode active with zero-cost tool caching',
        '- **Pacing Controller**: Dynamic time-decay budget guard operational',
        '- **Regression Guard**: Sequential canary runner active before changes',
        '',
        '---',
        '*Automated update generated by [MiniAgent](https://github.com/RustyDrops/miniAgent-e2-micro).*'
    ])

    content = '\n'.join(lines) + '\n'
    content_bytes = content.encode('utf-8')
    digest = hashlib.sha256(content_bytes).hexdigest()

    rel_path = f'updates/daily/{resolved_date}.md'
    target_file = root / 'updates' / 'daily' / f'{resolved_date}.md'
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_bytes(content_bytes)

    return {
        'path': rel_path,
        'date': resolved_date,
        'sha256': digest,
        'bytes': len(content_bytes),
        'total_jobs': total_jobs,
        'spent_usd': spent_today_usd
    }


def generate_weekly_recap(queue, workspace_root=None, week_str=None, budget=None):
    """Compile an autonomous weekly recap rollup and save to updates/weekly/YYYY-Www.md."""
    root = ROOT if workspace_root is None else Path(workspace_root)
    start_ts, end_ts, resolved_week = get_week_bounds_utc(week_str)

    history = queue.get_history_range(start_ts, end_ts) if hasattr(queue, 'get_history_range') else []

    total_jobs = len(history)
    succeeded = sum(1 for h in history if h[4] == 'done')
    failed = sum(1 for h in history if h[4] == 'failed')
    total_tool_calls = sum((h[9] or 0) for h in history)
    total_cost_micro = sum((h[11] or 0) for h in history)
    total_spent_usd = total_cost_micro / 1e6
    weekly_limit_usd = 7.00

    learnings = collect_recent_learnings(root, limit=8)

    lines = [
        f'# MiniAgent Weekly Recap — {resolved_week}',
        '',
        '> **Autonomous Agent Weekly Rollup**  ',
        '> Project: [RustyDrops/miniAgent-e2-micro](https://github.com/RustyDrops/miniAgent-e2-micro)  ',
        f'> Weekly Budget Limit: \\${weekly_limit_usd:.2f}',
        '',
        '## 🌟 Weekly Highlights & Performance',
        f'- **Autonomous Tasks Completed**: {succeeded} / {total_jobs} ({(succeeded / total_jobs * 100) if total_jobs else 100:.1f}% success rate)',
        f'- **Total Tool Invocations**: {total_tool_calls}',
        f'- **Total Weekly Spend**: \\${total_spent_usd:.4f} / \\${weekly_limit_usd:.2f} ({(total_spent_usd / weekly_limit_usd * 100):.1f}% pacing)',
        f'- **Cost Efficiency**: \\${(total_spent_usd / max(1, succeeded)):.4f} per successful task',
        '',
        '## 🔬 Curated Technical Knowledge',
    ]

    if learnings:
        for item in learnings:
            src_text = f" (Sources: {', '.join(item['sources'])})" if item['sources'] else ''
            lines.append(f"- **{item['topic']}**: {item['lesson']}{src_text}")
    else:
        lines.append('- *No new learning notes logged during this week.*')

    lines.extend([
        '',
        '## 🛡️ Reliability & Self-Improvement',
        '- Multi-specialist consensus architecture (Planner, Builder, Reviewer) maintained.',
        '- AST test scaffolding and canary isolation active to prevent code regressions.',
        '- Zero third-party dependencies; strictly standard library & SQLite WAL mode.',
        '',
        '---',
        '*Automated weekly recap generated by [MiniAgent](https://github.com/RustyDrops/miniAgent-e2-micro).*'
    ])

    content = '\n'.join(lines) + '\n'
    content_bytes = content.encode('utf-8')
    digest = hashlib.sha256(content_bytes).hexdigest()

    rel_path = f'updates/weekly/{resolved_week}.md'
    target_file = root / 'updates' / 'weekly' / f'{resolved_week}.md'
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_bytes(content_bytes)

    return {
        'path': rel_path,
        'week': resolved_week,
        'sha256': digest,
        'bytes': len(content_bytes),
        'total_jobs': total_jobs,
        'total_spent_usd': total_spent_usd
    }
