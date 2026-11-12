"""Opt-in actual e2fsprogs + portable FAT32 integration (not a board-boot test).

CI must stage two trusted test executables under outputs/toolchain/bin before
setting UC_REAL_ARM_SMOKE=1. This is not run by default on user machines.
"""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('uc_arm_real_smoke', ROOT/'scripts/workflow/arm_image_builder.py')
builder=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@unittest.skipUnless(os.environ.get('UC_REAL_ARM_SMOKE')=='1',
                     'Real ext4 smoke requires explicitly staged test tools')
class ArmRealSmokeTests(unittest.TestCase):
    def test_real_ext4_and_python_fat32_image(self):
        for tool in ('mke2fs','debugfs','fsck.fat','mdir'):
            path=ROOT/'outputs/toolchain/bin'/tool
            self.assertTrue(path.is_file() and os.access(path,os.X_OK),
                            'CI must stage project-local '+tool)
        output=ROOT/'outputs'
        output.mkdir(exist_ok=True)
        tmp=tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(tmp.cleanup)
        folder=Path(tmp.name)
        board='arm-real-smoke-'+folder.name.lower().replace('_','')[-8:]
        self.addCleanup(lambda:shutil.rmtree(output/'arm-images'/board,ignore_errors=True))
        archive=folder/'ubuntu-base-24.04.5-base-arm64.tar.gz'
        payload=b'#!/bin/sh\nexec /bin/sh\n'
        with tarfile.open(archive,'w:gz') as tar:
            entry=tarfile.TarInfo('sbin/init')
            entry.mode=0o755
            entry.size=len(payload)
            tar.addfile(entry,io.BytesIO(payload))
        official=dict(builder.baseline.BASELINE)
        builder.baseline.BASELINE['sha256']=builder.sha256(archive)
        self.addCleanup(lambda:builder.baseline.BASELINE.update(official))
        assets={}
        for part,filename in (('kernel','Image'),('dtb','w152d.dtb')):
            path=folder/filename
            path.write_bytes((part+' CI-only placeholder').encode())
            assets[part]={'file':str(path),'sha256':builder.sha256(path),'bytes':path.stat().st_size}
        candidate=folder/'candidate.json'
        import json
        candidate.write_text(json.dumps({
            'schema_version':1,'type':'ubuntu-customizer/arm-candidate-stage',
            'board':board,'revision':1,'components':assets,
            'base_archive':str(archive),'base_sha256':builder.sha256(archive)}))
        result=builder.build(candidate,boot_mib=64,root_mib=256,
                             tools={'mke2fs':str(output/'toolchain/bin/mke2fs')},
                             approved=True)
        self.assertEqual(result['boot_filesystem_backend'],'python-fat32')
        self.assertEqual(result['root_partition']['filesystem'],'ext4')
        self.assertFalse(result['usb_boot_confirmed'])
        self.assertFalse(result['deployment_allowed'])
        disk=ROOT/result['image']
        self.assertEqual(result['sha256'],builder.sha256(disk))
        with disk.open('rb') as stream:
            stream.seek(result['boot_partition']['offset']+82)
            self.assertEqual(stream.read(8),b'FAT32   ')
            stream.seek(result['root_partition']['offset']+1080)
            self.assertEqual(stream.read(2),b'\x53\xef')
        extracted_boot=folder/'boot-extracted.fat'
        with disk.open('rb') as source, extracted_boot.open('xb') as dest:
            source.seek(result['boot_partition']['offset'])
            remain=64*1024*1024
            while remain:
                data=source.read(min(1024*1024,remain))
                self.assertTrue(data)
                dest.write(data)
                remain-=len(data)
        fat_tool=output/'toolchain/bin/fsck.fat'
        check=subprocess.run([str(fat_tool),'-n',str(extracted_boot)],
                             cwd=folder,env={'HOME':str(folder),'TMPDIR':str(folder),'PATH':''},
                             capture_output=True,timeout=30,check=False)
        self.assertEqual(check.returncode,0,check.stderr[-400:]+check.stdout[-400:])
        check=subprocess.run([str(output/'toolchain/bin/mdir'),'-i',str(extracted_boot),'::/'],
                             cwd=folder,env={'HOME':str(folder),'TMPDIR':str(folder),'PATH':''},
                             capture_output=True,timeout=30,check=False)
        self.assertEqual(check.returncode,0,check.stderr[-400:])
        self.assertIn(b'IMAGE',check.stdout.upper())
        extracted=folder/'root-extracted.ext4'
        length=256*1024*1024
        with disk.open('rb') as source,extracted.open('xb') as dest:
            source.seek(result['root_partition']['offset'])
            remaining=length
            while remaining:
                block=source.read(min(1024*1024,remaining))
                self.assertTrue(block)
                dest.write(block)
                remaining-=len(block)
        process=subprocess.run([str(output/'toolchain/bin/debugfs'),
                                '-R','cat /sbin/init',str(extracted)],
                               cwd=folder,env={'HOME':str(folder),'TMPDIR':str(folder),'PATH':''},
                               capture_output=True,timeout=20,check=False)
        self.assertEqual(process.returncode,0,process.stderr[-400:])
        self.assertIn(payload,process.stdout)


if __name__=='__main__':
    unittest.main()
