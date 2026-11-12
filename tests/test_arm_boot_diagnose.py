"""Read-only ARM serial diagnostics, no hardware access."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'uc_arm_boot_diagnose_test', ROOT / 'scripts/workflow/arm_boot_diagnose.py')
diag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diag)


class ArmBootDiagnoseTests(unittest.TestCase):
    def test_boot_stage_classification_and_security(self):
        examples = [
            ('U-Boot 2025.01\nWrong Image Format\n', 'kernel_format'),
            ('U-Boot 2025.01\nStarting kernel ...\n', 'uboot_no_kernel_marker'),
            ('Linux version 6.12.0\nFDT_ERR_NOTFOUND\n', 'dtb'),
            ('Linux version 6.12.0\nVFS: Unable to mount root fs\n', 'rootfs_mount'),
            ('Linux version 6.12.0\nRun /sbin/init as init process\n', 'userspace_observed'),
        ]
        for source, expected in examples:
            with self.subTest(expected=expected):
                result = diag.classify(source + 'password=should-not-leak\n')
                self.assertEqual(result['stage'], expected)
                self.assertFalse(result['boot_confirmed'])
                self.assertFalse(result['deployment_allowed'])
                self.assertNotIn('should-not-leak', json.dumps(result))

    def test_diagnosis_binds_image_and_uart_hash_without_raw_log(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'outputs') as d:
            root = Path(d)
            img = root / 'disk.img'
            img.write_bytes(b'fake usb disk')
            image_manifest = root / 'image-manifest.json'
            image_manifest.write_text(json.dumps({
                'type': 'ubuntu-customizer/arm-usb-image', 'board': 'w152d',
                'revision': 1, 'image': str(img), 'sha256': diag.sha256_file(img),
                'bytes': img.stat().st_size}))
            log = root / 'uart.log'
            log.write_text('U-Boot 2025.01\nWrong Image Format\npassword=secret\n')
            target = root / 'diagnosis.json'
            report = diag.diagnose(image_manifest, log, target)
            self.assertEqual(report['stage'], 'kernel_format')
            self.assertNotIn('secret', target.read_text())
            with self.assertRaises(ValueError):
                diag.diagnose(image_manifest, log, target)
            with self.assertRaises(ValueError):
                diag.diagnose('/etc/passwd', log, root / 'other.json')


if __name__ == '__main__':
    unittest.main()
