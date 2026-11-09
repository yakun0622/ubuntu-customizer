import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_explore", ROOT / "scripts/workflow/explore.py")
explore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(explore)

class ExploreTests(unittest.TestCase):
    def make_session(self, root):
        session = root / "capture"
        (session / "drivers").mkdir(parents=True)
        (session / "pins").mkdir()
        records = [
            ("drivers", "platform-bindings", "platform\tuart@100\tserial_drv\t/sys/devices/platform/uart@100\n"),
            ("drivers", "of-node-bindings", "platform\tuart@100\t/sys/firmware/devicetree/base/soc/uart@100\n"),
            ("pins", "dt-source", '/ { soc { uart@100 { status = "okay"; }; }; };\n'),
        ]
        items = []
        for category, name, value in records:
            file = session / category / (name + ".txt")
            file.write_text(value)
            items.append({"category": category, "name": name, "file": f"{category}/{name}.txt",
                          "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "status": "ok"})
        (session / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "transport": "local", "target": "lab-device",
            "state": "complete", "items": items,
        }))
        return session

    def test_tree_node_and_plan(self):
        with tempfile.TemporaryDirectory() as d:
            session = self.make_session(Path(d))
            folder, manifest, _, graph = explore.load_session(session)
            self.assertTrue(explore.tree_data(graph))
            id_ = "device:platform:uart@100"
            node = explore.detail(graph, id_)
            self.assertEqual(node["node"]["id"], id_)
            self.assertTrue(any(e["relation"] == "described_by" for e in node["relationships"]))
            plan = explore.build_plan(folder, manifest, graph, "diagnose", id_, "Understand UART wiring")
            self.assertEqual(plan["execution"], "disabled")
            self.assertEqual(plan["selected_node"], id_)
            self.assertEqual(plan["risk"], "R0")

    def test_unknown_node_and_invalid_task_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            session = self.make_session(Path(d))
            folder, manifest, _, graph = explore.load_session(session)
            with self.assertRaises(ValueError):
                explore.detail(graph, "device:unknown")
            with self.assertRaises(ValueError):
                explore.build_plan(folder, manifest, graph, "flash", None)

    def test_image_plan_is_blocked_for_target_validation(self):
        with tempfile.TemporaryDirectory() as d:
            session = self.make_session(Path(d))
            folder, manifest, _, graph = explore.load_session(session)
            plan = explore.build_plan(folder, manifest, graph, "image")
            self.assertEqual(plan["risk"], "R4")
            self.assertTrue(any("Boot chain" in x for x in plan["blockers"]))

    def test_refuse_overwrite_plan(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "plan.json"
            explore.write_plan(output, {"execution": "disabled"})
            with self.assertRaises(ValueError):
                explore.write_plan(output, {"execution": "disabled"})

    def test_tampered_evidence_cannot_be_browsed(self):
        with tempfile.TemporaryDirectory() as d:
            session = self.make_session(Path(d))
            (session / "pins/dt-source.txt").write_text("tampered")
            with self.assertRaises(ValueError):
                explore.load_session(session)

if __name__ == "__main__":
    unittest.main()
