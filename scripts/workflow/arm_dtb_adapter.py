#!/usr/bin/env python3
"""Inspect or compile W152D DTS/DTB inside the current project only.

This utility does not modify an attached device, flash storage, or invent
missing regulator/pinctrl properties. A compiled DTB is not proven compatible.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ws = importlib.util.spec_from_file_location('uc_arm_dtb_workspace', HERE / 'project_workspace.py')
workspace = importlib.util.module_from_spec(ws)
ws.loader.exec_module(workspace)

MAX_DTB = 4 * 1024 * 1024
MAX_DTS = 4 * 1024 * 1024


def sha256(path):
    obj = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            obj.update(part)
    return obj.hexdigest()


def inspect_dtb(blob):
    if len(blob) < 40 or len(blob) > MAX_DTB:
        raise ValueError('Unsupported DTB size')
    fields = struct.unpack('>10I', blob[:40])
    magic, size, structs, strings, reserves, version, compatible, cpu, str_len, struct_len = fields
    if magic != 0xd00dfeed or size > len(blob) or size < 40 or version < 16:
        raise ValueError('Invalid FDT header')
    if (structs < 40 or strings < 40 or structs + struct_len > size or
            strings + str_len > size or reserves >= size):
        raise ValueError('FDT sections out of bounds')
    text = blob[strings:strings + str_len]
    struct_data = blob[structs:structs + struct_len]
    index, depth, nodes = 0, 0, 0
    properties = {}
    end_seen = False
    while index + 4 <= len(struct_data):
        token = struct.unpack_from('>I', struct_data, index)[0]
        index += 4
        if token == 1:  # BEGIN_NODE
            at = struct_data.find(b'\0', index)
            if at == -1:
                raise ValueError('Unterminated DTB node')
            index = (at + 4) & ~3
            if index > len(struct_data):
                raise ValueError('Truncated DTB node')
            depth += 1
            nodes += 1
        elif token == 2:  # END_NODE
            depth -= 1
            if depth < 0:
                raise ValueError('Invalid DTB tree nesting')
        elif token == 3:  # PROP
            if index + 8 > len(struct_data):
                raise ValueError('Truncated DTB property')
            length, nameoff = struct.unpack_from('>II', struct_data, index)
            index += 8
            at = text.find(b'\0', nameoff)
            if nameoff >= len(text) or at < 0 or length > len(struct_data) - index:
                raise ValueError('Invalid DTB property bounds')
            key = text[nameoff:at].decode('ascii', 'replace')
            if depth == 1 and key in ('compatible', 'model', 'amlogic-dt-id'):
                data = struct_data[index:index + length]
                if len(data) > 2048:
                    raise ValueError('Oversized DTB board identifier')
                properties[key] = [x.decode('utf-8', 'replace') for x in
                                   data.rstrip(b'\0').split(b'\0') if x]
            index = (index + length + 3) & ~3
        elif token == 4:  # NOP
            continue
        elif token == 9:  # END
            if depth != 0:
                raise ValueError('Unbalanced DTB tree')
            end_seen = True
            break
        else:
            raise ValueError('Unknown FDT structure token')
    if not end_seen or nodes == 0:
        raise ValueError('Incomplete DTB structure')
    signature = ' '.join(sum(properties.values(), [])).lower()
    return {'fdt_version': version, 'nodes': nodes, 'total_bytes': size,
            'root_properties': properties,
            'w152d_identity_observed': ('s905l4' in signature or 'gxlx4' in signature),
            'board_boot_compatible': False}


def compile_dts(board, revision, dts_path, dtc_tool, *, runner=subprocess.run,
                approved=False):
    if not approved:
        raise ValueError('DTB compilation requires explicit offline approval')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', board) or not 1 <= revision <= 9999:
        raise ValueError('Invalid board/revision')
    dts = workspace.checked_input(dts_path, max_bytes=MAX_DTS)
    tool = workspace.checked_input(dtc_tool)
    if not os.access(tool, os.X_OK):
        raise ValueError('Project-local dtc is not executable')
    base = workspace.output_path('arm-dtb', board)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = workspace.output_path('arm-dtb', board, 'rev-%04d' % revision)
    folder.mkdir(mode=0o700)  # no overwrite
    out = folder / 'board.dtb'
    try:
        env = {'PATH': '', 'HOME': str(folder), 'TMPDIR': str(folder), 'LANG': 'C'}
        result = runner([str(tool), '-I', 'dts', '-O', 'dtb', '-o', str(out), str(dts)],
                        cwd=folder, env=env, stdin=subprocess.DEVNULL,
                        capture_output=True, text=True, timeout=90, check=False)
        if result.returncode != 0:
            raise RuntimeError('Project-local dtc compilation failed')
        validated = workspace.checked_input(out, max_bytes=MAX_DTB)
        details = inspect_dtb(validated.read_bytes())
        report = {'schema_version': 1, 'type': 'ubuntu-customizer/arm-dtb-revision',
                  'board': board, 'revision': revision,
                  'source_sha256': sha256(dts),
                  'dtb': str(out.relative_to(workspace.project_root())),
                  'dtb_sha256': sha256(out), 'inspection': details,
                  'board_boot_compatible': False,
                  'next_action': 'stage_new_candidate_and_test_usb'}
        summary = folder / 'dtb-report.json'
        summary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        summary.chmod(0o600)
        return report
    except BaseException:
        # Only remove this new revision; preserve previous validated versions.
        import shutil
        shutil.rmtree(folder)
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board', default='w152d')
    p.add_argument('--revision', type=int, required=True)
    p.add_argument('--dts', required=True)
    p.add_argument('--tool-dtc', required=True)
    p.add_argument('--approved', action='store_true')
    args = p.parse_args(argv)
    try:
        print(json.dumps(compile_dts(args.board, args.revision, args.dts,
                                     args.tool_dtc, approved=args.approved), indent=2))
        return 0
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
