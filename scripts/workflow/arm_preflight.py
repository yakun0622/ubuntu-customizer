#!/usr/bin/env python3
"""Project-only, read-only readiness audit for ARM64 candidate construction.

Does not scan PATH, search host drives, spawn tools, or install dependencies.
May write one explicitly requested report beneath ./outputs.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys

HERE = Path(__file__).resolve().parent


def sibling(name):
    spec=importlib.util.spec_from_file_location('uc_arm_preflight_'+name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

workspace=sibling('project_workspace')
base=sibling('arm_baseline')


def _binary_kind(path):
    with path.open('rb') as stream:
        first=stream.read(64)
    if first[:2]==b'#!':
        return 'script-needs-external-interpreter'
    if first[:4]==b'\x7fELF':
        return 'elf'
    if first[:4] in (b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',
                     b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xce',
                     b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'):
        return 'mach-o'
    return 'unknown'


def inspect(candidate=None, mke2fs='outputs/toolchain/bin/mke2fs'):
    root=workspace.project_root()
    result={'schema_version':1,'type':'ubuntu-customizer/arm-preflight',
            'host_os':sys.platform,'host_arch':platform.machine(),
            'filesystem_scope':'project-only-local-inputs',
            'local_image_discovery':False,
            'physical_emmc_access':False,'boot_confirmed':False,
            'host_os_sandbox_verified':False,
            'portable_fat32':'available',
            'requirements':{},'blockers':[], 'next_actions':[]}

    def record(key,valid,reason=None,action=None,**extra):
        result['requirements'][key]={'ready':bool(valid),**extra}
        if not valid:
            result['blockers'].append(reason or key)
            if action and action not in result['next_actions']:
                result['next_actions'].append(action)

    report=root/'outputs/baselines'/ (base.BASELINE['id']+'.json')
    valid_source=False
    try:
        meta=workspace.checked_input(report,max_bytes=32768)
        record_data=json.loads(meta.read_text(encoding='utf-8'))
        candidate_archive=workspace.checked_input(record_data.get('file'),max_bytes=base.MAX_BYTES)
        valid_source=(record_data.get('sha256')==base.BASELINE['sha256'] and
                      record_data.get('url')==base.BASELINE['url'] and
                      candidate_archive.name==base.BASELINE['filename'] and
                      base.sha256_file(candidate_archive)==base.BASELINE['sha256'])
    except (ValueError,OSError,TypeError,KeyError,json.JSONDecodeError):
        valid_source=False
    record('official_rootfs',valid_source,'official_arm64_rootfs_not_verified',
           'Approve pinned Ubuntu Base download using arm_baseline.py --approved-download')

    if candidate is None:
        record('board_candidate',False,'board_candidate_unspecified',
               'Stage W152D Kernel/DTB and the actual U-Boot loading assets under outputs')
    else:
        try:
            manifest=workspace.checked_input(candidate,max_bytes=1024*1024)
            document=json.loads(manifest.read_text(encoding='utf-8'))
            parts=document.get('components',{})
            present=[]
            for name in ('kernel','dtb','boot_script'):
                entry=parts.get(name)
                if isinstance(entry,dict):
                    path=workspace.checked_input(entry.get('file'),max_bytes=256*1024*1024)
                    if base.sha256_file(path)==entry.get('sha256') and path.stat().st_size==entry.get('bytes'):
                        present.append(name)
            if document.get('board') and 'kernel' in present and 'dtb' in present:
                record('board_candidate',True,components_verified=present,
                       board=document.get('board'),revision=document.get('revision'))
            else:
                record('board_candidate',False,'board_kernel_dtb_missing_or_changed',
                       'Acquire and stage genuine board Kernel/DTB revision')
        except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):
            record('board_candidate',False,'board_candidate_invalid',
                   'Repair project-local candidate manifest and component integrity')

    try:
        binary=workspace.checked_input(mke2fs,max_bytes=256*1024*1024)
        kind=_binary_kind(binary)
        compatible=(kind=='mach-o' if sys.platform=='darwin' else
                    kind=='elf' if sys.platform.startswith('linux') else False)
        record('ext4_tool',os.access(binary,os.X_OK) and compatible,
               'project_local_ext4_tool_missing_or_incompatible',
               'Provide a verified, compatible project-local mke2fs executable',
               format=kind, sha256=base.sha256_file(binary))
    except (ValueError,OSError,TypeError):
        record('ext4_tool',False,'project_local_mke2fs_missing',
               'Provide a verified project-local ext4 image writer in outputs/toolchain/bin')

    record('host_sandbox',False,'whole_process_host_filesystem_sandbox_unverified',
           'Use an OS-enforced sandbox before executing third-party tools')
    result['ready_for_real_build']=all(result['requirements'][k]['ready']
                                       for k in ('official_rootfs','board_candidate','ext4_tool'))
    result['safe_to_execute_unsandboxed']=False
    result['next_stage']='offline_build' if result['ready_for_real_build'] else 'prepare_missing_inputs'
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',help='Project-local staged board candidate manifest')
    parser.add_argument('--tool-mke2fs',default='outputs/toolchain/bin/mke2fs')
    parser.add_argument('--report',help='New outputs/.../preflight.json')
    args=parser.parse_args(argv)
    try:
        report=inspect(args.candidate,args.tool_mke2fs)
        if args.report:
            file=workspace.checked_output(args.report)
            if file.exists() or file.is_symlink() or not file.parent.is_dir():
                raise ValueError('Preflight report must be a new outputs file')
            with file.open('x',encoding='utf-8') as stream:
                json.dump(report,stream,indent=2,ensure_ascii=False)
                stream.write('\n')
            file.chmod(0o600)
        print(json.dumps(report,indent=2,ensure_ascii=False))
        return 0 if report['ready_for_real_build'] else 2
    except (ValueError,OSError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
