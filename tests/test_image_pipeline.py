import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location("test_image_" + name, ROOT / "scripts/workflow" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

image_plan = load("image_plan")
builder = load("build_image")

class ImagePipelineTests(unittest.TestCase):
    def create_session(self, root, kernel="Linux host 6.8.0 x86_64 GNU/Linux"):
        session = root / "session"
        (session / "identity").mkdir(parents=True)
        evidence = session / "identity" / "kernel.txt"
        evidence.write_text(kernel)
        (session / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "state": "complete", "transport": "local",
            "target": "test-device", "items": [
                {"category": "identity", "name": "kernel",
                 "file": "identity/kernel.txt", "status": "ok",
                 "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
            ]}))
        return session

    def source(self, root):
        source = root / "base.img"
        source.write_bytes(b"TEST-DISK-IMAGE")
        return source, hashlib.sha256(source.read_bytes()).hexdigest()

    def test_vm_plan_is_conditional_not_guaranteed_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self.create_session(root)
            source, sha = self.source(root)
            plan = image_plan.plan(session, "virtual-machine", "qcow2", source, sha)
            self.assertTrue(plan["build_allowed"])
            self.assertEqual(plan["architecture"], "amd64")
            self.assertIn("QEMU", " ".join(plan["verification_required"]))
            self.assertEqual(plan["backend"], "qemu-img-offline-convert")

    def test_physical_board_never_automatically_buildable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self.create_session(root)
            source, sha = self.source(root)
            result = image_plan.plan(session, "physical-device", "raw", source, sha)
            self.assertFalse(result["build_allowed"])
            self.assertIsNone(result["backend"])
            self.assertGreaterEqual(len(result["blockers"]), 3)

    def test_reject_wrong_hash_and_tampered_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self.create_session(root)
            source, sha = self.source(root)
            with self.assertRaises(ValueError):
                image_plan.plan(session, "virtual-machine", "raw", source, "0" * 64)
            (session / "identity/kernel.txt").write_text("tampered")
            with self.assertRaises(ValueError):
                image_plan.plan(session, "virtual-machine", "raw", source, sha)

    def test_builder_rejects_unsupported_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, sha = self.source(Path(tmp))
            plan = {"type": "ubuntu-customizer/image-plan", "schema_version": 1,
                    "target": "physical-device", "format": "raw", "backend": None,
                    "build_allowed": False, "blockers": ["Missing BSP"],
                    "source": {"path": str(source), "sha256": sha, "bytes": source.stat().st_size}}
            with self.assertRaises(ValueError):
                builder.validate(plan)

    def test_builder_rejects_backing_chain(self):
        with patch.object(builder.shutil, "which", return_value="/usr/bin/qemu-img"), \
             patch.object(builder.subprocess, "run", return_value=subprocess.CompletedProcess(
                 ["qemu-img"], 0, json.dumps({
                     "format": "qcow2", "virtual-size": 4096, "backing-filename": "parent.img"
                 }), "")):
            with self.assertRaises(ValueError):
                builder.inspect_image(Path("/tmp/base.qcow2"))

    def test_builder_rejects_output_pseudofs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, sha = self.source(Path(tmp))
            plan = {"type": "ubuntu-customizer/image-plan", "schema_version": 1,
                    "target": "virtual-machine", "format": "qcow2",
                    "backend": "qemu-img-offline-convert", "build_allowed": True,
                    "blockers": [], "source": {"path": str(source), "sha256": sha,
                    "bytes": source.stat().st_size}}
            with self.assertRaises(ValueError):
                builder.build(plan, "/dev/not-a-block-device.qcow2")

if __name__ == "__main__":
    unittest.main()
