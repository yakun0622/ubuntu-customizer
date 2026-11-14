import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "workflow"))
import w152d_boot_script


class W152dBootScriptTests(unittest.TestCase):
    def test_observed_root_override_and_reject_unknown_target(self):
        script = w152d_boot_script.script_for_root("/dev/sda2")
        self.assertIn(b"root=/dev/sda2 rootwait", script)
        self.assertNotIn(b"root=LABEL=UCROOT", script)
        login_script = w152d_boot_script.script_for_root("/dev/sda2", serial_init=True)
        self.assertNotIn(b"init=/bin/sh", login_script)
        with self.assertRaises(ValueError):
            w152d_boot_script.script_for_root("/dev/mmcblk0p1")
        with self.assertRaises(ValueError):
            w152d_boot_script.script_for_root("LABEL=UCROOT", serial_init=True)

    def test_legacy_header_and_no_internal_storage_commands(self):
        blob = w152d_boot_script.legacy_script()
        self.assertEqual(blob[:4], bytes.fromhex("27051956"))
        self.assertEqual(len(blob[:64]), 64)
        self.assertEqual(int.from_bytes(blob[12:16], "big"), len(blob) - 64)
        self.assertEqual(zlib.crc32(blob[64:]), int.from_bytes(blob[24:28], "big"))
        header = bytearray(blob[:64])
        checksum = int.from_bytes(header[4:8], "big")
        header[4:8] = b"\0" * 4
        self.assertEqual(zlib.crc32(header), checksum)
        self.assertEqual(blob[30], 6)  # U-Boot legacy script type
        self.assertIn(b"booti ", blob)
        self.assertNotIn(b"saveenv", blob)
        self.assertNotIn(b"store write", blob)


if __name__ == "__main__":
    unittest.main()
