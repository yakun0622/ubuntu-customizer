#!/usr/bin/env python3
"""Evidence-bound ARM USB-boot diagnosis with non-destructive next-step hints.

Never writes or reads device nodes, sends UART data, or infers trusted boot
from an unauthenticated serial capture. Operates only on project-local files.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'uc_arm_diag_workspace', HERE / 'project_workspace.py')
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)

MAX_BYTES = 4 * 1024 * 1024

RULES = (
    ('kernel_panic_rootfs', r'(?:VFS: Unable to mount root fs|unknown-block\(|Waiting for root device)',
     'rootfs_mount', 'Check root=LABEL=UCROOT, ext4 built-in support, and USB storage initialization'),
    ('dtb_failure', r'(?:FDT_ERR|Bad device tree|ERROR: Did not find a cmdline Flattened Device Tree)',
     'dtb', 'Compare DTB compatible/regulator/clock nodes and U-Boot FDT load address'),
    ('kernel_image_failure', r'(?:Bad Magic Number|Wrong Image Format|Bad Linux ARM64 Image magic)',
     'kernel_format', 'Check selected kernel format and U-Boot booti vs bootm command'),
    ('kernel_panic', r'(?:Kernel panic|not syncing:)',
     'kernel', 'Inspect panic context; preserve the last known working kernel and DTB'),
    ('init_failure', r'(?:Failed to execute /sbin/init|No working init found|Requested init .* failed)',
     'userspace', 'Provide ARM64 init/systemd and required shared libraries in the root filesystem'),
    ('usb_io_failure', r'(?:USB device descriptor read/64, error|Buffer I/O error on dev sd|reset .* USB device)',
     'usb', 'Compare USB VBUS GPIO, controller reset/clock and PHY drivers against working boot'),
    ('ethernet_rx_issue', r'(?:mmc_rx_crc_error|mmc_rx_align_error|rx_framecount_gb: 0)',
     'ethernet', 'Compare MDIO PHY address, RGMII delays, RX clock, interrupts and reset GPIO'),
)


def sha256_file(path):
    sha = hashlib.sha256()
    with path.open('rb') as f:
        for buf in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(buf)
    return sha.hexdigest()


def classify(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_BYTES * 3:
        raise ValueError('Invalid serial log')
    lines = raw.splitlines()
    matches = []
    for key, pattern, stage, action in RULES:
        regex = re.compile(pattern, re.IGNORECASE)
        found = next((index for index, line in enumerate(lines, 1)
                      if regex.search(line[:2000])), None)
        if found is not None:
            matches.append({'code': key, 'stage': stage, 'line': found,
                            'action': action})
    has_uboot = any(re.search(r'\bU-Boot\s+(?:20\d\d|v20\d\d)', x, re.I)
                    for x in lines)
    kernel = any(re.search(r'\bLinux version\s+\d', x, re.I) for x in lines)
    userspace = any(re.search(r'(?:Run /sbin/init|systemd\[1\]|login:\s*$)', x, re.I)
                    for x in lines)
    if matches:
        primary = matches[0]['stage']
    elif kernel and userspace:
        primary = 'userspace_observed'
    elif kernel:
        primary = 'kernel_started'
    elif has_uboot:
        primary = 'uboot_no_kernel_marker'
    else:
        primary = 'no_identifiable_boot_markers'
    if not matches:
        next_step = {
            'userspace_observed': 'Inspect peripheral drivers; capture authenticated live health separately',
            'kernel_started': 'Capture later serial messages and check rootfs/init',
            'uboot_no_kernel_marker': 'Review USB boot script, kernel/dtb load address and UART baud transition',
            'no_identifiable_boot_markers': 'Capture complete UART log from power on, using verified serial settings',
        }[primary]
    else:
        next_step = matches[0]['action']
    return {'stage': primary, 'diagnoses': matches,
            'uboot_observed': has_uboot, 'kernel_observed': kernel,
            'userspace_observed': userspace,
            'boot_confirmed': False, 'deployment_allowed': False,
            'next_action': next_step}


def diagnose(image_manifest, log_file, report_file):
    manifest_path = workspace.checked_input(image_manifest, max_bytes=1024 * 1024)
    log = workspace.checked_input(log_file, max_bytes=MAX_BYTES)
    destination = workspace.checked_output(report_file)
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError('Diagnosis report must be a new file inside outputs')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('type') != 'ubuntu-customizer/arm-usb-image':
        raise ValueError('Expected a built ARM USB image manifest')
    image = workspace.checked_input(manifest.get('image'))
    if sha256_file(image) != manifest.get('sha256') or image.stat().st_size != manifest.get('bytes'):
        raise ValueError('ARM image has changed since build')
    result = {'schema_version': 1,
              'type': 'ubuntu-customizer/arm-boot-diagnosis',
              'board': manifest['board'], 'revision': manifest['revision'],
              'image_sha256': manifest['sha256'],
              'boot_log_sha256': sha256_file(log),
              'log_provenance': 'user-supplied, unauthenticated',
              **classify(log.read_bytes())}
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    destination.chmod(0o600)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image-manifest', required=True)
    p.add_argument('--serial-log', required=True)
    p.add_argument('--report', required=True)
    args = p.parse_args(argv)
    try:
        print(json.dumps(diagnose(args.image_manifest, args.serial_log, args.report), indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
