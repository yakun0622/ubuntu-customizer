import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "workflow" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

dossier = load("dossier")
compare = load("compare")

class DossierTests(unittest.TestCase):
    def session(self, root, kernel="Linux sample 1"):
        folder = root / "session"
        folder.mkdir()
        (folder / "identity").mkdir()
        file = folder / "identity" / "kernel.txt"
        file.write_text(kernel)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "transport": "local", "target": "local",
            "items": [{"category": "identity", "name": "kernel", "file": "identity/kernel.txt",
                       "sha256": digest, "status": "ok", "bytes": len(file.read_bytes())}]
        }))
        return folder

    def test_dossier_provenance(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.session(Path(t))
            d = dossier.make_dossier(folder)
            self.assertEqual(d["identity"]["kernel"]["state"], "observed")
            self.assertEqual(d["identity"]["kernel"]["value"], "Linux sample 1")
            self.assertEqual(d["pin_mapping"]["state"], "unverified")

    def test_reject_evidence_tampering(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.session(Path(t))
            (folder / "identity/kernel.txt").write_text("tampered")
            with self.assertRaises(ValueError):
                dossier.make_dossier(folder)

    def test_missing_evidence_not_hardware_absent(self):
        with tempfile.TemporaryDirectory() as t:
            d = dossier.make_dossier(self.session(Path(t)))
            self.assertEqual(d["identity"]["board_model"]["state"], "not_collected")

    def test_compare_detects_kernel_change(self):
        old = {"identity": {"kernel": {"state": "observed", "value": "5.10"}}, "evidence": {}}
        new = {"identity": {"kernel": {"state": "observed", "value": "6.1"}}, "evidence": {}}
        result = compare.compare(old, new)
        self.assertEqual(result["identity_changes"][0]["field"], "kernel")

if __name__ == "__main__":
    unittest.main()
