#!/usr/bin/env python3
"""Offline ARM USB image builder: MBR + FAT32 boot + ext4 Ubuntu Base rootfs.

Only project-local inputs and outputs. Never opens a block device, flashes
firmware, mounts a host filesystem or claims hardware boot success. Executable
mkfs/mtools dependencies must be provided by an approved, confined Linux
build environment; Python path guards are not an OS sandbox.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent

def sibling(name):
    spec = importlib.util.spec_from_file_location('uc_arm_builder_' + name, HERE / (name + '.py'))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

workspace = sibling('project_workspace')
baseline = sibling('arm_baseline')
fat32 = sibling('arm_fat32')
SECTOR = 512
ALIGN = 2048
MBR_BOOT_TYPE = 0x0C  # FAT32 LBA
MBR_ROOT_TYPE = 0x83  # Linux ext4
MAX_ARCHIVE_MEMBERS = 250000
MAX_ROOT_BYTES = 3 * 1024**3
MAX_OVERLAY_BYTES = 256 * 1024**2
MAX_ROOT_MIB = 8192
MAX_BOOT_MIB = 512
BOOT_FILE_LIMIT = 128 * 1024**2
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,47}\Z')
BOOT = {'kernel': 'Image', 'dtb': 'w152d.dtb', 'initramfs': 'initrd.img',
        'boot_script': 'boot.scr', 'boot_ini': 'boot.ini',
        'aml_autoscript': 'aml_autoscript', 'u_boot_sd': 'u-boot.sd'}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def _relative_tar_name(name):
    if not isinstance(name, str) or '\\' in name or '\x00' in name:
        raise ValueError('Unsafe archive path')
    posix = PurePosixPath(name)
    if posix.is_absolute() or '..' in posix.parts:
        raise ValueError('Archive path escapes the rootfs')
    parts = tuple(p for p in posix.parts if p not in ('', '.'))
    if not parts:
        return None
    return '/'.join(parts)


def _safe_link(name, target):
    if not target or '\\' in target or '\x00' in target:
        raise ValueError('Unsafe archive symlink')
    parent = posixpath.dirname(name)
    intended = (target.lstrip('/') if target.startswith('/')
                else posixpath.join(parent, target))
    normalized = posixpath.normpath(intended)
    if normalized == '..' or normalized.startswith('../'):
        raise ValueError('Archive link escapes rootfs')
    # Absolute guest links must never point to host /etc, /proc or other
    # directories during build; rewrite to an equivalent relative guest link.
    return posixpath.relpath(normalized, parent or '.')


def unpack_rootfs(archive, root, max_bytes=MAX_ROOT_BYTES):
    """Two-pass extraction: validate first; defer symlinks and hardlinks.

    Does not preserve device nodes, suid bits or untrusted xattrs. This is a
    minimal boot candidate; special files are supplied at runtime by devtmpfs.
    """
    root.mkdir(mode=0o700)
    entries = []
    seen = set()
    links = set()
    count = 0
    total = 0
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            name = _relative_tar_name(member.name)
            if name is None:
                continue
            count += 1
            if count > MAX_ARCHIVE_MEMBERS:
                raise ValueError('Too many archive members')
            if name in seen:
                raise ValueError('Duplicate archive path')
            seen.add(name)
            if not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
                raise ValueError('Special archive entries are not supported')
            if member.size < 0 or (member.isfile() and member.size > max_bytes):
                raise ValueError('Oversized archive member')
            if member.isfile():
                total += member.size
                if total > max_bytes:
                    raise ValueError('Expanded rootfs exceeds limit')
            if member.issym() or member.islnk():
                if member.issym():
                    _safe_link(name, member.linkname)
                else:
                    target = _relative_tar_name(member.linkname)
                    if target is None:
                        raise ValueError('Invalid hardlink')
                links.add(name)
            entries.append((member, name))
        # Refuse entries whose parent is a symlink. This prevents extracting a
        # child path through a host symlink before/after deferred link creation.
        for _, name in entries:
            ancestor = name
            while '/' in ancestor:
                ancestor = ancestor.rsplit('/', 1)[0]
                if ancestor in links:
                    raise ValueError('Archive symlink is an ancestor of a member')
        dirs = []
        deferred = []
        for member, name in entries:
            path = root.joinpath(*name.split('/'))
            path.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                path.mkdir(exist_ok=True)
                dirs.append((path, member.mode))
            elif member.isfile():
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError('Archive file payload missing')
                with source, path.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                os.chmod(path, member.mode & 0o777 & ~0o6000)
                if os.geteuid() == 0:
                    os.chown(path, member.uid, member.gid)
            else:
                deferred.append((member, name, path))
        for member, name, path in deferred:
            if member.issym():
                path.symlink_to(_safe_link(name, member.linkname))
                if os.geteuid() == 0:
                    os.chown(path, member.uid, member.gid, follow_symlinks=False)
            else:
                target_name = _relative_tar_name(member.linkname)
                target = root.joinpath(*target_name.split('/'))
                if not target.is_file() or target.is_symlink():
                    raise ValueError('Unsafe or missing archive hardlink target')
                os.link(target, path)
        for path, mode in reversed(dirs):
            path.chmod(mode & 0o777 & ~0o6000)
        if os.geteuid() == 0:
            for member, name in entries:
                if member.isdir():
                    path = root.joinpath(*name.split('/'))
                    os.chown(path, member.uid, member.gid)
    return {'members': count, 'expanded_bytes': total, 'suid_removed': True,
            'host_device_nodes_created': False, 'ownership_preserved': os.geteuid() == 0}


def apply_driver_overlay(archive, root, expected_sha256):
    """Copy project-supplied driver files only into /usr/lib/modules/firmware.

    Overlay is optional and versioned by its caller-provided SHA-256. No
    scripts are executed and no paths outside the staged rootfs are opened.
    """
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha256 or ''):
        raise ValueError('Driver overlay requires a trusted SHA-256')
    tarpath = workspace.checked_input(archive, max_bytes=MAX_OVERLAY_BYTES)
    if sha256(tarpath) != expected_sha256.lower():
        raise ValueError('Driver overlay checksum mismatch')
    total = 0
    with tarfile.open(tarpath, 'r:gz') as tar:
        entries = []
        for member in tar:
            name = _relative_tar_name(member.name)
            if name is None:
                continue
            if not (name.startswith('usr/lib/modules/') or
                    name.startswith('usr/lib/firmware/') or
                    name in ('usr', 'usr/lib', 'usr/lib/modules', 'usr/lib/firmware')):
                raise ValueError('Driver overlay may change modules/firmware only')
            if not (member.isdir() or member.isfile()):
                raise ValueError('Driver overlay cannot contain links or special files')
            total += member.size
            if total > MAX_OVERLAY_BYTES:
                raise ValueError('Driver overlay expanded beyond limit')
            dest = root.joinpath(*name.split('/'))
            if not dest.resolve(strict=False).is_relative_to(root.resolve()):
                raise ValueError('Driver overlay escapes staged root')
            entries.append((member, dest))
        for member, dest in entries:
            if member.isdir():
                if dest.is_symlink():
                    raise ValueError('Driver directory is a symlink')
                dest.mkdir(parents=True, exist_ok=True)
            else:
                if dest.exists() or dest.is_symlink():
                    raise ValueError('Driver overlay must not overwrite existing files')
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.resolve(strict=False).is_relative_to(root.resolve()):
                    raise ValueError('Driver overlay traverses a symlink')
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError('Driver payload missing')
                with source, dest.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                dest.chmod(member.mode & 0o777 & ~0o6000)
                if os.geteuid() == 0:
                    os.chown(dest, member.uid, member.gid)
    return {'sha256': expected_sha256.lower(), 'bytes': tarpath.stat().st_size,
            'expanded_bytes': total}


def mbr_bytes(boot_mib, root_mib):
    """Create a conventional USB MBR with 1 MiB aligned FAT32/ext4 entries."""
    if not 64 <= boot_mib <= MAX_BOOT_MIB or not 256 <= root_mib <= MAX_ROOT_MIB:
        raise ValueError('Partition size outside permitted bounds')
    start_boot = ALIGN
    sectors_boot = boot_mib * 2048
    start_root = start_boot + sectors_boot
    sectors_root = root_mib * 2048
    total = start_root + sectors_root + ALIGN
    if total > 0xffffffff:
        raise ValueError('MBR 2TiB limit exceeded')
    mbr = bytearray(SECTOR)
    for index, (start, count, kind) in enumerate(((start_boot, sectors_boot, MBR_BOOT_TYPE),
                                                   (start_root, sectors_root, MBR_ROOT_TYPE))):
        offset = 446 + index * 16
        mbr[offset:offset+16] = struct.pack('<B3sB3sII', 0, b'\xfe\xff\xff', kind,
                                            b'\xfe\xff\xff', start, count)
    mbr[510:] = b'\x55\xaa'
    return bytes(mbr), start_boot * SECTOR, start_root * SECTOR, total * SECTOR


def _tools(provided=None):
    """Only mke2fs is required; the FAT32 implementation is pure Python.

    Older projects may explicitly pass all three mtools binaries to keep
    their historical workflow. Partial explicit overrides fail closed.
    """
    provided = dict(provided or {})
    legacy = ('mkfs.vfat', 'mcopy', 'mmd')
    selected = tuple(legacy) + ('mke2fs',) if any(provided.get(k) for k in legacy) else ('mke2fs',)
    if any(provided.get(k) for k in legacy) and not all(provided.get(k) for k in legacy):
        raise ValueError('Legacy mtools backend requires mkfs.vfat, mcopy and mmd together')
    result = {}
    for name in selected:
        try:
            binary = workspace.checked_input(provided.get(name))
        except (ValueError, TypeError, OSError) as exc:
            raise ValueError('Approved project-local build tool missing: ' + name) from exc
        if not os.access(binary, os.X_OK):
            raise ValueError('Build tool is not executable: ' + name)
        result[name] = str(binary)
    return result


def _run(argv, cwd, runner=subprocess.run):
    # External dependencies may read their runtimes/configurations. Launch the
    # caller-approved sandbox with only this project mounted for local data.
    environment = {'PATH': '', 'HOME': str(cwd), 'TMPDIR': str(cwd),
                   'MTOOLSRC': str(cwd / 'mtools.conf'),
                   'MKE2FS_CONFIG': str(cwd / 'mke2fs.conf'),
                   'LANG': 'C', 'LC_ALL': 'C'}
    proc = runner(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                  capture_output=True, text=True, timeout=180, check=False)
    if proc.returncode:
        raise RuntimeError('Offline filesystem command failed: ' + Path(argv[0]).name)


def _write_stage_boot(stage, components, board, boot_mode, root_label, cmdline):
    boot = stage / 'boot-files'
    boot.mkdir()
    for part, filename in BOOT.items():
        if part not in components:
            continue
        src = components[part]
        with src.open('rb') as stream, (boot / filename).open('xb') as output:
            shutil.copyfileobj(stream, output, 1024 * 1024)
    if boot_mode == 'extlinux':
        extlinux = boot / 'extlinux'
        extlinux.mkdir()
        lines = ['DEFAULT ubuntu', 'TIMEOUT 30', 'LABEL ubuntu',
                 '  LINUX /Image', '  FDT /w152d.dtb']
        if 'initramfs' in components:
            lines.append('  INITRD /initrd.img')
        lines.append('  APPEND root=LABEL=' + root_label + ' rootwait rw ' + cmdline)
        (extlinux / 'extlinux.conf').write_text('\n'.join(lines) + '\n', encoding='ascii')
    return boot


def _copy_at(image, payload, offset):
    with payload.open('rb') as source, image.open('r+b') as target:
        target.seek(offset)
        shutil.copyfileobj(source, target, 1024 * 1024)


def read_candidate(value):
    manifest = workspace.checked_input(value, max_bytes=1024 * 1024)
    candidate = json.loads(manifest.read_text(encoding='utf-8'))
    if (candidate.get('type') != 'ubuntu-customizer/arm-candidate-stage'
            or candidate.get('schema_version') != 1 or
            not NAME.fullmatch(candidate.get('board', '')) or
            not isinstance(candidate.get('revision'), int)):
        raise ValueError('Invalid ARM candidate manifest')
    parts = candidate.get('components')
    if not isinstance(parts, dict) or set(parts) - {'kernel', 'dtb', 'boot_script',
                                                  'initramfs', 'bootloader', 'firmware',
                                                  'boot_ini', 'aml_autoscript', 'u_boot_sd'}:
        raise ValueError('Invalid board components')
    inputs = {}
    for key, item in parts.items():
        if not isinstance(item, dict):
            raise ValueError('Invalid component metadata')
        path = workspace.checked_input(item.get('file'), max_bytes=BOOT_FILE_LIMIT)
        if sha256(path) != item.get('sha256') or path.stat().st_size != item.get('bytes'):
            raise ValueError('Candidate component changed: ' + key)
        inputs[key] = path
    return manifest, candidate, inputs


def build(candidate_manifest, *, boot_mib=128, root_mib=1024,
          boot_mode='extlinux', cmdline='console=ttyS0,921600',
          overlay=None, overlay_sha256=None,
          tools=None, runner=subprocess.run, approved=False):
    """Build one non-overwriting USB IMG candidate; no direct device writes."""
    if not approved:
        raise ValueError('Explicit offline image-build approval required')
    if boot_mode not in ('extlinux', 'vendor-script'):
        raise ValueError('Unsupported board boot method')
    if not re.fullmatch(r'[a-zA-Z0-9_.,=:/ -]{1,200}', cmdline) or '\n' in cmdline:
        raise ValueError('Unsafe kernel command line')
    toolset = _tools(tools)
    manifest_file, candidate, components = read_candidate(candidate_manifest)
    for necessary in ('kernel', 'dtb'):
        if necessary not in components:
            raise ValueError('Kernel and DTB must be staged before IMG build')
    if boot_mode == 'vendor-script' and 'boot_script' not in components:
        raise ValueError('Vendor boot script is required for script boot')
    # No built-in assumption that gxlx4 uses the ordinary extlinux path.
    source = workspace.checked_input(candidate['base_archive'], max_bytes=128 * 1024 * 1024)
    if candidate['base_sha256'] != baseline.BASELINE['sha256']:
        raise ValueError('Candidate does not use the pinned official Ubuntu Base')
    if sha256(source) != candidate['base_sha256']:
        raise ValueError('Pinned Ubuntu Base has changed')
    if source.name != baseline.BASELINE['filename']:
        raise ValueError('Only supported pinned ARM64 baseline is allowed')
    mbr, boot_offset, root_offset, image_bytes = mbr_bytes(boot_mib, root_mib)
    if bool(overlay) != bool(overlay_sha256):
        raise ValueError('Driver overlay path and SHA-256 must be supplied together')
    root_bytes = root_mib * 1024 * 1024
    # Use an immutable new revision directory and a private intermediate area.
    parent = workspace.output_path('arm-images', candidate['board'])
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = workspace.output_path('arm-images', candidate['board'],
                                   'rev-%04d' % candidate['revision'])
    target.mkdir(mode=0o700)  # refuses overwrite
    try:
        tmp = target / 'work'
        tmp.mkdir(mode=0o700)
        (tmp / 'mtools.conf').write_text('', encoding='ascii')
        # Minimal self-contained e2fsprogs configuration; no /etc read.
        (tmp / 'mke2fs.conf').write_text('[defaults]\nbase_features = sparse_super,filetype,resize_inode,dir_index,ext_attr\n', encoding='ascii')
        root = tmp / 'rootfs'
        inventory = unpack_rootfs(source, root, max_bytes=min(MAX_ROOT_BYTES, root_bytes))
        driver_overlay = (apply_driver_overlay(overlay, root, overlay_sha256)
                          if overlay is not None else None)
        # Minimum static rootfs initialization; never chroot or execute guest code.
        (root / 'etc').mkdir(exist_ok=True)
        (root / 'etc' / 'fstab').write_text('LABEL=UCROOT / ext4 defaults,noatime 0 1\n', encoding='ascii')
        (root / 'etc' / 'hostname').write_text(candidate['board'] + '\n', encoding='ascii')
        (root / 'boot').mkdir(exist_ok=True)
        boot = _write_stage_boot(tmp, components, candidate['board'], boot_mode,
                                 'UCROOT', cmdline)
        bootimg = tmp / 'boot.fat'
        rootimg = tmp / 'root.ext4'
        with bootimg.open('xb') as f:
            f.truncate(boot_mib * 1024 * 1024)
        with rootimg.open('xb') as f:
            f.truncate(root_bytes)
        if 'mkfs.vfat' in toolset:
            _run([toolset['mkfs.vfat'], '-F', '32', '-n', 'UCBOOT', str(bootimg)], tmp, runner)
            boot_contents = None
        else:
            # Portable, real FAT32 filesystem with VFAT long filename support.
            # Uses only Python stdlib; avoids three host executables on macOS.
            boot_contents = fat32.write_fat32(boot, bootimg, volume_label='UCBOOT')
        _run([toolset['mke2fs'], '-F', '-t', 'ext4', '-L', 'UCROOT', '-d',
              str(root), str(rootimg)], tmp, runner)
        if 'mkfs.vfat' in toolset:
            for item in sorted(boot.rglob('*')):
                rel = item.relative_to(boot).as_posix()
                if item.is_dir():
                    _run([toolset['mmd'], '-i', str(bootimg), '::/' + rel], tmp, runner)
                else:
                    _run([toolset['mcopy'], '-i', str(bootimg), str(item), '::/' + rel], tmp, runner)
        img = target / ('%s-r%04d-usb.img' % (candidate['board'], candidate['revision']))
        with img.open('xb') as disk:
            disk.truncate(image_bytes)
            disk.seek(0)
            disk.write(mbr)
        _copy_at(img, bootimg, boot_offset)
        _copy_at(img, rootimg, root_offset)
        with img.open('rb') as disk:
            disk.seek(510)
            if disk.read(2) != b'\x55\xaa':
                raise RuntimeError('Missing MBR signature')
            disk.seek(root_offset + 1024 + 56)
            if disk.read(2) != b'\x53\xef':
                raise RuntimeError('Expected ext4 superblock not found')
        # Boot components are staged and validated but the SoC's USB boot flow
        # still requires a real U-Boot log and a verified vendor-specific path.
        has_init = any((root / p).exists() for p in ('sbin/init', 'lib/systemd/systemd',
                                                     'usr/lib/systemd/systemd'))
        report = {
            'schema_version': 1, 'type': 'ubuntu-customizer/arm-usb-image',
            'board': candidate['board'], 'revision': candidate['revision'],
            'format': 'raw', 'partition_table': 'mbr',
            'boot_partition': {'filesystem': 'fat32', 'offset': boot_offset, 'label': 'UCBOOT'},
            'root_partition': {'filesystem': 'ext4', 'offset': root_offset, 'label': 'UCROOT'},
            'image': str(img.relative_to(workspace.project_root())),
            'bytes': image_bytes, 'sha256': sha256(img),
            'candidate_manifest_sha256': sha256(manifest_file),
            'rootfs': inventory, 'driver_overlay': driver_overlay,
            'boot_filesystem_backend': ('legacy-mtools' if 'mkfs.vfat' in toolset
                                        else 'python-fat32'),
            'boot_filesystem_details': boot_contents,
            'userspace_init_present': has_init,
            'boot_mode': boot_mode, 'boot_script_verified_on_hardware': False,
            'usb_boot_confirmed': False, 'deployment_allowed': False,
            'missing_gates': ['physical_usb_boot_log', 'bootloader_load_path',
                              'board_driver_functionality'] + ([] if has_init else ['userspace_init']),
            'notes': ['Image was assembled offline only; eMMC untouched',
                      'Bootloader payload never written to raw boot sectors',
                      'Vendor boot support and rootfs ownership need real device validation'],
        }
        (target / 'image-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
        shutil.rmtree(tmp)
        return report
    except BaseException:
        # This is the newly created revision only; no existing build is touched.
        shutil.rmtree(target)
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('candidate', help='project-local candidate.json')
    p.add_argument('--boot-mib', type=int, default=128)
    p.add_argument('--root-mib', type=int, default=1024)
    p.add_argument('--boot-mode', choices=('extlinux', 'vendor-script'), default='extlinux')
    p.add_argument('--cmdline', default='console=ttyS0,921600')
    p.add_argument('--driver-overlay', help='Project-local gzip tar of usr/lib/modules or firmware')
    p.add_argument('--driver-overlay-sha256', help='Trusted overlay archive SHA-256')
    for name in ('mkfs.vfat', 'mcopy', 'mmd', 'mke2fs'):
        p.add_argument('--tool-' + name.replace('.', '-'), required=name == 'mke2fs',
                       help='Project-local executable; only mke2fs is required (Python FAT32 is default)')
    p.add_argument('--approved', action='store_true')
    args = p.parse_args(argv)
    try:
        tools = {name: getattr(args, 'tool_' + name.replace('.', '_').replace('-', '_'))
                 for name in ('mkfs.vfat', 'mcopy', 'mmd', 'mke2fs')
                 if getattr(args, 'tool_' + name.replace('.', '_').replace('-', '_'))}
        result = build(args.candidate, boot_mib=args.boot_mib, root_mib=args.root_mib,
                       boot_mode=args.boot_mode, cmdline=args.cmdline,
                       overlay=args.driver_overlay, overlay_sha256=args.driver_overlay_sha256,
                       tools=tools, approved=args.approved)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, tarfile.TarError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
