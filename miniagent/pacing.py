"""Time-decay dynamic budget pacing controller for e2-micro."""
from datetime import datetime, timezone


def calculate_pacing(spent_microdollars: int, daily_limit_microdollars: int, current_hour_utc: float | None = None) -> dict:
    """Evaluate budget pacing according to time-of-day progression in UTC."""
    if current_hour_utc is None:
        now = datetime.now(timezone.utc)
        current_hour_utc = now.hour + (now.minute / 60.0)

    # Progress fraction throughout the 24h day (at least 1/24th)
    fraction = min(1.0, max(0.0416, (current_hour_utc + 1.0) / 24.0))
    target_microdollars = int(daily_limit_microdollars * fraction)

    if spent_microdollars >= daily_limit_microdollars:
        status = 'exhausted'
        recommended_rounds = 0
        pace_ratio = round(spent_microdollars / daily_limit_microdollars, 2)
    elif target_microdollars > 0:
        pace_ratio = round(spent_microdollars / target_microdollars, 2)
        if pace_ratio > 1.5:
            status = 'hot'
            recommended_rounds = 1
        elif pace_ratio > 1.15:
            status = 'warm'
            recommended_rounds = 2
        else:
            status = 'normal'
            recommended_rounds = 3
    else:
        status = 'normal'
        pace_ratio = 0.0
        recommended_rounds = 3

    return {
        'status': status,
        'utc_hour': round(current_hour_utc, 2),
        'fraction_of_day': round(fraction, 2),
        'spent_usd': round(spent_microdollars / 1e6, 4),
        'target_usd': round(target_microdollars / 1e6, 4),
        'limit_usd': round(daily_limit_microdollars / 1e6, 2),
        'pace_ratio': pace_ratio,
        'recommended_max_tool_rounds': recommended_rounds,
    }


import time
from typing import List, Tuple


class CPUCooler:
    """e2-micro CPU burst credit guardian. Throttles consecutive heavy operations to prevent hypervisor 25% CPU capping."""

    def __init__(self, window_seconds: float = 60.0, heavy_threshold_seconds: float = 1.5):
        self.window_seconds = window_seconds
        self.heavy_threshold_seconds = heavy_threshold_seconds
        self._history: List[Tuple[float, float, str]] = []

    def record_compute(self, op_name: str, duration_seconds: float) -> None:
        now = time.time()
        self._history.append((now, float(duration_seconds), str(op_name)))
        self._prune(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._history = [entry for entry in self._history if entry[0] >= cutoff]

    def get_recommended_cooldown(self) -> float:
        """Calculate dynamic cooldown based on accumulated compute in the rolling window."""
        now = time.time()
        self._prune(now)
        total_heavy_duration = sum(d for _, d, _ in self._history if d >= self.heavy_threshold_seconds)
        count_heavy = sum(1 for _, d, _ in self._history if d >= self.heavy_threshold_seconds)

        if count_heavy >= 3 or total_heavy_duration >= 5.0:
            return min(15.0, round(count_heavy * 2.0, 1))
        elif count_heavy >= 1:
            return 1.0
        return 0.0

    def cool_down_if_needed(self) -> float:
        """Apply non-blocking or short sleep cooling if CPU credits are strained."""
        delay = self.get_recommended_cooldown()
        if delay > 0:
            time.sleep(delay)
        return delay


# Process-level singleton instance
cpu_cooler = CPUCooler()

