import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_manage", ROOT / "scripts/workflow/manage.py")
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)

class DeviceManagementTests(unittest.TestCase):
    def test_default_registry_is_under_project_outputs(self):
        self.assertEqual(manage.DEFAULT_HOME, Path.cwd() / "outputs" / "device-manager")

    def test_default_discovery_never_scans_external_host_directories(self):
        with patch.object(manage, "ssh_aliases", side_effect=AssertionError("external SSH read")), \
             patch.object(manage, "adb_targets", side_effect=AssertionError("external ADB scan")), \
             patch.object(manage, "serial_ports", side_effect=AssertionError("/dev scan")):
            result = manage.discover()
        self.assertEqual(result["ssh"], [])
        self.assertEqual(result["adb"], [])
        self.assertEqual(result["ttl"], [])

    def test_host_alias_discovery_ignores_patterns(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "config"
            f.write_text("Host server-one server-two\n HostName 192.0.2.1\nHost * !blocked\n")
            self.assertEqual(manage.ssh_aliases(f), ["server-one", "server-two"])

    def test_register_and_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "data")
            result = manage.register(root, "device-01", "ssh", "server-one")
            self.assertEqual(result["transport"], "ssh")
            self.assertEqual(manage.load_catalog(root)["devices"]["device-01"]["target"], "server-one")
            self.assertEqual(manage.sessions(root, "device-01"), [])
            with self.assertRaises(ValueError):
                manage.register(root, "device-01", "ssh", "server-one")

    def test_unsafe_targets_rejected(self):
        for target in ("-oProxyCommand=bad", "foo;uname", "bad alias"):
            with self.assertRaises(ValueError):
                manage.check_target("ssh", target)
        with self.assertRaises(ValueError):
            manage.check_target("ttl", "/tmp/serial")

    def test_session_history_reads_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "data")
            manage.register(root, "device-01", "local", "local")
            folder = root / "devices" / "device-01" / "sessions" / "run-01"
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "state": "complete", "items": [{"name": "os"}], "skipped": []
            }))
            self.assertEqual(manage.sessions(root, "device-01")[0]["collected"], 1)

    def test_inspect_session_summary(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "data")
            manage.register(root, "device-01", "local", "local")
            folder = root / "devices" / "device-01" / "sessions" / "run-01"
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "state": "complete",
                "items": [{"category": "identity", "status": "ok"}, {"category": "pins", "status": "unavailable"}],
                "skipped": [{"category": "pins", "reason": "not_observed"}]
            }))
            summary = manage.inspect_session(root, "device-01", "run-01")
            self.assertEqual(summary["categories"]["pins"]["failed"], 1)
            self.assertEqual(len(summary["skipped"]), 1)

    def test_explore_session_routes_verified_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "data")
            manage.register(root, "device-01", "local", "local")
            folder = root / "devices" / "device-01" / "sessions" / "run-01"
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "state": "complete",
                "transport": "local", "target": "local", "items": []
            }))
            result = manage.explore_session(root, "device-01", "run-01", "diagnose")
            self.assertEqual(result["execution"], "disabled")
            self.assertEqual(result["task"], "diagnose")
            with self.assertRaises(ValueError):
                manage.explore_session(root, "device-01", "../bad", "diagnose")

    def test_browser_export_routes_verified_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "data")
            manage.register(root, "device-01", "local", "local")
            folder = root / "devices" / "device-01" / "sessions" / "run-01"
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "transport": "local",
                "target": "local", "state": "complete", "items": []
            }))
            page = folder / "hardware-explorer.html"
            manage.export_html.export(folder, page)
            self.assertTrue(page.is_file())
            self.assertIn("Hardware Explorer", page.read_text())
            with self.assertRaises(ValueError):
                manage.export_html.export(folder, page)

    def test_managed_image_planning_requires_registered_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "data")
            manage.register(root, "device-01", "local", "local")
            folder = root / "devices" / "device-01" / "sessions" / "run-01"
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "state": "complete", "transport": "local",
                "target": "local", "items": []
            }))
            self.assertEqual(manage.session_path(root, "device-01", "run-01"), folder)
            with self.assertRaises(ValueError):
                manage.session_path(root, "unregistered", "run-01")
            with self.assertRaises(ValueError):
                manage.session_path(root, "device-01", "../escape")

    def test_manager_denies_registry_outside_outputs(self):
        with patch.object(manage, "collect_device") as collect:
            self.assertEqual(manage.main(["--data-dir", "/tmp/outside-uc-catalog", "list"]), 2)
            collect.assert_not_called()

    def test_manager_approved_plan_avoids_repeat_prompt_and_starts_preview(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "manager")
            manage.register(root, "board", "ssh", "trusted-host")
            manifest = {"state": "complete", "items": [], "skipped": [],
                        "preview": {"state": "running", "url": "http://127.0.0.1:1234/"}}
            with patch.object(manage.adaptive.workspace, "checked_output", return_value=root), \
                 patch.object(manage, "collect_device", return_value=(root / "session", manifest)) as collector, \
                 patch("builtins.input", side_effect=AssertionError("unnecessary prompt")):
                rc = manage.main(["--data-dir", str(root), "collect", "board", "--yes"])
                self.assertEqual(rc, 0)
                self.assertTrue(collector.call_args.kwargs["preview_approved"])
                self.assertTrue(callable(collector.call_args.kwargs["preview_notify"]))
            with patch.object(manage.adaptive.workspace, "checked_output", return_value=root), \
                 patch.object(manage, "collect_device", return_value=(root / "session", manifest)) as collector, \
                 patch("builtins.input", side_effect=AssertionError("unnecessary prompt")):
                self.assertEqual(manage.main(["--data-dir", str(root), "collect", "board",
                                              "--yes", "--no-preview"]), 0)
                self.assertFalse(collector.call_args.kwargs["preview_approved"])

    def test_manager_single_consent_includes_connection_and_monitor(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "manager")
            manage.register(root, "board", "ssh", "trusted-host")
            manifest = {"state": "complete", "items": [], "skipped": []}
            with patch.object(manage.adaptive.workspace, "checked_output", return_value=root), \
                 patch.object(manage, "collect_device", return_value=(root / "session", manifest)) as collector, \
                 patch("builtins.input", return_value="yes") as prompt:
                self.assertEqual(manage.main(["--data-dir", str(root), "collect", "board"]), 0)
                self.assertEqual(prompt.call_count, 1)
                self.assertIn("监控方案", prompt.call_args.args[0])
                self.assertTrue(collector.call_args.kwargs["preview_approved"])
            with patch.object(manage.adaptive.workspace, "checked_output", return_value=root), \
                 patch.object(manage, "collect_device") as collector, \
                 patch("builtins.input", return_value="no") as prompt:
                self.assertEqual(manage.main(["--data-dir", str(root), "collect", "board"]), 1)
                self.assertEqual(prompt.call_count, 1)
                collector.assert_not_called()

    def test_manager_ttl_plan_includes_actual_baud(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "manager")
            manage.register(root, "w152d", "ttl", "/dev/cu.wchusbserial1140")
            manifest = {"state": "complete", "items": [], "skipped": []}
            with patch.object(manage.adaptive.workspace, "checked_output", return_value=root), \
                 patch.object(manage, "collect_device",
                              return_value=(root / "session", manifest)) as collector, \
                 patch("builtins.input", return_value="yes") as prompt:
                self.assertEqual(manage.main([
                    "--data-dir", str(root), "collect", "w152d", "--baud", "921600"
                ]), 0)
            self.assertEqual(prompt.call_count, 1)
            self.assertEqual(collector.call_args.kwargs["baud"], 921600)

    def test_collect_uses_existing_engine(self):
        with tempfile.TemporaryDirectory() as d:
            root = manage._private_dir(Path(d) / "data")
            manage.register(root, "device-01", "local", "local")
            with patch.object(manage.adaptive, "run", return_value=(Path(d), {"state": "complete", "items": [], "skipped": []})) as fn:
                manage.collect_device(root, "device-01", ["network"])
            self.assertEqual(fn.call_args.args[0:2], ("local", "local"))
            self.assertEqual(fn.call_args.args[4], ["network"])

if __name__ == "__main__":
    unittest.main()
