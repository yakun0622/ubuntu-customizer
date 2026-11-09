import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("device_tree", ROOT / "scripts/workflow/device_tree.py")
dt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dt)

SAMPLE = """/dts-v1/;
/ {
    compatible = "example,board";
    soc {
        pinctrl: pinctrl@100 {
            phandle = <0x12>;
        };
        uart@200 {
            compatible = "vendor,uart";
            status = "okay";
            pinctrl-0 = <0x12>;
            pinctrl-names = "default";
        };
        ethernet@300 {
            phy-handle = <&phy0>;
            phy-mode = "rgmii";
        };
        mdio {
            phy0: ethernet-phy@0 { compatible = "ethernet-phy-ieee802.3-c22"; };
        };
    };
};
"""

class DeviceTreeTests(unittest.TestCase):
    def test_nodes_and_phandles(self):
        result = dt.parse_dts(SAMPLE, "pins/dt-source.txt")
        names = {node["id"] for node in result["nodes"]}
        self.assertIn("/soc/uart@200", names)
        self.assertIn("/soc/mdio/ethernet-phy@0", names)
        self.assertTrue(any(edge["from"] == "/soc/ethernet@300" and edge["to"] == "/soc/mdio/ethernet-phy@0" and edge["relation"] == "phy-handle" for edge in result["edges"]))
        self.assertTrue(any(edge["from"] == "/soc/uart@200" and edge["to"] == "/soc/pinctrl@100" and edge["relation"] == "pinctrl-0" and edge["confidence"] == "candidate_numeric_phandle" for edge in result["edges"]))

    def test_unresolved_reference_is_not_invented(self):
        result = dt.parse_dts('/ { dev@0 { pinctrl-0 = <&missing>; }; };', "fake.txt")
        self.assertTrue(any(gap["kind"] == "unresolved_label" for gap in result["gaps"]))
        self.assertFalse(any(edge["relation"] == "pinctrl-0" for edge in result["edges"]))

    def test_strings_with_braces(self):
        result = dt.parse_dts('/ { model = "board {rev}"; uart@0 { status = "disabled"; }; };', "fake.txt")
        self.assertIn("/uart@0", {n["id"] for n in result["nodes"]})

    def test_missing_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "manifest.json").write_text(json.dumps({"schema_version": 1, "items": []}))
            result = dt.build(folder)
            self.assertEqual(result["gaps"][0]["kind"], "not_collected")

    def test_tampered_dts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "pins").mkdir()
            source = folder / "pins/dt-source.txt"
            source.write_text(SAMPLE)
            (folder / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "items": [{"category": "pins", "name": "dt-source", "file": "pins/dt-source.txt",
                           "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "status": "ok"}]}))
            source.write_text("tampered")
            with self.assertRaises(ValueError):
                dt.build(folder)

if __name__ == "__main__":
    unittest.main()
