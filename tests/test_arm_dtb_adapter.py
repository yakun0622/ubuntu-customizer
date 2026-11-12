"""Offline DTB compile/inspect regression tests; no actual host compiler or board."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('uc_arm_dtb_test',
    ROOT / 'scripts/workflow/arm_dtb_adapter.py')
dtb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dtb)


def minimal_fdt(compatible=b'amlogic,gxlx4\0amlogic,s905l4\0'):
    strings = b'compatible\0'
    structure = (struct.pack('>I', 1) + b'\0\0\0\0' +
                 struct.pack('>III', 3, len(compatible), 0) +
                 compatible + b'\0' * (-len(compatible) % 4) +
                 struct.pack('>II', 2, 9))
    offset = 56
    total = offset + len(structure) + len(strings)
    return (struct.pack('>10I', 0xd00dfeed, total, offset,
                        offset + len(structure), 40, 17, 16, 0,
                        len(strings), len(structure)) + b'\0' * 16 +
            structure + strings)


class ArmDtbAdapterTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'outputs').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'outputs')
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.board = 'w152d-' + self.folder.name[-10:].lower().replace('_', '-')
        self.dts = self.folder / 'board.dts'
        self.dts.write_text('/dts-v1/; / { compatible = "amlogic,gxlx4"; };\n')
        self.tool = self.folder / 'dtc'
        self.tool.write_bytes(b'dummy compiler')
        self.tool.chmod(0o700)

    def test_fdt_introspection_is_bounded_and_never_claims_compatibility(self):
        parsed = dtb.inspect_dtb(minimal_fdt())
        self.assertTrue(parsed['w152d_identity_observed'])
        self.assertEqual(parsed['nodes'], 1)
        self.assertFalse(parsed['board_boot_compatible'])
        with self.assertRaises(ValueError):
            dtb.inspect_dtb(b'broken')
        with self.assertRaises(ValueError):
            dtb.inspect_dtb(minimal_fdt()[:-4])

    def test_dtb_compilation_writes_only_a_new_outputs_revision(self):
        def runner(args, **kwargs):
            self.assertEqual(kwargs['env']['HOME'], str(kwargs['cwd']))
            self.assertTrue(kwargs['cwd'].is_relative_to(ROOT / 'outputs'))
            self.assertNotIn('/dev/', ' '.join(args))
            Path(args[6]).write_bytes(minimal_fdt())
            return subprocess.CompletedProcess(args, 0, '', '')
        report = dtb.compile_dts(self.board, 1, self.dts, self.tool,
                                  runner=runner, approved=True)
        self.assertTrue(report['dtb_sha256'])
        self.assertFalse(report['board_boot_compatible'])
        self.assertEqual(report['inspection']['nodes'], 1)
        staged = ROOT / report['dtb']
        self.assertEqual(staged.read_bytes(), minimal_fdt())
        with self.assertRaises(FileExistsError):
            dtb.compile_dts(self.board, 1, self.dts, self.tool,
                            runner=runner, approved=True)

    def test_unapproved_and_external_dts_dtc_rejected(self):
        with self.assertRaises(ValueError):
            dtb.compile_dts(self.board, 2, self.dts, self.tool)
        for args in [('/etc/passwd', self.tool), (self.dts, '/usr/bin/dtc')]:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    dtb.compile_dts(self.board, 2, *args, approved=True)
        link = self.folder / 'escape'
        link.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            dtb.compile_dts(self.board, 2, link, self.tool, approved=True)


if __name__ == '__main__':
    unittest.main()
