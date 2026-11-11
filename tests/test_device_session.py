"""Offline and PTY integration tests; never contacts attached hardware."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "scripts/workflow/device_session.py"
spec = importlib.util.spec_from_file_location("device_session", MODULE)
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)


class TestConsoleStates(unittest.TestCase):
    def test_android_root(self):
        self.assertEqual(ds.console_state(b"console:/ # "), "shell")

    def test_linux_user(self):
        self.assertEqual(ds.console_state(b"user@armbian:~$ "), "shell")

    def test_uboot_not_a_root_shell(self):
        self.assertEqual(ds.console_state(b"gxlx4_bt203# "), "uboot")

    def test_login_requires_user(self):
        self.assertEqual(ds.console_state(b"armbian login: "), "login-required")

    def test_old_uboot_banner_does_not_override_linux_prompt(self):
        self.assertEqual(ds.console_state(b"U-Boot\nLinux\nconsole:/ # "), "shell")

    def test_no_output(self):
        self.assertEqual(ds.console_state(b"picocom v3.2\nTerminal ready"), "unknown")


class TestTransportArgs(unittest.TestCase):
    @mock.patch.object(ds.shutil, "which", side_effect=lambda cmd: "/usr/bin/" + cmd)
    def test_all_transports_use_fixed_argv(self, _):
        ttl = ds.transport_argv("ttl", "/dev/cu.usbserial1", 921600)
        self.assertEqual(ttl, ["/usr/bin/picocom", "-b", "921600", "-d", "8", "-p", "1", "-f", "n", "/dev/cu.usbserial1"])
        self.assertIn("BatchMode=yes", ds.transport_argv("ssh", "board", 115200))
        self.assertEqual(ds.transport_argv("adb", "192.168.2.150:5555", 115200)[-3:],
                         ["-s", "192.168.2.150:5555", "shell"])

    @mock.patch.object(ds.shutil, "which", return_value="/usr/bin/ssh")
    def test_target_injection_rejected(self, _):
        for target in ("-v", "example;id", "other host"):
            with self.assertRaises(ValueError):
                ds.transport_argv("ssh", target, 115200)

    def test_command_whitelist(self):
        with tempfile.TemporaryDirectory() as directory:
            c = ds.PersistentConsole(["/bin/sh"], Path(directory) / "transcript")
            with self.assertRaises(ValueError):
                c.run_fixed("reboot")


class FakeConsole:
    instances = []

    def __init__(self, argv, transcript):
        self.argv = argv
        self.transcript = Path(transcript)
        self.sent = []
        self.woke = False
        FakeConsole.instances.append(self)

    def __enter__(self):
        self.transcript.write_bytes(b"console:/ # ")
        return self

    def __exit__(self, *args):
        return None

    def observe(self, timeout):
        return "shell" if self.woke else "unknown"

    def wake_blank_line(self):
        self.woke = True

    def run_fixed(self, cmd, timeout):
        self.sent.append(cmd)
        if cmd == ds.IDENTIFY:
            return "ok", b"14\n", 0
        return "ok", b"example\n", 0


class TestCollection(unittest.TestCase):
    @mock.patch.object(ds, "transport_argv", return_value=["picocom", "-b", "921600"])
    def test_ttl_not_probed_without_verified_shell(self, _):
        FakeConsole.instances.clear()
        with tempfile.TemporaryDirectory() as d:
            folder, manifest = ds.run_collection("ttl", "/dev/cu.test", Path(d) / "new", 921600, 3, console_factory=FakeConsole)
            self.assertEqual(manifest["state"], "blocked")
            self.assertEqual(manifest["items"], [])
            self.assertEqual(FakeConsole.instances[-1].sent, [])
            self.assertTrue((folder / "manifest.json").exists())

    @mock.patch.object(ds, "transport_argv", return_value=["picocom", "-b", "921600"])
    def test_explicit_wake_runs_android_probe_in_same_session(self, _):
        FakeConsole.instances.clear()
        with tempfile.TemporaryDirectory() as d:
            folder, manifest = ds.run_collection("ttl", "/dev/cu.test", Path(d) / "new", 921600, 3,
                                                 wake_console=True, console_factory=FakeConsole)
            self.assertEqual(manifest["state"], "complete")
            self.assertEqual(manifest["os_family"], "android")
            inst = FakeConsole.instances[-1]
            self.assertTrue(inst.woke)
            self.assertEqual(len(inst.sent), 1 + len(ds.PROBES["common"]) + len(ds.PROBES["android"]))
            self.assertEqual(len(manifest["items"]), len(inst.sent))
            self.assertEqual(json.loads((folder / "manifest.json").read_text())["state"], "complete")

    @mock.patch.object(ds, "transport_argv", return_value=["picocom"])
    def test_new_directory_cannot_be_reused(self, _):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                ds.run_collection("ttl", "/dev/cu.test", Path(d), 921600, 3, console_factory=FakeConsole)


class TestPTY(unittest.TestCase):
    def test_real_local_pty_shell_marker_and_rejected_command(self):
        with tempfile.TemporaryDirectory() as d:
            with ds.PersistentConsole(["/bin/sh", "-i"], Path(d) / "console.log") as console:
                console.observe(.3)
                status, body, rc = console.run_fixed("uname -a", 5)
                self.assertEqual(status, "ok", (status, body[-200:], rc))
                self.assertIn(b"Linux", body)
                self.assertEqual(rc, 0)
                with self.assertRaises(ValueError):
                    console.run_fixed("rm -rf /tmp")
            self.assertGreater((Path(d) / "console.log").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
