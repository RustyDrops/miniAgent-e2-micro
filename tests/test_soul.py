"""Tests for the Soul & continuous streak tracker."""

import json
from pathlib import Path
import tempfile
import unittest

from miniagent.soul import Soul


class TestSoul(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_initialization_and_save(self):
        soul = Soul(name="TestAgent")
        self.assertEqual(soul.streak_days, 1)
        self.assertEqual(soul.name, "TestAgent")
        soul.save(self.workspace)

        loaded = Soul.load(self.workspace)
        self.assertEqual(loaded.name, "TestAgent")
        self.assertEqual(loaded.streak_days, 1)
        self.assertIn("Autonomously", loaded.active_goal)

    def test_streak_progression(self):
        soul = Soul(streak_days=5, last_active_date="2026-11-01")
        # Next consecutive day
        soul.record_daily_activity(date_str="2026-11-02")
        self.assertEqual(soul.streak_days, 6)

        # Same day maintains streak
        soul.record_daily_activity(date_str="2026-11-02")
        self.assertEqual(soul.streak_days, 6)

        # Gap of more than 1 day resets streak to 1
        soul.record_daily_activity(date_str="2026-11-05")
        self.assertEqual(soul.streak_days, 1)

        # Budget breach resets streak to 0
        soul.record_daily_activity(date_str="2026-11-06", budget_breached=True)
        self.assertEqual(soul.streak_days, 0)

    def test_task_success_and_goal(self):
        soul = Soul()
        soul.record_task_success(cost_usd=0.0125)
        self.assertEqual(soul.total_tasks_completed, 1)
        self.assertAlmostEqual(soul.total_usd_spent, 0.0125, places=4)

        soul.set_goal("Solve Picoling-style edge optimization")
        self.assertEqual(soul.active_goal, "Solve Picoling-style edge optimization")


if __name__ == "__main__":
    unittest.main()
