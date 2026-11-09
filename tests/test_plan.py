import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("plan", ROOT / "scripts/system/plan.py")
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)

class PlanTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / "profiles/base/ubuntu-server.json").read_text())

    def test_plan_is_dry_run(self):
        result = plan.collect(self.profile)
        self.assertEqual(result["mode"], "dry-run")
        self.assertTrue(all(action["risk"] == "R2" for action in result["actions"]))

    def test_mismatch_blocks_plan(self):
        self.profile["target"]["distribution"] = "armbian"
        result = plan.collect(self.profile)
        self.assertTrue(result["blocked"])

if __name__ == "__main__":
    unittest.main()
