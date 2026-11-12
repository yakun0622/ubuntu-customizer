"""Single-host capability selection without creating VMs or installing tools."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_host_capabilities_test",
                                            ROOT / "scripts/workflow/host_capabilities.py")
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)

class HostCapabilityTests(unittest.TestCase):
    def all_tools(self):
        return {x: True for x in host.CORE + tuple(host.QEMU.values())}

    def test_native_linux_vm_build_and_optional_qemu(self):
        result = host.decide("linux", "amd64", self.all_tools(),
                             "virtual-machine", "amd64")
        self.assertEqual(result["build"]["backend"], "native-linux")
        self.assertEqual(next(x for x in result["verification"]
                              if x["id"] == "qemu-guest-health")["status"], "available")
        self.assertFalse(any(x["boot_confirmed"] for x in result["verification"]))

    def test_mac_existing_lima_vm_is_same_host_backend(self):
        lima = {"available": True, "os": "linux", "arch": "arm64",
                "tools": self.all_tools(), "shared_input_readable": True,
                "shared_output_writable": True}
        result = host.decide("darwin", "arm64", {}, "virtual-machine",
                             "amd64", lima)
        self.assertEqual(result["build"]["backend"], "lima-local-linux")
        lima["shared_output_writable"] = False
        blocked = host.decide("darwin", "arm64", {}, "virtual-machine", "amd64", lima)
        self.assertEqual(blocked["build"]["status"], "blocked")
        self.assertEqual(blocked["build"]["reason"], "lima_shared_paths_not_accessible_or_writable")

    def test_missing_guest_tools_does_not_claim_native_build(self):
        lima = {"available": True, "tools": {"qemu-img": True},
                "shared_input_readable": True, "shared_output_writable": True}
        result = host.decide("darwin", "arm64", {}, "virtual-machine",
                             "amd64", lima)
        self.assertIsNone(result["build"]["backend"])
        self.assertIn("virt-customize", result["build"]["missing"])

    def test_physical_arm_is_static_log_only(self):
        result = host.decide("linux", "arm64", self.all_tools(),
                             "physical-device", "arm64")
        self.assertEqual(result["build"]["status"], "blocked")
        self.assertEqual(result["build"]["reason"],
                         "physical_BSP_bootloader_DTB_recovery_not_verified")
        self.assertEqual(next(x for x in result["verification"]
                              if x["id"] == "arm-serial-boot-log")["status"], "available")
        self.assertEqual(next(x for x in result["verification"]
                              if x["id"] == "qemu-guest-health")["status"], "unavailable")

    def test_default_inspection_never_scans_host_path_or_lima(self):
        with patch.object(host.shutil, "which", side_effect=AssertionError("PATH read")), \
             patch.object(host, "probe_lima", side_effect=AssertionError("Lima I/O")):
            result = host.inspect(target="physical-device", target_arch="arm64")
        self.assertTrue(result["project_only_host_scan"])
        self.assertFalse(any(result["tools"].values()))
        self.assertEqual(result["lima"]["reason"], "project_only_no_host_scan")

    def test_lima_probe_never_starts_vm(self):
        seen = []
        payload = {"os": "linux", "arch": "aarch64",
                   "tools": {x:True for x in host.CORE},
                   "cwd_writable":True, "input_readable":True}
        def runner(args, **kw):
            seen.append(args)
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        with patch.object(host.shutil, "which", return_value="/usr/local/bin/limactl"):
            result = host.probe_lima("default", "/Users/demo/build", "/Users/demo/project",
                                     runner=runner)
        self.assertTrue(result["available"])
        self.assertEqual(result["arch"], "arm64")
        self.assertIn("--start=false", seen[0])
        self.assertNotIn("start", seen[0])
        self.assertEqual(seen[0][-2:], ["/Users/demo/build", "/Users/demo/project"])

    def test_lima_probe_invalid_or_absent_fails_closed(self):
        with self.assertRaises(ValueError):
            host.probe_lima("default;rm -rf /")
        with patch.object(host.shutil, "which", return_value=None):
            self.assertEqual(host.probe_lima("default")["reason"], "limactl_missing")

if __name__ == "__main__":
    unittest.main()
