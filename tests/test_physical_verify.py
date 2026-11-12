"""ARM physical boot logs are evidence, never proof of safe flashing or boot."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_physical_verify_test",
                                            ROOT / "scripts/workflow/physical_verify.py")
physical = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(physical)

LOG = """U-Boot 2026.07
Booting Linux on physical CPU 0x0000000000
Linux version 6.12.18 (builder@host)
Machine model: Amlogic SM1 example board
VFS: Mounted root (ext4 filesystem) readonly on device 179:2.
Run /sbin/init as init process
systemd[1]: Started NetworkManager.
end0: Link is Up - 100Mbps/Full
armbian login:
secret: MAC=aa:bb:cc:dd:ee:ff password=do-not-publish
"""

class PhysicalEvidenceTests(unittest.TestCase):
    def test_arm_boot_events_reported_without_claiming_boot_confirmed(self):
        result = physical.classify_log(LOG)
        self.assertEqual(result["state"], "userspace_markers_observed")
        self.assertTrue(result["kernel_observed"])
        self.assertTrue(result["userspace_observed"])
        self.assertTrue(result["network_link_observed"])
        self.assertFalse(result["boot_confirmed"])
        self.assertEqual(result["markers"]["kernel"], 3)
        self.assertNotIn("do-not-publish", json.dumps(result))

    def test_panic_overrides_login_prompt(self):
        result = physical.classify_log(LOG + "\nKernel panic - not syncing:\n")
        self.assertEqual(result["state"], "boot_error_observed")
        self.assertIn("kernel_panic", result["boot_errors"])
        self.assertFalse(result["boot_confirmed"])

    def test_kernel_only_is_partial(self):
        result = physical.classify_log("Linux version 6.10-test\n")
        self.assertEqual(result["state"], "partial_boot_evidence")
        self.assertFalse(result["userspace_observed"])

    def test_external_log_is_unbound_to_verified_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            log = root / "uart.log"
            log.write_text(LOG)
            report = physical.evaluate(log=log)
            self.assertFalse(report["session"]["log_bound_to_session"])
            self.assertFalse(report["physical_deployment_allowed"])
            self.assertIn("BSP_kernel_DTB", report["missing_gates"])
            self.assertEqual(report["boot_log"]["source_sha256"],
                             hashlib.sha256(log.read_bytes()).hexdigest())
            self.assertNotIn("aa:bb:cc", json.dumps(report))

    def test_symlink_and_oversized_log_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            log = root / "uart.log"
            log.write_text(LOG)
            other = root / "link.log"
            other.symlink_to(log)
            with self.assertRaises(ValueError):
                physical.evaluate(log=other)
            log.write_bytes(b"x" * (physical.MAX_LOG + 1))
            with self.assertRaises(ValueError):
                physical.evaluate(log=log)

    def test_image_requires_trusted_hash_and_reports_unknown_bsp(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            image = root / "physical.img"
            image.write_bytes(b"synthetic raw disk")
            with self.assertRaises(ValueError):
                physical.evaluate(image=image)
            with self.assertRaises(ValueError):
                physical.evaluate(image=image, sha256="0"*64)
            report = {"observations":{"format":"raw","partition_table":"mbr",
                         "guest_os":{"architecture":"arm64","distribution":"debian"},
                         "boot_details":{"kernels":[{"version":"6.12.0"}]}},
                      "gaps":[{"check":"boot_firmware","reason":"unavailable"}]}
            inspector = type("FakeInspector", (), {
                "safe_source":staticmethod(lambda p:Path(p)),
                "inspect":staticmethod(lambda p,s:report)})
            with patch.object(physical, "sibling", return_value=inspector):
                result = physical.evaluate(image=image, sha256=physical.hash_file(image))
            self.assertEqual(result["static_image"]["guest_architecture"], "arm64")
            self.assertFalse(result["static_image"]["physical_bsp_verified"])
            self.assertFalse(result["physical_deployment_allowed"])

    def test_report_permissions_and_no_raw_uart_data(self):
        # CLI reports must live inside the project's private outputs tree.
        with tempfile.TemporaryDirectory(dir=physical.workspace.ensure_outputs()) as d:
            root = Path(d)
            log = root / "uart.log"
            log.write_text(LOG)
            report = root / "report.json"
            self.assertEqual(physical.main(["--log",str(log),"--output",str(report)]),0)
            result = json.loads(report.read_text())
            self.assertFalse(result["boot_confirmed"])
            self.assertEqual(report.stat().st_mode & 0o077,0)
            self.assertNotIn("password=",report.read_text())
            self.assertNotIn("aa:bb:cc",report.read_text())
            self.assertEqual(physical.main(["--log",str(log),"--output",str(report)]),2)

if __name__ == "__main__":
    unittest.main()
