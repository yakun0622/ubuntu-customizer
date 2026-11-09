import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("capabilities", ROOT / "scripts/workflow/capabilities.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

class CapabilityTests(unittest.TestCase):
    def session(self, root, probes):
        items = []
        for category, name, data, status in probes:
            folder = root / category
            folder.mkdir(exist_ok=True)
            file = folder / (name + ".txt")
            file.write_text(data)
            items.append({"category": category, "name": name,
                          "file": f"{category}/{name}.txt", "status": status,
                          "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
        (root / "manifest.json").write_text(json.dumps({"schema_version": 1, "transport": "local", "target": "local", "items": items}))

    def test_empty_session_does_not_assume_peripherals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            self.session(path, [])
            report = module.analyze(path)
            self.assertEqual(report["capabilities"]["device_tree"]["state"], "unknown")
            self.assertEqual(report["capabilities"]["gpio_pinctrl"]["state"], "unknown")

    def test_partial_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            self.session(path, [("identity", "os", "ID=ubuntu\n", "ok")])
            report = module.analyze(path)
            self.assertEqual(report["capabilities"]["system_identity"]["state"], "partial")

    def test_unavailable_tool_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            self.session(path, [("pins", "gpioinfo", "unavailable\n", "ok")])
            report = module.analyze(path)
            self.assertEqual(report["capabilities"]["gpio_pinctrl"]["state"], "unknown")

if __name__ == "__main__":
    unittest.main()
