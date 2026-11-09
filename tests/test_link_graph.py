import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("link_graph", ROOT / "scripts/workflow/link_graph.py")
graph = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(graph)

class LinkGraphTests(unittest.TestCase):
    def test_normalize_of_path(self):
        self.assertEqual(graph.normalized_of_path("/sys/firmware/devicetree/base/soc/ethernet@ff3f0000"), "/soc/ethernet@ff3f0000")
        self.assertIsNone(graph.normalized_of_path("/etc/passwd"))

    def test_link_device_with_verified_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            (session / "drivers").mkdir()
            (session / "pins").mkdir()
            rows = [
                ("drivers", "platform-bindings", "platform\tff3f0000.ethernet\tdwmac\t/sys/devices/platform/ff3f0000.ethernet\n"),
                ("drivers", "of-node-bindings", "platform\tff3f0000.ethernet\t/sys/firmware/devicetree/base/soc/ethernet@ff3f0000\n"),
                ("pins", "dt-source", "/ { soc { ethernet@ff3f0000 { compatible = \"vendor,ethernet\"; }; }; };\n"),
            ]
            items = []
            for cat, name, content in rows:
                path = session / cat / (name + ".txt")
                path.write_text(content)
                items.append({"category": cat, "name": name, "file": f"{cat}/{name}.txt",
                              "status": "ok", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            (session / "manifest.json").write_text(json.dumps({"schema_version": 1, "target": "test-board", "items": items}))
            result = graph.build(session)
            self.assertTrue(any(edge["relation"] == "described_by" and edge["from"] == "device:platform:ff3f0000.ethernet" and edge["to"] == "dt:/soc/ethernet@ff3f0000" for edge in result["edges"]))

if __name__ == "__main__":
    unittest.main()
