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
