"""Pure-Python tests for the pinned Ubuntu Cloud Image end-to-end Skill runner.

No images are downloaded and no QEMU process or remote CI is launched.
Positive paths use synthetic local fixtures and explicit mocks only.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_cloud_image_e2e_test", ROOT / "scripts/workflow/cloud_image_e2e.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

class FakeResponse:
    def __init__(self, url, payload):
        self.url = url
        self.payload = io.BytesIO(payload)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.payload.close()
    def geturl(self):
        return self.url
    def read(self, count=-1):
        return self.payload.read(count)

class CloudE2ETests(unittest.TestCase):
    def prepare(self, root, boot_mode="bios"):
        image = root / "ubuntu.img"
        image.write_bytes(b"synthetic qcow2 fixture, not a real VM")
        session = root / "verified-session"
        session.mkdir()
        pub = root / "id_ed25519.pub"
        pub.write_text("ssh-ed25519 synthetic-public-key unit-test\n")
        argv = ["--workdir", str(root / "new-run"), "--session", str(session),
                "--image", str(image), "--sha256", runner.sha256(image),
                "--public-key", str(pub), "--approve-build", "--approve-boot"]
        if boot_mode:
            argv += ["--boot-mode", boot_mode]
        return image, runner.parser().parse_args(argv)

    def test_fixed_official_source_is_https_and_pinned(self):
        source = runner.pinned_source()
        self.assertEqual(source["release"], "20261017")
        self.assertTrue(source["url"].startswith("https://cloud-images.ubuntu.com/"))
        self.assertEqual(source["sha256"], runner.PINNED_SHA256)
        self.assertEqual(len(source["sha256"]), 64)
        with self.assertRaises(ValueError):
            runner.pinned_source("untrusted-image.qcow2")

    def test_checksum_index_exactly_one_entry(self):
        digest = "a"*64
        manifest = digest + " *noble-server-cloudimg-amd64.img\n"
        self.assertEqual(runner.expected_hash(manifest), digest)
        with self.assertRaises(ValueError):
            runner.expected_hash(manifest + manifest)
        with self.assertRaises(ValueError):
            runner.expected_hash(digest + " *different.img\n")

    def test_official_download_only_to_new_file_hash_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "official.img"
            fake_image = b"A" * (1024 * 1024 + 17)
            digest = hashlib.sha256(fake_image).hexdigest()
            source = runner.pinned_source()
            sums = (digest + " *" + runner.IMAGE_NAME + "\n").encode()
            def fake_http(url, timeout=None):
                return FakeResponse(url, sums if url.endswith("SHA256SUMS") else fake_image)
            with patch.object(runner, "PINNED_SHA256", digest), \
                 patch.object(runner.urllib.request, "urlopen", side_effect=fake_http):
                metadata = runner.download_official(target)
                self.assertEqual(runner.sha256(target), digest)
                self.assertEqual(metadata["sha256"], digest)
                with self.assertRaises(ValueError):
                    runner.download_official(target)
            self.assertFalse(list(Path(tmp).glob("*.part")))

    def test_corrupt_official_checksum_refused_and_no_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "official.img"
            sums = ("0"*64 + " *" + runner.IMAGE_NAME + "\n").encode()
            with patch.object(runner.urllib.request, "urlopen",
                              return_value=FakeResponse(runner.BASE+"SHA256SUMS", sums)):
                with self.assertRaises(ValueError):
                    runner.download_official(target)
            self.assertFalse(target.exists())

    def test_guest_package_inventory_fails_closed_on_missing_qga(self):
        entries = "\n\n".join("Package: " + pkg + "\nStatus: install ok installed"
                            for pkg in ("python3", "cloud-init", "openssh-server"))
        inspector = SimpleNamespace(run_tool=lambda *a, **kw: (entries, None))
        result = runner.guest_preflight("/tmp/example.img", "qcow2", inspector=inspector)
        self.assertFalse(result["packages"]["qemu-guest-agent"])
        self.assertTrue(any("qemu-guest-agent" in x for x in result["blockers"]))
        inspector = SimpleNamespace(run_tool=lambda *a, **kw: (None, "tool_missing"))
        self.assertIsNone(runner.guest_preflight("image.img", "raw", inspector)["packages"]["cloud-init"])

    def test_host_preflight_lists_missing_tools_no_auto_installs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(runner.shutil, "which", return_value=None):
                result = runner.host_preflight(tmp, firmware_mode="uefi", minimum_gib=1)
            self.assertIn("qemu-system-x86_64", result["missing_tools"])
            self.assertTrue(result["no_auto_install"])
            self.assertTrue(any("OVMF" in reason for reason in result["blockers"]))

    def test_opt_in_approvals_and_source_sha256_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image, args = self.prepare(root)
            args.approve_boot = False
            with self.assertRaises(ValueError):
                runner.run(args)
            self.assertFalse((root / "new-run").exists())
            args.approve_boot = True
            args.sha256 = "0"*64
            with self.assertRaises(ValueError):
                runner.run(args)
            self.assertTrue((root / "new-run" / "e2e-report.json").is_file())
            self.assertEqual(json.loads((root / "new-run" / "e2e-report.json").read_text())["status"], "failed")

    def prepare_mocks(self, image, state="passed", dual=False):
        firmware = {"boot_modes":["bios","uefi"], "boot_mode": None} if dual else {
            "boot_modes":["bios"], "boot_mode":"bios"}
        inspected = {"observations":{"format":"qcow2", "guest_os":{"architecture":"amd64"},
                                     "boot_details":firmware}, "gaps":[]}
        calls = []
        def plan(*args, **kwargs):
            calls.append(("image_plan", kwargs.get("selected_firmware")))
            return {"build_allowed":True, "blockers":[], "format":"qcow2", "schema_version":1}
        def assemble(plan_obj, recipe, output, approved=False):
            calls.append(("rootfs_build", approved))
            output.mkdir()
            (output / "image.qcow2").write_bytes(b"built")
            return output, {"type":"rootfs-build-result"}
        def boot(*args, **kwargs):
            calls.append(("verify_first_boot", None))
            return {"status":state,"boot_confirmed":state == "passed",
                    "reason":"unverified" if state != "passed" else "verified_guest_health",
                    "checks":{"cloud_init": state == "passed", "ssh_host_keys": state == "passed"}}
        mapping = {
            "image_inspect": SimpleNamespace(inspect=lambda *a:inspected),
            "image_plan": SimpleNamespace(plan=plan),
            "rootfs_builder": SimpleNamespace(dry_run=lambda *a:{"missing_tools":[],"operations":["offline"]},
                assemble=assemble, verify_bundle=lambda *a:{
                    "hash_verified": True, "image_sha256": "b"*64}),
            "verify_first_boot": SimpleNamespace(verify_first_boot=boot)
        }
        return calls, mapping

    def test_unselected_dual_firmware_blocks_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image, args = self.prepare(root, boot_mode=None)
            calls, mapping = self.prepare_mocks(image, dual=True)
            with patch.object(runner,"sibling", side_effect=lambda n:mapping[n]):
                result = runner.run(args)
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(any(x["name"]=="firmware_selection" for x in result["steps"]))
            self.assertEqual(calls, [])

    def test_guest_agent_missing_prevents_unneeded_image_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image, args = self.prepare(root)
            calls, mapping = self.prepare_mocks(image)
            with patch.object(runner,"sibling", side_effect=lambda n:mapping[n]), \
                 patch.object(runner,"host_preflight",return_value={"blockers":[],"missing_tools":[],
                     "tools_available":{}}), \
                 patch.object(runner,"guest_preflight",return_value={
                     "packages":{"qemu-guest-agent":False},
                     "blockers":["Guest package missing: qemu-guest-agent"]}):
                result = runner.run(args)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("qemu-guest-agent", str(result["blockers"]))
            self.assertEqual(calls, [])
            self.assertFalse((root/"new-run"/"rootfs-bundle").exists())

    def test_synthetic_full_pipeline_success_is_not_real_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image, args = self.prepare(root)
            calls, mapping = self.prepare_mocks(image)
            with patch.object(runner,"sibling", side_effect=lambda n:mapping[n]), \
                 patch.object(runner,"host_preflight",return_value={"blockers":[],"missing_tools":[],
                     "tools_available":{}}), \
                 patch.object(runner,"guest_preflight",return_value={
                     "packages":{"qemu-guest-agent":True}, "blockers":[]}):
                result = runner.run(args)
            self.assertTrue(result["boot_confirmed"])
            self.assertEqual(result["status"], "passed")
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0], ("image_plan","bios"))
            stored = json.loads((root/"new-run"/"e2e-report.json").read_text())
            self.assertTrue(stored["artifact_integrity_verified"])
            self.assertTrue(stored["actual_vm_run"])
            self.assertEqual(runner.sha256(image), args.sha256)

    def test_failed_guest_health_retains_report_not_false_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image, args = self.prepare(root)
            calls, mapping = self.prepare_mocks(image, state="blocked")
            with patch.object(runner,"sibling", side_effect=lambda n:mapping[n]), \
                 patch.object(runner,"host_preflight",return_value={"blockers":[],"missing_tools":[],
                     "tools_available":{}}), \
                 patch.object(runner,"guest_preflight",return_value={
                     "packages":{"qemu-guest-agent":True}, "blockers":[]}):
                result = runner.run(args)
            self.assertFalse(result["boot_confirmed"])
            self.assertEqual(result["status"], "blocked")
            self.assertTrue((root/"new-run"/"e2e-report.json").exists())
            self.assertTrue((root/"new-run"/"rootfs-bundle"/"image.qcow2").exists())

if __name__ == "__main__":
    unittest.main()
