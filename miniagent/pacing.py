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
