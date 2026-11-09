import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_export_html", ROOT / "scripts/workflow/export_html.py")
export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export)

class HTMLExplorerTests(unittest.TestCase):
    def test_escapes_html_and_script_breakout(self):
        graph = {
            "type": "ubuntu-customizer/linked-hardware-graph",
            "nodes": [{"id": "device:unsafe", "name": "</script><script>alert(1)</script>",
                       "type": "device", "bus": "platform"}],
            "edges": [], "gaps": [], "target_label": "<img src=x onerror=alert(1)>"
        }
        page = export.render(graph)
        self.assertNotIn("</script><script>alert(1)</script>", page)
        self.assertNotIn("<img src=x onerror=alert(1)>", page)
        self.assertIn("\\u003c/script\\u003e", page)
        self.assertIn("connect-src 'none'", page)
        self.assertIn("textContent", page)

    def test_reject_invalid_graph(self):
        with self.assertRaises(ValueError):
            export.render({"type": "arbitrary", "nodes": [], "edges": [], "gaps": []})

    def test_export_requires_verified_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "capture"
            (folder / "pins").mkdir(parents=True)
            source = folder / "pins/dt-source.txt"
            source.write_text('/ { node@1 { status = "okay"; }; };')
            (folder / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "items": [{
                    "category": "pins", "name": "dt-source",
                    "file": "pins/dt-source.txt", "status": "ok",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest()
                }]
            }))
            result = Path(tmp) / "report.html"
            export.export(folder, result)
            self.assertTrue(result.is_file())
            self.assertIn("node@1", result.read_text())
            with self.assertRaises(ValueError):
                export.export(folder, result)
            source.write_text("altered")
            with self.assertRaises(ValueError):
                export.export(folder, Path(tmp) / "other.html")

if __name__ == "__main__":
    unittest.main()
