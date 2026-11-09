import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("collect", ROOT / "scripts/workflow/collect.py")
collect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect)

class WorkflowTests(unittest.TestCase):
    def test_ssh_command_is_fixed_and_quotes_probe(self):
        command = collect.shell_invocation("ssh", "test-host", "cat /etc/os-release")
        self.assertEqual(command[0], "ssh")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertEqual(command[-2], "test-host")
        self.assertTrue(command[-1].startswith("sh -c "))

    def test_adb_serial_is_separate_argument(self):
        command = collect.shell_invocation("adb", "SERIAL-123", "uname -a")
        self.assertEqual(command[:3], ["adb", "-s", "SERIAL-123"])
        self.assertEqual(command[3], "shell")

    def test_capture_reports_command_failure(self):
        with patch.object(collect.subprocess, "run", return_value=subprocess.CompletedProcess(["sh"], 1, b"", b"denied")):
            status, payload, error, code = collect.capture(["sh", "-c", "false"], 2)
        self.assertEqual(status, "error")
        self.assertEqual(payload, b"")
        self.assertEqual(code, 1)

    def test_capture_marks_unavailable(self):
        with patch.object(collect.subprocess, "run", return_value=subprocess.CompletedProcess(["sh"], 0, b"unavailable\n", b"")):
            status, _, _, _ = collect.capture(["sh", "-c", ":"], 2)
        self.assertEqual(status, "unavailable")

    def test_output_dir_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "new-session"
            created = collect.safe_output_dir(str(path))
            self.assertTrue(created.is_dir())
            with self.assertRaises(ValueError):
                collect.safe_output_dir(str(path))

    def test_no_unapproved_mutation_probes(self):
        commands = [command for _, _, command in collect.PROBES]
        self.assertGreater(len(commands), 10)
        for command in commands:
            self.assertNotIn("sudo ", command)
            self.assertNotIn("mount ", command)
            self.assertNotIn("reboot", command)
            self.assertNotIn("flash", command)

if __name__ == "__main__":
    unittest.main()
