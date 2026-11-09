"""Autonomous identity, goal alignment, and continuous streak tracker inspired by Picoling."""

from datetime import datetime, date, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Optional

from .tools import ROOT


class Soul:
    """Manages agent identity, active autonomous objectives, and survival streak telemetry."""

    def __init__(
        self,
        name: str = "MiniAgent",
        active_goal: str = "Autonomously self-improve on a $1/day budget.",
        streak_days: int = 1,
        last_active_date: Optional[str] = None,
        total_tasks_completed: int = 0,
        total_usd_spent: float = 0.0,
        total_learnings: int = 0,
        created_at: Optional[str] = None,
    ):
        self.name = name
        self.active_goal = active_goal
        self.streak_days = max(0, streak_days)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.last_active_date = last_active_date or today_str
        self.total_tasks_completed = max(0, total_tasks_completed)
        self.total_usd_spent = max(0.0, float(total_usd_spent))
        self.total_learnings = max(0, total_learnings)
        self.created_at = created_at or today_str

    @classmethod
    def load(cls, workspace_root: Optional[Path] = None) -> "Soul":
        """Load persistent soul state from workspace soul.json or initialize defaults."""
        root = ROOT if workspace_root is None else Path(workspace_root)
        soul_file = root / "soul.json"
        if soul_file.is_file():
            try:
                data = json.loads(soul_file.read_text(encoding="utf-8"))
                return cls(
                    name=data.get("name", "MiniAgent"),
                    active_goal=data.get("active_goal", "Autonomously self-improve on a $1/day budget."),
                    streak_days=int(data.get("streak_days", 1)),
                    last_active_date=data.get("last_active_date"),
                    total_tasks_completed=int(data.get("total_tasks_completed", 0)),
                    total_usd_spent=float(data.get("total_usd_spent", 0.0)),
                    total_learnings=int(data.get("total_learnings", 0)),
                    created_at=data.get("created_at"),
                )
            except Exception:
                pass
        return cls()

    def save(self, workspace_root: Optional[Path] = None) -> None:
        """Persist soul identity state to disk atomically."""
        root = ROOT if workspace_root is None else Path(workspace_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
            soul_file = root / "soul.json"
            temp_file = root / "soul.json.tmp"
            temp_file.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
            temp_file.replace(soul_file)
        except OSError:
            pass

    def record_daily_activity(self, date_str: Optional[str] = None, budget_breached: bool = False) -> dict:
        """Evaluate streak progression based on consecutive calendar activity and budget discipline."""
        today = date.fromisoformat(date_str) if date_str else datetime.now(timezone.utc).date()
        today_str = today.isoformat()

        if budget_breached:
            self.streak_days = 0
            self.last_active_date = today_str
            return self.as_dict()

        if self.last_active_date:
            try:
                last_date = date.fromisoformat(self.last_active_date)
                delta_days = (today - last_date).days
                if delta_days == 1:
                    self.streak_days += 1
                elif delta_days > 1:
                    self.streak_days = 1
                # If delta_days == 0 (same day), maintain streak
            except ValueError:
                self.streak_days = 1
        else:
            self.streak_days = 1

        self.last_active_date = today_str
        return self.as_dict()

    def record_task_success(self, cost_usd: float = 0.0) -> None:
        """Increment cumulative successful task counter and spent ledger."""
        self.total_tasks_completed += 1
        if cost_usd > 0:
            self.total_usd_spent = round(self.total_usd_spent + float(cost_usd), 6)

    def set_goal(self, goal: str) -> None:
        """Update current autonomous focus objective."""
        if goal and isinstance(goal, str):
            self.active_goal = goal.strip()[:200]

    def as_dict(self) -> dict:
        """Serialize soul state."""
        return {
            "name": self.name,
            "active_goal": self.active_goal,
            "streak_days": self.streak_days,
            "last_active_date": self.last_active_date,
            "total_tasks_completed": self.total_tasks_completed,
            "total_usd_spent": round(self.total_usd_spent, 4),
            "total_learnings": self.total_learnings,
            "created_at": self.created_at,
        }
