import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_nocloud", ROOT / "scripts/workflow/nocloud.py")
seed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed)

VM_PLAN = {
    "schema_version": 1, "type": "ubuntu-customizer/image-plan",
    "target": "virtual-machine", "backend": "qemu-img-offline-convert",
    "build_allowed": True, "blockers": []
}

class NoCloudTests(unittest.TestCase):
    def public_key(self, root):
        p = root / "id_ed25519.pub"
        p.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKJJp8za9kyuUsv1phC3wXXPzbYwdxmikbn10QECz9OA device-user\n")
        return p

    def test_emit_private_seed_files_with_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder, manifest = seed.make_files(VM_PLAN, "vm-one", "ubuntu",
                                               self.public_key(root), "instance-01",
                                               root / "seed")
            self.assertIn("#cloud-config", (folder / "user-data").read_text())
            parsed = json.loads((folder / "user-data").read_text().split("\n", 1)[1])
            self.assertTrue(parsed["disable_root"])
            self.assertFalse(parsed["ssh_pwauth"])
            self.assertEqual(parsed["users"][0]["name"], "ubuntu")
            self.assertEqual(manifest["files"]["meta-data"]["sha256"], seed.sha256(folder / "meta-data"))
            self.assertEqual((folder / "user-data").stat().st_mode & 0o077, 0)
            with self.assertRaises(ValueError):
                seed.make_files(VM_PLAN, "vm-one", "ubuntu", self.public_key(root),
                                "instance-02", root / "seed")

    def test_plan_must_be_approved_vm(self):
        bad = {**VM_PLAN, "target": "physical-device"}
        with self.assertRaises(ValueError):
            seed.check_image_plan(bad)
        bad = {**VM_PLAN, "build_allowed": False}
        with self.assertRaises(ValueError):
            seed.check_image_plan(bad)

    def test_bad_public_key_and_username(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            key = root / "id.pub"
            key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n")
            with self.assertRaises(ValueError):
                seed.read_key(key)
            self.assertFalse(seed.USER.fullmatch("root admin"))
            with self.assertRaises(ValueError):
                seed.make_files(VM_PLAN, "bad.name", "ubuntu", key, "id", root / "seed")

    def test_iso_fails_if_tool_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder, _ = seed.make_files(VM_PLAN, "vm-two", "ubuntu",
                                        self.public_key(root), "instance-02", root / "seed")
            with patch.object(seed.shutil, "which", return_value=None):
                with self.assertRaises(RuntimeError):
                    seed.make_iso(folder, root / "seed.iso")

    def test_mock_iso_creation_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder, _ = seed.make_files(VM_PLAN, "vm-two", "ubuntu",
                                        self.public_key(root), "instance-02", root / "seed")
            def fake_iso(args, **kwargs):
                Path(args[args.index("-output") + 1]).write_bytes(b"fake-iso-bytes")
                return subprocess.CompletedProcess(args, 0, "", "")
            with patch.object(seed.shutil, "which", return_value="/usr/bin/genisoimage"), \\
                 patch.object(seed.subprocess, "run", side_effect=fake_iso):
                result = seed.make_iso(folder, root / "seed.iso")
            self.assertEqual(result["sha256"], hashlib.sha256(b"fake-iso-bytes").hexdigest())
            with self.assertRaises(ValueError):
                seed.make_iso(folder, root / "seed.iso")

if __name__ == "__main__":
    unittest.main()
