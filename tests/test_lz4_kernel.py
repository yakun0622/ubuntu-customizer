import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "workflow"))
import lz4_kernel


class Lz4KernelTests(unittest.TestCase):
    def test_known_xxhash32_vectors(self):
        self.assertEqual(lz4_kernel.xxh32(b""), 0x02CC5D05)
        self.assertEqual(lz4_kernel.xxh32(b"abc"), 0x32D153FF)

    def test_literals_and_overlapping_match(self):
        self.assertEqual(lz4_kernel.block_decode(b"\x40abcd\x04\x00"), b"abcdabcd")
        self.assertEqual(lz4_kernel.block_decode(b"\x11a\x01\x00"), b"aaaaaa")


if __name__ == "__main__":
    unittest.main()
