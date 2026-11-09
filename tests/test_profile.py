import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_profile", ROOT / "scripts/safety/validate_profile.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / "profiles/base/ubuntu-server.json").read_text())

    def test_valid_baseline(self):
        self.assertEqual(module.validate(self.profile), [])

    def test_reject_write_mode(self):
        self.profile["execution"]["dry_run"] = False
        self.assertTrue(module.validate(self.profile))

    def test_reject_shell_injection_package(self):
        self.profile["packages"]["install"] = ["curl;rm -rf /"]
        self.assertTrue(module.validate(self.profile))

    def test_reject_extra_root_key(self):
        self.profile["command"] = "shutdown -h now"
        self.assertTrue(module.validate(self.profile))


if __name__ == "__main__":
    unittest.main()
