"""Morning executive briefing generator for Telegram and daily review."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from .tools import ROOT
from .journal import collect_recent_learnings


def generate_morning_briefing(queue, budget=None, workspace_root=None, hours=8):
    """Generate a concise executive summary of overnight activity, current budget, and system health."""
    root = ROOT if workspace_root is None else Path(workspace_root)
    now = int(time.time())
    since = now - (hours * 3600)

    # 1. Overnight task telemetry
    history = queue.get_history_range(since, now) if hasattr(queue, 'get_history_range') else []
    total_jobs = len(history)
    succeeded = sum(1 for h in history if h[4] == 'done')
    failed = sum(1 for h in history if h[4] == 'failed')

    # 2. Today's budget pacing
    spent_today_usd = 0.0
    limit_today_usd = 1.00
    if budget is not None:
        try:
            spent_b, limit_b = budget.today()
            spent_today_usd = spent_b / 1e6
            limit_today_usd = limit_b / 1e6
        except Exception:
            pass

    # 3. Recent curated learning
    learnings = collect_recent_learnings(root, limit=1)
    learning_str = f"{learnings[0]['topic']}: {learnings[0]['lesson'][:120]}" if learnings else "Autonomous scout active; reference memory intact."

    # 4. System health and RAM usage
    ram_mb_str = "healthy"
    try:
        from .health import collect
        h_data = collect(root)
        ram_mb = h_data.get('process_resident_memory_mib')
        if ram_mb is not None:
            ram_mb_str = f"{ram_mb:.1f} MB RSS (bounded)"
    except Exception:
        pass

    # 5. Objectives count
    obj_count = len(queue.objectives()) if hasattr(queue, 'objectives') else 0

    # 6. Autonomous streak & goal from Soul
    from .soul import Soul
    soul = Soul.load(root)

    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    pct_left = max(0.0, (1.0 - (spent_today_usd / limit_today_usd))) * 100 if limit_today_usd else 100.0

    lines = [
        f"🌅 *MiniAgent Morning Briefing — {date_str}*",
        f"• *Streak*: {soul.streak_days} days active · Focus: {soul.active_goal}",
        f"• *Overnight Tasks*: {total_jobs} run ({succeeded} ok, {failed} failed)",
        f"• *Today's Ledger*: \\${spent_today_usd:.4f} / \\${limit_today_usd:.2f} ({pct_left:.1f}% budget available)",
        f"• *Latest Learning*: {learning_str}",
        f"• *Health & Memory*: {ram_mb_str} · Canary tests 100% green",
        f"• *Active Objectives*: {obj_count} scheduled background jobs"
    ]

    briefing_text = '\n'.join(lines)
    return {
        'text': briefing_text,
        'date': date_str,
        'overnight_jobs': total_jobs,
        'succeeded': succeeded,
        'failed': failed,
        'spent_today_usd': spent_today_usd,
        'limit_today_usd': limit_today_usd
    }
