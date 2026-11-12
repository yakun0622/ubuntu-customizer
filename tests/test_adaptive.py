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
            # macOS /var/folders is a system alias for /private/var/folders.
            # The collector deliberately returns the canonical on-disk path.
            self.assertEqual(folder, dest.resolve())
            self.assertEqual(result["state"], "complete")
            self.assertTrue(result["read_only"])
            self.assertEqual(result["authorization_scope"], "initial_device_plan")
            self.assertTrue(result["device_python_auto_run"])
            self.assertTrue(result["device_shell_auto_run"])
            self.assertFalse(result["per_command_user_confirmation"])
            self.assertEqual(result["command_policy"], "fixed-readonly-probe-allowlist")
            self.assertTrue((dest / "manifest.json").exists())
            self.assertTrue(result["skipped"])
            for item in result["items"]:
                self.assertTrue((dest / item["file"]).exists())
                self.assertEqual(len(item["sha256"]), 64)

    def test_bootstrap_failure_marks_session_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "capture"
            with patch.object(adaptive, "collect_probe", return_value=("error", b"", "connection refused", 255)):
                with self.assertRaises(RuntimeError):
                    adaptive.run("ssh", "sample-host", str(dest), 3, ["network"])
            manifest = json.loads((dest / "manifest.json").read_text())
            self.assertEqual(manifest["state"], "incomplete")
            self.assertIn("bootstrap failed", manifest["failure"])

    def test_optional_preview_is_only_started_on_opt_in(self):
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "without-preview"
            def fake_probe(transport, target, command, timeout):
                if command == adaptive.FEATURE_COMMAND:
                    return ("ok", b"sysfs=1\n", "", 0)
                return ("ok", b"test\n", "", 0)
            with patch.object(adaptive, "collect_probe", side_effect=fake_probe), \
                 patch.object(adaptive, "start_preview") as start:
                _, report = adaptive.run("local", "local", str(dest), 3, [])
                self.assertNotIn("preview", report)
                start.assert_not_called()

            dest2 = Path(root) / "with-preview"
            with patch.object(adaptive, "collect_probe", side_effect=fake_probe), \
                 patch.object(adaptive, "start_preview", return_value={
                     "state": "running", "url": "http://127.0.0.1:18888/"}) as start:
                _, report = adaptive.run("local", "local", str(dest2), 3, [],
                                         preview_approved=True)
                start.assert_called_once()
                self.assertEqual(report["preview"]["state"], "running")
                self.assertEqual(report["preview"]["url"], "http://127.0.0.1:18888/")

    def test_verified_preview_url_is_emitted_before_first_probe(self):
        sequence = []
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "capture"
            def preview(path):
                self.assertTrue((path / "manifest.json").exists())
                sequence.append("preview")
                return {"state": "running", "url": "http://127.0.0.1:19991/"}
            def probe(*args):
                sequence.append("probe")
                return ("ok", b"test\\n", "", 0)
            with patch.object(adaptive, "start_preview", side_effect=preview), \
                 patch.object(adaptive, "collect_probe", side_effect=probe):
                _, report = adaptive.run("local", "local", str(destination), 3, [],
                                         preview_approved=True,
                                         preview_notify=lambda url: sequence.append("url"))
        self.assertEqual(sequence[:3], ["preview", "url", "probe"])
        self.assertEqual(report["preview"]["url"], "http://127.0.0.1:19991/")

    def test_optional_preview_failure_does_not_block_collection(self):
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "preview-fails"
            with patch.object(adaptive, "collect_probe", return_value=("ok", b"test\n", "", 0)), \
                 patch.object(adaptive, "start_preview", side_effect=RuntimeError("No listener")):
                _, report = adaptive.run("local", "local", str(dest), 3, [],
                                         preview_approved=True)
            self.assertEqual(report["state"], "complete")
            self.assertEqual(report["preview"]["state"], "unavailable")

    def test_cli_defaults_to_workspace_checked_outputs(self):
        with patch.object(adaptive.workspace, "checked_output",
                          return_value=Path("/project/outputs/device-session-fixed")) as checked, \
             patch.object(adaptive, "run", return_value=(
                 Path("/project/outputs/device-session-fixed"),
                 {"state": "complete", "items": [], "skipped": []})):
            rc = adaptive.main(["--transport", "local", "--yes"])
        self.assertEqual(rc, 0)
        self.assertTrue(checked.called)
        self.assertTrue(checked.call_args.args[0].startswith("outputs/"))

    def test_cli_rejects_output_outside_project(self):
        with patch.object(adaptive.workspace, "checked_output",
                          side_effect=ValueError("All Skill output files must be under ./outputs")), \
             patch.object(adaptive, "run") as collect:
            with self.assertRaises(SystemExit) as failure:
                adaptive.main(["--transport", "local", "--yes",
                               "--output", "/tmp/outside"])
        self.assertEqual(failure.exception.code, 2)
        collect.assert_not_called()

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
