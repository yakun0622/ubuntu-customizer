"""Unit tests for W152D FDT USB GPIO patching and optional tail slack."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "w152d_usb_dtb", ROOT / "scripts/workflow/w152d_usb_dtb.py")
dtb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dtb)


def _minimal_w152d_fdt():
    # Strings table: "gpios\0default-state\0"
    strings = b"gpios\x00default-state\x00"
    gpios_off = 0
    def_off = 6
    s = bytearray()

    def begin(name):
        s.extend(struct.pack(">I", 1))
        raw = name.encode("ascii") + b"\x00"
        s.extend(raw)
        while len(s) % 4:
            s.append(0)

    def prop(noff, payload):
        s.extend(struct.pack(">III", 3, len(payload), noff))
        s.extend(payload)
        while len(s) % 4:
            s.append(0)

    def end():
        s.extend(struct.pack(">I", 2))

    begin("")
    begin("gpio_leds")
    for n in (1, 2, 3):
        begin(f"usb2_{n}_enable")
        prop(gpios_off, struct.pack(">III", 0x1d, 29 + n, 0))
        prop(def_off, b"off\x00")
        end()
    end()
    end()
    s.extend(struct.pack(">I", 9))

    rsvmap = b"\x00" * 16
    off_rsv = 40
    off_struct = off_rsv + len(rsvmap)
    off_strings = off_struct + len(s)
    total = off_strings + len(strings)
    header = struct.pack(
        ">10I", 0xd00dfeed, total, off_struct, off_strings, off_rsv,
        17, 16, 0, len(strings), len(s))
    return header + rsvmap + bytes(s) + strings


class W152dUsbDtbTests(unittest.TestCase):
    def test_patches_usb_gpios_and_supports_aligned_extra_space(self):
        fake = _minimal_w152d_fdt()
        digest = hashlib.sha256(fake).hexdigest()
        with mock.patch.object(dtb, "ORIGINAL_SHA256", digest):
            exact = dtb.patch(fake, extra_space=0)
            self.assertEqual(len(exact), len(fake))
            self.assertNotIn(b"off\x00", exact)
            self.assertEqual(exact.count(b"on\x00\x00"), 3)

            padded = dtb.patch(fake, extra_space=8192)
            new_total = struct.unpack_from(">I", padded, 4)[0]
            self.assertEqual(new_total, len(padded))
            self.assertEqual(new_total % 4, 0)
            self.assertGreaterEqual(new_total - len(fake), 8192)
            self.assertEqual(padded[:56][8:], exact[:56][8:])
            with self.assertRaisesRegex(ValueError, "Invalid extra FDT space"):
                dtb.patch(fake, extra_space=3)


if __name__ == "__main__":
    unittest.main()
