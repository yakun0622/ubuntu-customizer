"""Output directory safety on macOS /var -> /private/var and Linux.

No real disk operations are performed. Canonicalization must never permit
arbitrary symlinks, existing bundle paths, or pseudo-filesystem writes.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_test_safe_output", ROOT / "scripts/workflow/safe_output.py")
safe_output = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(safe_output)

class SafeOutputTests(unittest.TestCase):
    def test_regular_private_tmpdir_has_canonical_output(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d)
            candidate = source / "new-artifact"
            result = safe_output.canonical_new_directory(candidate)
            self.assertEqual(result, source.resolve() / "new-artifact")
            self.assertFalse(result.exists())

    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "already-exists"
            target.mkdir()
            with self.assertRaises(ValueError):
                safe_output.canonical_new_directory(target)

    def test_user_symlink_parent_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "real").mkdir()
            (root / "user-link").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Symlink"):
                safe_output.canonical_new_directory(root / "user-link" / "new")

    def test_user_symlink_target_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "real").mkdir()
            (root / "new").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaises(ValueError):
                safe_output.canonical_new_directory(root / "new")

    def test_pseudofs_rejected(self):
        for path in ("/dev/uc-test-safe-output", "/proc/uc-test-safe-output",
                     "/sys/uc-test-safe-output"):
            with self.assertRaises(ValueError, msg=path):
                safe_output.canonical_new_directory(path)

    @unittest.skipUnless(sys.platform == "darwin", "macOS system aliases only")
    def test_trusted_macos_var_and_tmp_aliases(self):
        # /var itself is not user-writable; use the current user's normal
        # temporary folder beneath /var/folders instead of creating in /var.
        for alias, temp_parent in (("/var", None), ("/tmp", "/tmp")):
            root = Path(alias)
            expected = Path(safe_output.MACOS_SYSTEM_ALIASES[alias])
            if not root.is_symlink() or root.resolve() != expected:
                continue
            with tempfile.TemporaryDirectory(dir=temp_parent) as d:
                real = Path(d).resolve()
                if expected not in real.parents:
                    continue  # Host uses a different temporary volume.
                path = root / real.relative_to(expected) / "new-bundle"
                self.assertEqual(safe_output.canonical_new_directory(path),
                                 real / "new-bundle")

if __name__ == "__main__":
    unittest.main()
