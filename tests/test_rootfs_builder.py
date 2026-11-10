"""Offline RootFS builder tests; all tools and guest disk operations mocked."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from image_fixtures import plan as verified_plan

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_rootfs_builder_test", ROOT / "scripts/workflow/rootfs_builder.py")
rootfs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rootfs)

PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKJJp8za9kyuUsv1phC3wXXPzbYwdxmikbn10QECz9OA builder-test\n"

class RootfsBuilderTests(unittest.TestCase):
    def fixture(self, root, seed_iso=False):
        source = root / "source.img"
        source.write_bytes(b"immutable synthetic guest")
        pub = root / "key.pub"
        pub.write_text(PUBKEY)
        config = {
            "schema_version": 1, "hostname": "customized-vm",
            "motd": "Managed by Ubuntu Customizer\n",
            "first_boot": {"mode": "nocloud", "username": "ubuntu",
                           "instance_id": "portable-001", "ssh_public_key": str(pub),
                           "seed_iso": seed_iso}
        }
        return source, verified_plan(source), config

    def fake_tool(self, calls):
        def fake(args, timeout=1800, max_output=65536):
            calls.append(list(args))
            if args[0] == "qemu-img" and args[1] == "convert":
                Path(args[-1]).write_bytes(b"synthetic copied+customized disk")
                return b""
            if args[0] == "virt-cat":
                if args[-1] == "/etc/cloud/cloud.cfg":
                    return b"datasource_list: [ NoCloud ]\n"
                if args[-1] == "/etc/hostname":
                    return b"customized-vm\n"
                if args[-1] == "/etc/motd":
                    return b"Managed by Ubuntu Customizer\n"
            return b""
        return fake

    def safe_patches(self, source, calls):
        stack = __import__("contextlib").ExitStack()
        stack.enter_context(patch.object(rootfs.build_image, "validate", return_value=source))
        stack.enter_context(patch.object(rootfs.build_image, "inspect_image",
                                         side_effect=lambda path: {
                                             "format": "qcow2" if str(path).endswith(".qcow2") else "raw",
                                             "virtual-size": 8192}))
        stack.enter_context(patch.object(rootfs, "run_checked", side_effect=self.fake_tool(calls)))
        stack.enter_context(patch.object(rootfs, "inspect_output",
                                         side_effect=lambda path, observed, hostname, motd: {
                                             "source": {"sha256": rootfs.sha256_file(path)},
                                             "observations": observed}))
        stack.enter_context(patch.object(rootfs.shutil, "which", return_value="/usr/bin/test-tool"))
        stack.enter_context(patch.object(rootfs.progress, "preview_is_live", return_value=False))
        return stack

    def test_recipe_rejects_executables_secrets_or_unbounded_text(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _, _, config = self.fixture(root)
            rootfs.validate_config(config)
            bad = dict(config, shell="sudo rm -rf /")
            with self.assertRaises(ValueError):
                rootfs.validate_config(bad)
            with self.assertRaises(ValueError):
                rootfs.validate_config({**config, "motd": "x" * 4000})
            with self.assertRaises(ValueError):
                rootfs.validate_config({**config, "hostname": "-invalid"})
            with self.assertRaises(ValueError):
                rootfs.validate_config({**config, "first_boot":
                    {**config["first_boot"], "username": "root"}})

    def test_preview_is_readonly_and_not_approved_build(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, plan, config = self.fixture(root)
            calls = []
            with self.safe_patches(source, calls):
                preview = rootfs.dry_run(plan, config)
                self.assertEqual(preview["execution"], "disabled")
                self.assertEqual(preview["missing_tools"], [])
                self.assertFalse((root / "bundle").exists())
                with self.assertRaises(ValueError):
                    rootfs.assemble(plan, config, root / "bundle")
                self.assertEqual(calls, [])

    def test_physical_device_plan_is_blocked_before_any_tool_execution(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, plan, config = self.fixture(root)
            plan.update({"target": "physical-device", "build_allowed": False,
                         "blockers": ["BSP boot firmware not verified"]})
            calls = []
            with self.safe_patches(source, calls):
                with self.assertRaises(ValueError):
                    rootfs.assemble(plan, config, root / "bundle", approved=True)
                self.assertFalse((root / "bundle").exists())
            self.assertEqual(calls, [])

    def test_successful_mocked_build_is_private_and_original_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, plan, config = self.fixture(root)
            original = rootfs.sha256_file(source)
            calls = []
            with self.safe_patches(source, calls):
                bundle, report = rootfs.assemble(plan, config, root / "bundle", approved=True)
                verified = rootfs.verify_bundle(bundle)
            self.assertTrue(verified["hash_verified"])
            self.assertFalse(verified["boot_tested"])
            self.assertFalse(report["first_boot_confirmed"])
            self.assertEqual(rootfs.sha256_file(source), original)
            self.assertTrue((bundle / "image.qcow2").is_file())
            self.assertTrue((bundle / "seed" / "user-data").is_file())
            self.assertTrue((bundle / "seed" / "meta-data").is_file())
            self.assertTrue((bundle / "build-manifest.json").is_file())
            self.assertEqual((bundle / "build-manifest.json").stat().st_mode & 0o077, 0)
            self.assertFalse(list(root.glob(".uc-rootfs-*")))
            qemu_converts = [a for a in calls if a[0] == "qemu-img"]
            self.assertEqual(len(qemu_converts), 2)
            customize = next(a for a in calls if a[0] == "virt-customize")
            sysprep = next(a for a in calls if a[0] == "virt-sysprep")
            self.assertIn("--no-network", customize)
            self.assertIn("--no-network", sysprep)
            self.assertIn("machine-id,ssh-hostkeys", sysprep)
            self.assertNotIn(str(source), customize)
            self.assertNotIn(str(source), sysprep)

    def test_no_cloud_init_aborts_without_published_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, plan, config = self.fixture(root)
            calls = []
            with self.safe_patches(source, calls):
                original = rootfs.run_checked
                def no_cloud(args, timeout=1800, max_output=65536):
                    if args[0] == "virt-cat" and args[-1] == "/etc/cloud/cloud.cfg":
                        raise RuntimeError("Guest lacks NoCloud")
                    return original(args, timeout, max_output)
                with patch.object(rootfs, "run_checked", side_effect=no_cloud):
                    with self.assertRaises(RuntimeError):
                        rootfs.assemble(plan, config, root / "bundle", approved=True)
            self.assertFalse((root / "bundle").exists())
            self.assertFalse(list(root.glob(".uc-rootfs-*")))

    def test_output_tampering_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, plan, config = self.fixture(root)
            with self.safe_patches(source, []):
                bundle, _ = rootfs.assemble(plan, config, root / "bundle", approved=True)
                (bundle / "seed" / "user-data").write_text("tampered")
                with self.assertRaises(ValueError):
                    rootfs.verify_bundle(bundle)

    def test_missing_builder_dependencies_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, plan, config = self.fixture(root)
            with self.safe_patches(source, []), \
                 patch.object(rootfs.shutil, "which", return_value=None):
                result = rootfs.dry_run(plan, config)
                self.assertIn("virt-customize", result["missing_tools"])
                with self.assertRaises(RuntimeError):
                    rootfs.assemble(plan, config, root / "bundle", approved=True)
            self.assertFalse((root / "bundle").exists())

if __name__ == "__main__":
    unittest.main()
