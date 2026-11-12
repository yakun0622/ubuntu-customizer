"""Offline ARM USB image builder regression tests (no disks or network)."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile
import shutil
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'uc_arm_image_builder_test', ROOT / 'scripts/workflow/arm_image_builder.py')
img = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(img)


class ArmImageBuilderTests(unittest.TestCase):
    def setUp(self):
        folder = ROOT / 'outputs'
        folder.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.board = 'w152d-' + self.folder.name.lower().replace('_', '-')[:10]
        self.addCleanup(lambda: shutil.rmtree(ROOT / 'outputs/arm-images' / self.board, ignore_errors=True))
        archive = self.folder / 'ubuntu-base-24.04.5-base-arm64.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            data = b'#!/bin/sh\n'
            entry = tarfile.TarInfo('sbin/init')
            entry.mode = 0o755
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        self.archive = archive
        self._official_hash = dict(img.baseline.BASELINE)
        img.baseline.BASELINE['sha256'] = img.sha256(archive)
        self.addCleanup(lambda: img.baseline.BASELINE.update(self._official_hash))
        self.components = {}
        for name in ('kernel', 'dtb', 'boot_script'):
            component = self.folder / (name + '.bin')
            component.write_bytes((name + ' sample').encode())
            self.components[name] = {'file': str(component), 'sha256': img.sha256(component),
                                     'bytes': component.stat().st_size}
        self.candidate = self.folder / 'candidate.json'
        self.candidate.write_text(json.dumps({
            'schema_version': 1, 'type': 'ubuntu-customizer/arm-candidate-stage',
            'board': self.board, 'revision': 1,
            'components': self.components, 'base_archive': str(archive),
            'base_sha256': img.sha256(archive)}))
        self.tools = {}
        for name in ('mkfs.vfat', 'mcopy', 'mmd', 'mke2fs'):
            tool = self.folder / name
            tool.write_text('#!/bin/sh\nexit 0\n')
            tool.chmod(0o700)
            self.tools[name] = str(tool)
        self.commands = []

    def runner(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        self.assertTrue(Path(kwargs['cwd']).is_relative_to(ROOT / 'outputs'))
        self.assertTrue(Path(kwargs['env']['TMPDIR']).is_relative_to(ROOT / 'outputs'))
        if Path(argv[0]).name == 'mke2fs':
            output = Path(argv[-1])
            with output.open('r+b') as stream:
                stream.seek(1080)
                stream.write(b'\x53\xef')
        return subprocess.CompletedProcess(argv, 0, '', '')

    def test_builds_mbr_fat_ext4_image_and_verifiable_manifest(self):
        result = img.build(self.candidate, boot_mib=64, root_mib=256,
                           boot_mode='vendor-script', tools=self.tools,
                           runner=self.runner, approved=True)
        disk = ROOT / result['image']
        self.assertTrue(disk.is_file())
        self.assertEqual(result['sha256'], img.sha256(disk))
        self.assertFalse(result['usb_boot_confirmed'])
        self.assertFalse(result['deployment_allowed'])
        self.assertTrue(result['userspace_init_present'])
        with disk.open('rb') as stream:
            stream.seek(446)
            part1 = stream.read(16)
            part2 = stream.read(16)
            self.assertEqual(part1[4], 0x0C)
            self.assertEqual(part2[4], 0x83)
            first = struct.unpack_from('<I', part1, 8)[0]
            second = struct.unpack_from('<I', part2, 8)[0]
            self.assertEqual(first, 2048)
            self.assertEqual(second, 2048 + 64 * 2048)
            stream.seek(510)
            self.assertEqual(stream.read(2), b'\x55\xaa')
            stream.seek(result['root_partition']['offset'] + 1080)
            self.assertEqual(stream.read(2), b'\x53\xef')
        argv = [' '.join(map(str, command)) for command, _ in self.commands]
        self.assertTrue(any('mke2fs' in command and '-d' in command for command in argv))
        self.assertTrue(any('boot.scr' in command for command in argv))
        self.assertFalse(any('/dev/' in command or 'dd ' in command or 'losetup' in command
                             for command in argv))
        with self.assertRaises(FileExistsError):
            img.build(self.candidate, boot_mib=64, root_mib=256,
                      tools=self.tools, runner=self.runner, approved=True)

    def test_missing_kernel_or_dtb_blocks_prior_to_directory_creation(self):
        stage = json.loads(self.candidate.read_text())
        stage['components'].pop('dtb')
        self.candidate.write_text(json.dumps(stage))
        with self.assertRaisesRegex(ValueError, 'Kernel and DTB'):
            img.build(self.candidate, tools=self.tools, runner=self.runner, approved=True)
        self.assertFalse((ROOT / 'outputs/arm-images' / self.board / 'rev-0001').exists())

    def test_approval_and_external_paths_fail_before_tools(self):
        with self.assertRaises(ValueError):
            img.build(self.candidate, tools=self.tools)
        with self.assertRaises(ValueError):
            img.build('/etc/passwd', tools=self.tools, approved=True)
        tools = dict(self.tools, mke2fs='/usr/sbin/mke2fs')
        with self.assertRaisesRegex(ValueError, 'project-local'):
            img.build(self.candidate, tools=tools, approved=True)

    def test_corrupt_component_rejected_without_disk_write(self):
        (self.folder / 'dtb.bin').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'changed'):
            img.build(self.candidate, tools=self.tools, approved=True)

    def test_tar_traversal_and_link_escape_rejected(self):
        for entry in ('../outside', 'dev/../../outside'):
            with self.subTest(entry=entry):
                tarpath = self.folder / ('unsafe_' + str(len(entry)) + '.tar.gz')
                with tarfile.open(tarpath, 'w:gz') as tar:
                    payload = b'bad'
                    member = tarfile.TarInfo(entry)
                    member.size = len(payload)
                    tar.addfile(member, io.BytesIO(payload))
                with self.assertRaises(ValueError):
                    img.unpack_rootfs(tarpath, self.folder / ('extract_' + str(len(entry))))
        linkpath = self.folder / 'links.tar.gz'
        with tarfile.open(linkpath, 'w:gz') as tar:
            link = tarfile.TarInfo('etc/shadow')
            link.type = tarfile.SYMTYPE
            link.linkname = '../../etc/passwd'
            tar.addfile(link)
        with self.assertRaisesRegex(ValueError, 'link escapes'):
            img.unpack_rootfs(linkpath, self.folder / 'link-extract')

    def test_overlay_rejects_unapproved_file_types(self):
        root = self.folder / 'overlay-root'
        root.mkdir()
        malicious = self.folder / 'unsafe-overlay.tar.gz'
        with tarfile.open(malicious, 'w:gz') as tar:
            body = b'text'
            entry = tarfile.TarInfo('etc/hostname')
            entry.size = len(body)
            tar.addfile(entry, io.BytesIO(body))
        with self.assertRaisesRegex(ValueError, 'modules/firmware'):
            img.apply_driver_overlay(malicious, root, img.sha256(malicious))

    def test_tar_symlinks_are_relative_and_special_nodes_refused(self):
        tarpath = self.folder / 'links-safe.tar.gz'
        with tarfile.open(tarpath, 'w:gz') as tar:
            link = tarfile.TarInfo('etc/mtab')
            link.type = tarfile.SYMTYPE
            link.linkname = '/proc/mounts'
            tar.addfile(link)
        dest = self.folder / 'safe-extract'
        img.unpack_rootfs(tarpath, dest)
        self.assertEqual((dest / 'etc/mtab').readlink().as_posix(), '../proc/mounts')


if __name__ == '__main__':
    unittest.main()
