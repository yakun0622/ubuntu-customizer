"""Project-local Python workspace and output confinement tests (offline)."""
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_project_workspace_test", ROOT / "scripts/workflow/project_workspace.py")
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)


class WorkspaceTests(unittest.TestCase):
    def fixture(self, root):
        base = Path(root)
        (base / "SKILL.md").write_text("# test project\n")
        (base / "scripts" / "workflow").mkdir(parents=True)
        return base

    def test_outputs_are_private_and_not_symlinked(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            out = workspace.ensure_outputs(root)
            self.assertEqual(out, root / "outputs")
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
            self.assertTrue(out.is_dir())

    def test_python_venv_bootstrapped_locally_without_network_or_pip_install(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            calls = []
            def fake_run(argv, **kwargs):
                calls.append((argv, kwargs))
                self.assertEqual(argv[:3], [workspace.sys.executable, "-m", "venv"])
                env = root / ".venv"
                (env / "bin").mkdir(parents=True)
                (env / "pyvenv.cfg").write_text("home = test")
                (env / "bin" / "python").write_text("fake python binary")
            with mock.patch.object(workspace.subprocess, "run", side_effect=fake_run):
                result = workspace.prepare(root)
            self.assertEqual(result["state"], "ready")
            self.assertEqual(result["venv"], str(root / ".venv"))
            self.assertEqual(result["outputs"], str(root / "outputs"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1]["cwd"], root)
            with mock.patch.object(workspace.subprocess, "run") as run:
                workspace.prepare(root)
                run.assert_not_called()

    def test_explicit_outputs_must_remain_within_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            good = workspace.checked_output("outputs/session-01", root)
            self.assertEqual(good, root / "outputs" / "session-01")
            for bad in ("../outside", "outside", "outputs/../outside",
                        str(root / "not-in-outputs" / "session")):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        workspace.checked_output(bad, root)

    def test_reject_symlinks_inside_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            out = workspace.ensure_outputs(root)
            target = root / "other"
            target.mkdir()
            (out / "link").symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                workspace.output_path("link" , "session", root=root)

    def test_reject_preexisting_venv_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            other = root / "other"
            other.mkdir()
            (root / ".venv").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                workspace.prepare(root)

    def test_no_venv_creation_for_inspection_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            with mock.patch.object(workspace.subprocess, "run") as run:
                result = workspace.prepare(root, create_venv=False)
                run.assert_not_called()
            self.assertTrue((root / "outputs").is_dir())
            self.assertFalse((root / ".venv").exists())
            self.assertEqual(result["state"], "ready")


if __name__ == "__main__":
    unittest.main()
