import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_verify_vm", ROOT / "scripts/workflow/verify_vm.py")
verify_vm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_vm)

class VMVerificationTests(unittest.TestCase):
    def result(self, root):
        image = root / "vm.qcow2"
        image.write_bytes(b"synthetic-image")
        return {
            "schema_version": 1, "type": "ubuntu-customizer/image-build-result",
            "output_path": str(image), "output_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "output_bytes": image.stat().st_size, "format": "qcow2",
            "virtual_size": 4096, "architecture": "amd64"
        }

    def test_static_result_does_not_claim_boot(self):
        with tempfile.TemporaryDirectory() as d:
            result = self.result(Path(d))
            with patch.object(verify_vm, "qemu_info", return_value={"format": "qcow2", "virtual-size": 4096}):
                report = verify_vm.verify(result)
            self.assertEqual(report["static_image_check"], "passed")
            self.assertFalse(report["boot_attempted"])
            self.assertFalse(report["boot_confirmed"])

    def test_tampered_image_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            result = self.result(Path(d))
            Path(result["output_path"]).write_bytes(b"modified")
            with self.assertRaises(ValueError):
                verify_vm.validate_result(result)

    def test_wrong_architecture_refused_for_smoke(self):
        with tempfile.TemporaryDirectory() as d:
            result = self.result(Path(d))
            result["architecture"] = "arm64"
            with patch.object(verify_vm, "qemu_info", return_value={"format": "qcow2", "virtual-size": 4096}):
                with self.assertRaises(ValueError):
                    verify_vm.verify(result, boot=True, serial_log=str(Path(d) / "boot.log"))

    def test_mocked_qemu_attempt_never_marks_success(self):
        with tempfile.TemporaryDirectory() as d:
            result = self.result(Path(d))
            log = Path(d) / "serial.log"
            with patch.object(verify_vm, "qemu_info", return_value={"format": "qcow2", "virtual-size": 4096}), \
                 patch.object(verify_vm.shutil, "which", return_value="/usr/bin/qemu-system-x86_64"), \
                 patch.object(verify_vm.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
                report = verify_vm.verify(result, boot=True, serial_log=str(log))
            self.assertTrue(report["boot_attempted"])
            self.assertFalse(report["boot_confirmed"])
            self.assertEqual(report["boot_state"], "qemu_exited")

if __name__ == "__main__":
    unittest.main()
