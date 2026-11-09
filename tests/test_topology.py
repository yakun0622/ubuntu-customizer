import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("topology", ROOT / "scripts/workflow/topology.py")
topology = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(topology)

class TopologyTests(unittest.TestCase):
    def make_session(self, root, data, status="ok"):
        session = root / "session"
        (session / "drivers").mkdir(parents=True)
        path = session / "drivers/sysfs-bindings.txt"
        path.write_text(data)
        (session / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "target": "test", "items": [
                {"category": "drivers", "name": "sysfs-bindings",
                 "file": "drivers/sysfs-bindings.txt", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "status": status, "bytes": len(path.read_bytes())}]}))
        return session

    def test_driver_binding_has_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session(Path(tmp), "net\tend0\tdwmac-meson8b\t/sys/devices/platform/soc/ethernet\n")
            result = topology.build_topology(session)
            self.assertEqual(len(result["edges"]), 1)
            self.assertEqual(result["edges"][0]["relation"], "bound_to")
            self.assertEqual(result["edges"][0]["source"], "drivers/sysfs-bindings.txt")
            self.assertEqual(result["edges"][0]["confidence"], "observed_sysfs")

    def test_no_binding_not_hardware_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session(Path(tmp), "net\tend0\t\t/sys/devices/platform/soc/ethernet\n")
            result = topology.build_topology(session)
            self.assertEqual(len(result["edges"]), 0)
            self.assertIn("driver_not_observed", [gap["status"] for gap in result["gaps"]])

    def test_malformed_rows_not_inferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session(Path(tmp), "net\tend0\tdriver\t/etc/passwd\nmalformed\n")
            result = topology.build_topology(session)
            self.assertEqual(len(result["edges"]), 0)
            self.assertIn("invalid_path", [gap["status"] for gap in result["gaps"]])

    def test_integrity_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session(Path(tmp), "net\tend0\tfoo\t/sys/test\n")
            (session / "drivers/sysfs-bindings.txt").write_text("tampered")
            with self.assertRaises(ValueError):
                topology.build_topology(session)

if __name__ == "__main__":
    unittest.main()
