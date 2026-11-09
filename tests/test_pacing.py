import unittest
from miniagent.pacing import calculate_pacing


class PacingTests(unittest.TestCase):
    def test_pacing_normal_spend(self):
        # 12:00 UTC (hour 12), limit $1.00 ($1,000,000 microdollars), spent $0.30 ($300,000 microdollars)
        # Expected target at hour 12: ~54% -> $540,000. Spent is below target.
        res = calculate_pacing(300000, 1000000, current_hour_utc=12.0)
        self.assertEqual(res['status'], 'normal')
        self.assertEqual(res['recommended_max_tool_rounds'], 3)
        self.assertLess(res['pace_ratio'], 1.0)

    def test_pacing_hot_spend(self):
        # 02:00 UTC (hour 2), limit $1.00, spent $0.40 ($400,000 microdollars)
        # Expected target at hour 2: 3/24 = 12.5% -> $125,000. Spent is way ahead of target!
        res = calculate_pacing(400000, 1000000, current_hour_utc=2.0)
        self.assertEqual(res['status'], 'hot')
        self.assertEqual(res['recommended_max_tool_rounds'], 1)
        self.assertGreater(res['pace_ratio'], 1.5)

    def test_pacing_exhausted(self):
        res = calculate_pacing(1000000, 1000000, current_hour_utc=15.0)
        self.assertEqual(res['status'], 'exhausted')
        self.assertEqual(res['recommended_max_tool_rounds'], 0)

    def test_cpu_cooler_cooldown(self):
        from miniagent.pacing import CPUCooler
        cooler = CPUCooler(window_seconds=60.0, heavy_threshold_seconds=1.0)
        self.assertEqual(cooler.get_recommended_cooldown(), 0.0)

        # Record a single heavy event
        cooler.record_compute("canary_run", 2.0)
        self.assertEqual(cooler.get_recommended_cooldown(), 1.0)

        # Record multiple heavy events
        cooler.record_compute("ast_sweep", 3.0)
        cooler.record_compute("wal_truncate", 2.5)
        self.assertGreaterEqual(cooler.get_recommended_cooldown(), 5.0)


if __name__ == '__main__':
    unittest.main()
