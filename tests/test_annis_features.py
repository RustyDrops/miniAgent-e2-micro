"""Tests for AnnIs-Mini inspired features: JIT tool scoping, scratchpad handoff, and per-role budget attribution."""

from decimal import Decimal
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from miniagent.budget import Budget
from miniagent.tools import (
    SCHEMAS,
    SCHEMAS_LITE,
    SCHEMAS_RESEARCH,
    SCHEMAS_CODING,
    SCHEMAS_AUDIT,
    get_schemas_for_role,
)
from miniagent.agent import Agent, role_schemas
from miniagent.config import Config


class TestAnnIsFeatures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "budget_test.db")
        self.budget = Budget(self.db_path, Decimal("1.00"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_jit_schema_subsets_smaller_than_full(self):
        """Verify that role-scoped JIT tool subsets are significantly smaller than the full schema set."""
        self.assertLess(len(SCHEMAS_LITE), len(SCHEMAS))
        self.assertLess(len(SCHEMAS_RESEARCH), len(SCHEMAS))
        self.assertLess(len(SCHEMAS_CODING), len(SCHEMAS))
        self.assertLess(len(SCHEMAS_AUDIT), len(SCHEMAS))

        # Check get_schemas_for_role routing
        self.assertEqual(get_schemas_for_role("researcher"), SCHEMAS_RESEARCH)
        self.assertEqual(get_schemas_for_role("coding"), SCHEMAS_CODING)
        self.assertEqual(get_schemas_for_role("audit"), SCHEMAS_AUDIT)
        self.assertEqual(get_schemas_for_role("lite"), SCHEMAS_LITE)

    def test_role_schemas_preserves_system_health(self):
        """Verify all roles retain essential system_health and peek_draft tools."""
        for role in ("researcher", "builder", "reviewer"):
            names = {s["function"]["name"] for s in role_schemas(role, SCHEMAS)}
            self.assertIn("system_health", names)
            self.assertIn("peek_draft", names)

    def test_per_role_budget_attribution(self):
        """Verify spend reservations attribute costs to specific specialist roles."""
        # Reserve for researcher
        res_r = self.budget.reserve(50000, model="gemini-2.5-flash-lite", role="researcher")
        self.budget.settle(res_r, actual=45000, input_tokens=450, output_tokens=100)

        # Reserve for builder
        res_b = self.budget.reserve(120000, model="gemini-2.5-flash", role="builder")
        self.budget.settle(res_b, actual=110000, input_tokens=1000, output_tokens=250)

        # Reserve for reviewer
        res_rev = self.budget.reserve(30000, model="gemini-2.5-flash", role="reviewer")
        self.budget.settle(res_rev, actual=28000, input_tokens=250, output_tokens=80)

        breakdown = self.budget.usage_by_role()
        roles = {row["role"]: row for row in breakdown}

        self.assertIn("builder", roles)
        self.assertIn("researcher", roles)
        self.assertIn("reviewer", roles)

        self.assertEqual(roles["builder"]["committed_microdollars"], 110000)
        self.assertEqual(roles["researcher"]["committed_microdollars"], 45000)
        self.assertEqual(roles["reviewer"]["committed_microdollars"], 28000)

    def test_transient_scratchpad_handoff(self):
        """Verify that intermediate specialist output is propagated forward via [PLAN SCRATCHPAD]."""
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = [
            {"content": "Step 1: Found data in arXiv paper 2401.00001."},
            {"content": "Step 2: Wrote draft in workspace."},
            {"content": "Step 3: All verified and ready."},
        ]

        cfg = Config(
            db_path=self.db_path,
            daily_usd=Decimal("1.00"),
            api_key="fake-key",
            base_url="https://api.example.com",
            model="gemini-2.5-flash",
            input_price=Decimal("0.10"),
            output_price=Decimal("0.40"),
            max_output_tokens=500,
            timeout_seconds=10,
            max_input_bytes=10000,
            max_tool_rounds=0,
            service_tier="standard",
        )

        agent = Agent(cfg, tool_schemas=SCHEMAS, provider=mock_provider)
        res = agent.run_task("Analyze and draft report")

        self.assertIn("Step 1", res)
        self.assertIn("Step 2", res)
        self.assertIn("Step 3", res)

        # Check call arguments for Step 2 and Step 3
        # Call 1 (researcher) receives User task
        # Call 2 (builder) receives [PLAN SCRATCHPAD] with Step 1 content
        call_2_msgs = mock_provider.complete.call_args_list[1][0][0]
        user_msg_2 = next(m["content"] for m in call_2_msgs if m["role"] == "user")
        self.assertIn("[PLAN SCRATCHPAD - Pertinent facts from previous step]:", user_msg_2)
        self.assertIn("Step 1: Found data", user_msg_2)


if __name__ == "__main__":
    unittest.main()
