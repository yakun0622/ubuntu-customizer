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
        self.assertTrue(any('-O has_journal,extent' in command for command in argv))
        self.assertTrue(any('boot.scr' in command for command in argv))
        self.assertFalse(any('/dev/' in command or 'dd ' in command or 'losetup' in command
                             for command in argv))
        with self.assertRaises(FileExistsError):
            img.build(self.candidate, boot_mib=64, root_mib=256,
                      tools=self.tools, runner=self.runner, approved=True)

    def test_portable_fat32_build_requires_only_project_mke2fs(self):
        image = img.build(self.candidate, boot_mib=64, root_mib=256,
                          boot_mode='vendor-script',
                          tools={'mke2fs': self.tools['mke2fs']},
                          runner=self.runner, approved=True)
        self.assertEqual(image['boot_filesystem_backend'], 'python-fat32')
        self.assertGreaterEqual(image['boot_filesystem_details']['clusters'], 65525)
        self.assertEqual(len(self.commands), 1)
        self.assertIn('mke2fs', self.commands[0][0][0])
        with (ROOT / image['image']).open('rb') as data:
            data.seek(image['boot_partition']['offset'])
            vbr = data.read(512)
        self.assertEqual(vbr[82:90], b'FAT32   ')
        self.assertEqual(vbr[71:82], b'UCBOOT     ')
        self.assertEqual(vbr[510:512], bytes.fromhex('55aa'))

    def test_serial_init_accepts_only_fixed_w152d_payload_and_boot_root(self):
        root = self.folder / 'rootfs'
        (root / 'usr/sbin').mkdir(parents=True)
        init_file = self.folder / 'serial-init'
        init_file.write_bytes(img.serial_init.SCRIPT)
        boot_file = self.folder / 'boot-script'
        boot_file.write_bytes(b'root=/dev/sda2 rootwait rw\nbooti 0x0a000000 - 0x01000000\n')
        components = {'init_script': init_file, 'boot_script': boot_file}
        self.assertTrue(img.install_serial_init(root, components, 'w152d', 'vendor-script'))
        self.assertEqual((root / 'usr/sbin/init').read_bytes(), img.serial_init.SCRIPT)
        init_file.write_bytes(b'#!/bin/sh\nunsafe command\n')
        with self.assertRaisesRegex(ValueError, 'Unverified W152D'):
            img.install_serial_init(root, components, 'w152d', 'vendor-script')

    def test_partial_legacy_fat_tools_rejected(self):
        with self.assertRaisesRegex(ValueError, 'requires mkfs.vfat'):
            img.build(self.candidate, tools={
                'mkfs.vfat': self.tools['mkfs.vfat'],
                'mke2fs': self.tools['mke2fs']}, approved=True)

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

    def test_deb_bundle_and_ssh_authorized_key_staging_and_guards(self):
        deb_bundle = self.folder / 'debs.tar.gz'
        with tarfile.open(deb_bundle, 'w:gz') as tar:
            payload = b'!<arch>\ndebian-binary\n'
            info = tarfile.TarInfo('var/cache/uc-debs/kmod_31_arm64.deb')
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        deb_sha = img.sha256(deb_bundle)

        key_file = self.folder / 'id_ed25519.pub'
        key_line = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE6mxdrIYfeaIlG/E8i1O218DaFy0uDN2B32RZTPzXsA user@example'
        key_file.write_text(key_line + '\n', encoding='utf-8')

        captured = {}
        orig_runner = self.runner

        def inspect_runner(argv, **kwargs):
            if Path(argv[0]).name == 'mke2fs':
                root_dir = Path(argv[argv.index('-d') + 1])
                captured['deb_exists'] = (root_dir / 'var/cache/uc-debs/kmod_31_arm64.deb').is_file()
                captured['auth_keys'] = (root_dir / 'root/.ssh/authorized_keys').read_text('utf-8')
                captured['sshd_dropin'] = (root_dir / 'etc/ssh/sshd_config.d/99-uc-pubkey.conf').read_text('utf-8')
            return orig_runner(argv, **kwargs)

        res = img.build(
            self.candidate,
            boot_mib=64,
            root_mib=256,
            boot_mode='vendor-script',
            deb_bundle=str(deb_bundle),
            deb_bundle_sha256=deb_sha,
            ssh_authorized_key_file=str(key_file),
            tools={'mke2fs': self.tools['mke2fs']},
            runner=inspect_runner,
            approved=True,
        )
        self.assertTrue(captured['deb_exists'])
        self.assertEqual(captured['auth_keys'], key_line + '\n')
        self.assertIn('PasswordAuthentication no', captured['sshd_dropin'])
        self.assertEqual(res['deb_bundle']['deb_count'], 1)
        self.assertEqual(res['ssh_authorized_key']['key_type'], 'ssh-ed25519')

        # Reject authorized_keys command="" injection options and invalid .deb headers.
        bad_key = self.folder / 'bad_key.pub'
        bad_key.write_text('command="/bin/sh" ' + key_line + '\n', encoding='utf-8')
        root = self.folder / 'key-root'
        root.mkdir()
        with self.assertRaisesRegex(ValueError, 'Invalid or unsafe OpenSSH'):
            img.install_ssh_authorized_key(bad_key, root)

        bad_deb = self.folder / 'bad-debs.tar.gz'
        with tarfile.open(bad_deb, 'w:gz') as tar:
            payload = b'not-an-ar-archive'
            info = tarfile.TarInfo('var/cache/uc-debs/evil_1_arm64.deb')
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        with self.assertRaisesRegex(ValueError, 'ar header'):
            img.apply_deb_bundle(bad_deb, root, img.sha256(bad_deb))


if __name__ == '__main__':
    unittest.main()
