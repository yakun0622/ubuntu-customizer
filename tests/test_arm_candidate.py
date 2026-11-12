"""Board-candidate staging keeps all local reads/writes in the active workspace."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_arm_candidate_test", ROOT / "scripts/workflow/arm_candidate.py")
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class ArmCandidateTests(unittest.TestCase):
    def setUp(self):
        out = ROOT / "outputs"
        out.mkdir(mode=0o700, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=out)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project"
        (self.root / "scripts" / "workflow").mkdir(parents=True)
        (self.root / "SKILL.md").write_text("# fake current project")
        source = dict(candidate.baseline.BASELINE)
        payload = b"mock official base"
        source["sha256"] = hashlib.sha256(payload).hexdigest()
        self.source = source
        base = self.root / "outputs" / "baselines"
        base.mkdir(parents=True)
        archive = base / source["filename"]
        archive.write_bytes(payload)
        self.manifest = base / (source["id"] + ".json")
        self.manifest.write_text(json.dumps(dict(source, file=str(archive))))

    def test_new_revision_stages_components_without_claiming_bootability(self):
        dtb = self.root / "board.dtb"
        dtb.write_bytes(b"mock dtb")
        with mock.patch.object(candidate.baseline, "BASELINE", self.source), \
             mock.patch.object(candidate.workspace.Path, "cwd", return_value=self.root):
            first = candidate.stage("w152d", str(self.manifest), 1, {"dtb": str(dtb)})
            self.assertTrue(first["rootfs_verified"])
            self.assertFalse(first["bootable_image_created"])
            self.assertFalse(first["boot_confirmed"])
            self.assertFalse(first["deployment_allowed"])
            self.assertEqual(first["missing_boot_components"], ["kernel", "bootloader"])
            self.assertEqual(dtb.read_bytes(), b"mock dtb")
            with self.assertRaises(FileExistsError):
                candidate.stage("w152d", str(self.manifest), 1)
            second = candidate.stage("w152d", str(self.manifest), 2)
            self.assertEqual(second["revision"], 2)

    def test_external_file_and_symlink_are_never_read(self):
        with mock.patch.object(candidate.baseline, "BASELINE", self.source), \
             mock.patch.object(candidate.workspace.Path, "cwd", return_value=self.root):
            with self.assertRaises(ValueError):
                candidate.stage("w152d", str(self.manifest), 1,
                                {"dtb": "/etc/passwd"})
            escaped = self.root / "fake.dtb"
            escaped.symlink_to("/etc/passwd")
            with self.assertRaises(ValueError):
                candidate.stage("w152d", str(self.manifest), 1,
                                {"dtb": str(escaped)})
            with self.assertRaises(ValueError):
                candidate.stage("../outside", str(self.manifest), 1)


if __name__ == "__main__":
    unittest.main()
