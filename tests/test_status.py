import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location("test_status_" + name,
        ROOT / "scripts" / "workflow" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

status = load("status")
preview = load("preview")

class StatusTests(unittest.TestCase):
    def test_agent_update_and_page_status(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            status.update(folder, "image-plan", "running", 2, 5)
            report = preview.effective_status(folder)
            self.assertEqual(report["stage"], "image-plan")
            self.assertEqual(report["state"], "running")
            self.assertEqual(report["completed"], 2)
            self.assertEqual(report["total"], 5)
            self.assertEqual((folder / "skill-status.json").stat().st_mode & 0o077, 0)

    def test_reject_freeform_and_invalid_progress(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                status.update(d, "execute arbitrary command", "running", 0, 1)
            with self.assertRaises(ValueError):
                status.update(d, "image-build", "running", 4, 2)
            with self.assertRaises(ValueError):
                status.update(d, "finish", "exfiltrate", 0, 0)

    def test_reject_status_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            target = folder / "external.json"
            target.write_text("{}")
            (folder / "skill-status.json").symlink_to(target)
            with self.assertRaises(ValueError):
                status.update(folder, "analyze", "running", 0, 1)

    def test_preview_does_not_echo_extra_fields(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "skill-status.json").write_text(json.dumps({
                "schema_version": 1, "stage": "verify", "state": "blocked",
                "completed": 0, "total": 1, "secret": "DO_NOT_EXPOSE"
            }))
            result = preview.effective_status(folder)
            self.assertNotIn("DO_NOT_EXPOSE", json.dumps(result))
            self.assertEqual(result["stage"], "verify")

if __name__ == "__main__":
    unittest.main()
