"""Pinned ARM baseline acquisition: offline, no host-file discovery."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_arm_baseline_test", ROOT / "scripts/workflow/arm_baseline.py")
arm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(arm)


class ArmBaselineTests(unittest.TestCase):
    def setUp(self):
        output = ROOT / "outputs"
        output.mkdir(mode=0o700, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        (self.root / "scripts" / "workflow").mkdir(parents=True)
        (self.root / "SKILL.md").write_text("# fake current project")
        self.payload = b"synthetic official archive for a mocked download"
        self.pinned = dict(arm.BASELINE,
                           sha256=hashlib.sha256(self.payload).hexdigest())

    def test_plan_selects_official_arm64_base_without_local_search(self):
        plan = arm.planned()
        self.assertEqual(plan["architecture"], "arm64")
        self.assertEqual(plan["kind"], "rootfs-tarball")
        self.assertFalse(plan["bootable"])
        self.assertFalse(plan["downloaded"])

    def test_acquisition_requires_permission_before_network_or_output(self):
        with mock.patch.object(arm, "urlopen") as network:
            with self.assertRaises(ValueError):
                arm.acquire(False)
            network.assert_not_called()

    def test_pinned_download_and_reuse_inside_project_only(self):
        with mock.patch.object(arm, "BASELINE", self.pinned), \
             mock.patch.object(arm.workspace.Path, "cwd", return_value=self.root), \
             mock.patch.object(arm, "urlopen", return_value=io.BytesIO(self.payload)) as network:
            result = arm.acquire(True)
            self.assertTrue(result["checksum_verified"])
            dest = Path(result["file"])
            self.assertEqual(dest.read_bytes(), self.payload)
            self.assertTrue(dest.is_relative_to(self.root))
            self.assertEqual(json.loads((dest.parent / (self.pinned["id"] + ".json")).read_text())["sha256"],
                             self.pinned["sha256"])
            self.assertTrue(arm.acquire(True)["checksum_verified"])
            network.assert_called_once()

    def test_bad_digest_leaves_no_download_artifact(self):
        with mock.patch.object(arm.workspace.Path, "cwd", return_value=self.root), \
             mock.patch.object(arm, "urlopen", return_value=io.BytesIO(self.payload)):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                arm.acquire(True)
        files = list((self.root / "outputs" / "baselines").iterdir())
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
