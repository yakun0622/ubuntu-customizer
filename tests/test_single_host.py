"""Safe, explicit single-host execution, especially Mac's local Lima adapter."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_single_host_test",
                                            ROOT / "scripts/workflow/single_host.py")
single = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(single)

class SingleHostTests(unittest.TestCase):
    def arg(self, action, *options):
        return single.parser().parse_args([action, *options])

    def test_linux_native_fixed_inspection_command(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            source = folder / "input.img"
            source.write_bytes(b"source")
            args = self.arg("inspect", "--source", str(source),
                            "--sha256", "a"*64, "--output", str(folder / "inspection.json"))
            result = single.prepare("inspect", args, backend="native", host_platform="linux")
            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["command"][1].endswith("image_inspect.py"))
            self.assertNotIn("sh", result["command"])
            self.assertNotIn("--approved", result["command"])

    def test_explicit_approval_required_for_write_and_boot(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            plan = folder / "plan.json"
            config = folder / "config.json"
            plan.write_text("{}")
            config.write_text("{}")
            args = self.arg("rootfs", "--plan", str(plan), "--config", str(config),
                            "--output-dir", str(folder / "output"))
            with self.assertRaisesRegex(ValueError, "approved"):
                single.command_for("rootfs", args)
            args = self.arg("verify-boot", "--bundle", str(folder),
                            "--report", str(folder / "health.json"))
            with self.assertRaisesRegex(ValueError, "approved"):
                single.command_for("verify-boot", args)

    def test_guest_share_restricts_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "real").mkdir()
            allowed = home / "real" / "data.json"
            allowed.write_text("{}")
            self.assertEqual(single.shared_path(allowed, home=home), str(allowed.resolve()))
            self.assertEqual(single.shared_path(home / "real" / "output.json",
                                                output=True, home=home),
                             str(home.resolve() / "real" / "output.json"))
            (home / "linked").symlink_to(home / "real", target_is_directory=True)
            with self.assertRaises(ValueError):
                single.shared_path(home / "linked" / "data.json", home=home)
            with self.assertRaises(ValueError):
                single.shared_path(allowed, output=True, home=home)

    def test_guest_share_outside_home_denied(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as outside:
            source = Path(outside) / "image.img"
            source.write_bytes(b"private")
            with self.assertRaisesRegex(ValueError, "within the mounted host home"):
                single.shared_path(source, home=home)

    def test_lima_preflight_does_not_run_image_command_or_start_vm(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            source = folder / "source.img"
            source.write_bytes(b"abc")
            args = self.arg("inspect", "--source", str(source),
                            "--sha256", "a"*64, "--output", str(folder / "report.json"),
                            "--check-only")
            # Test host and repository are not actually mounted under the fake
            # Mac home, so path validation is mocked to isolate dispatch logic.
            fake_guest = {"available":True, "tools":{
                "qemu-img":True, "virt-inspector":True, "virt-filesystems":True,
                "virt-drivers":True,"guestfish":True}, "shared_output_writable":True,
                "shared_input_readable":True}
            cap = type("FakeCaps", (), {"probe_lima":staticmethod(lambda *a,**kw:fake_guest)})
            calls = []
            def fake_runner(cmd, **kwargs):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd,0)
            with patch.object(single, "shared_path", side_effect=lambda p,**kw:str(p)), \
                 patch.object(single, "module", return_value=cap):
                result = single.execute("inspect", args, backend="lima",
                                        host_platform="darwin", runner=fake_runner)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(calls, [])
            with patch.object(single, "shared_path", side_effect=lambda p,**kw:str(p)), \
                 patch.object(single, "module", return_value=cap):
                ready = single.prepare("inspect", args, backend="lima",
                                       host_platform="darwin", runner=fake_runner)
            self.assertIn("--start=false", ready["command"])
            self.assertEqual(ready["command"][0], "limactl")

    def test_lima_read_only_host_mount_blocks_write(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            source = folder / "source.img"
            source.write_bytes(b"abc")
            args = self.arg("inspect", "--source", str(source),
                            "--sha256", "a"*64, "--output", str(folder / "report.json"))
            guest = {"available":True, "tools":{"qemu-img":True,
                     "virt-inspector":True,"virt-filesystems":True,
                     "virt-drivers":True, "guestfish":True},
                     "shared_output_writable":False, "shared_input_readable":True}
            cap = type("FakeCaps", (), {"probe_lima":staticmethod(lambda *a,**kw:guest)})
            with patch.object(single, "shared_path", side_effect=lambda p,**kw:str(p)), \
                 patch.object(single, "module", return_value=cap):
                with self.assertRaisesRegex(ValueError, "not writable"):
                    single.prepare("inspect", args, backend="lima", host_platform="darwin")

if __name__ == "__main__":
    unittest.main()
