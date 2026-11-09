import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_preview_control", ROOT / "scripts/workflow/preview_control.py")
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)

class PreviewControlTests(unittest.TestCase):
    def test_missing_session_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                control.private_session(Path(d) / "missing")

    def test_cli_refuses_start_without_approval(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(control, "start") as start:
                self.assertEqual(control.main(["start", d]), 2)
                start.assert_not_called()

    def test_status_before_start(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(control.status(d)["state"], "not_started")

    def test_stale_record_never_kills_process(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            meta = {"schema_version": 1, "session": str(root.resolve()),
                    "port": 12777, "pid": 99999999, "instance_id": "a"*32}
            (root / control.RUNTIME).write_text(json.dumps(meta))
            with patch.object(control, "probe", return_value=False) , \
                 patch.object(control.os, "kill") as kill:
                self.assertEqual(control.status(root)["state"], "stale")
                with self.assertRaises(ValueError):
                    control.stop(root)
                kill.assert_not_called()
                self.assertEqual(control.clear_stale(root)["state"], "stale_record_cleared")
            self.assertFalse((root / control.RUNTIME).exists())

    def test_start_status_stop_end_to_end(self):
        # Uses a temporary directory and localhost-only ephemeral port;
        # no remote connection or target operation is performed.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            started = control.start(root, port=0)
            try:
                self.assertEqual(started["state"], "running")
                self.assertEqual(control.status(root)["state"], "running")
                with urlopen(started["url"] + "api/status", timeout=2) as res:
                    summary = json.load(res)
                self.assertEqual(summary["state"], "pending")
                self.assertNotIn("target", summary)
                with self.assertRaises(ValueError):
                    control.start(root, port=0)
            finally:
                self.assertEqual(control.stop(root)["state"], "stopped")
            self.assertEqual(control.status(root)["state"], "not_started")

if __name__ == "__main__":
    unittest.main()
