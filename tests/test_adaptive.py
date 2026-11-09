import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("adaptive", ROOT / "scripts/workflow/adaptive.py")
adaptive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adaptive)

class AdaptiveTests(unittest.TestCase):
    def test_parse_features_ignores_untrusted_keys(self):
        result = adaptive.parse_features("dtc=1\ngpioinfo=0\nUNKNOWN=1\n")
        self.assertEqual(result, {"dtc": True, "gpioinfo": False})

    def test_skip_only_unobserved_dependencies(self):
        planned = adaptive.plan(["pins", "network"], {"gpioinfo": True, "ip": True})
        statuses = {(p["category"], p["name"]): p["status"] for p in planned}
        self.assertEqual(statuses["pins", "gpioinfo"], "pending")
        self.assertEqual(statuses["pins", "dt-source"], "skipped")
        self.assertEqual(statuses["network", "ip-link"], "pending")

    def test_no_inference_when_feature_probe_fails(self):
        planned = adaptive.plan(["drivers"], {})
        self.assertEqual(next(p for p in planned if p["name"] == "sysfs-bindings")["status"], "skipped")

    def test_checkpoint_and_read_only_execution(self):
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "capture"
            def fake_capture(transport, target, command, timeout):
                if command == adaptive.FEATURE_COMMAND:
                    return ("ok", b"devicetree=0\nsysfs=1\nbuses=0\n", "", 0)
                return ("ok", b"test\n", "", 0)
            with patch.object(adaptive, "collect_probe", side_effect=fake_capture):
                folder, result = adaptive.run("local", "local", str(dest), 3, ["pins", "drivers"])
            self.assertEqual(folder, dest)
            self.assertEqual(result["state"], "complete")
            self.assertTrue(result["read_only"])
            self.assertTrue((dest / "manifest.json").exists())
            self.assertTrue(result["skipped"])
            for item in result["items"]:
                self.assertTrue((dest / item["file"]).exists())
                self.assertEqual(len(item["sha256"]), 64)

    def test_existing_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                adaptive.run("local", "local", root, 3, [])

    def test_no_unapproved_probe_commands(self):
        self.assertNotIn("sudo", adaptive.FEATURE_COMMAND)
        self.assertNotIn("mount", adaptive.FEATURE_COMMAND)
        self.assertNotIn("reboot", adaptive.FEATURE_COMMAND)

if __name__ == "__main__":
    unittest.main()
