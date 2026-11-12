"""Project-confined ARM preflight, no host PATH discovery or tool execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('uc_arm_preflight_test',ROOT/'scripts/workflow/arm_preflight.py')
preflight=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class ArmPreflightTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'outputs').mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=ROOT/'outputs')
        self.addCleanup(temp.cleanup)
        self.project=Path(temp.name)/'project'
        (self.project/'scripts/workflow').mkdir(parents=True)
        (self.project/'SKILL.md').write_text('test')
        # All helpers and fixture files stay underneath the checked-out repo.
        patch=mock.patch.object(preflight.workspace,'project_root',return_value=self.project)
        patch.start(); self.addCleanup(patch.stop)

    def test_missing_inputs_give_actions_without_host_scanning(self):
        report=preflight.inspect()
        self.assertIn('official_arm64_rootfs_not_verified',report['blockers'])
        self.assertIn('project_local_mke2fs_missing',report['blockers'])
        self.assertFalse(report['ready_for_real_build'])
        self.assertFalse(report['safe_to_execute_unsandboxed'])
        self.assertFalse(report['local_image_discovery'])
        self.assertFalse(report['physical_emmc_access'])

    def setup_fixture(self):
        root=self.project
        archive_dir=root/'outputs/baselines'
        archive_dir.mkdir(parents=True)
        archive=archive_dir/preflight.base.BASELINE['filename']
        archive.write_bytes(b'synthetic ubuntu base')
        original=dict(preflight.base.BASELINE)
        preflight.base.BASELINE['sha256']=preflight.base.sha256_file(archive)
        self.addCleanup(lambda:preflight.base.BASELINE.update(original))
        meta={**preflight.base.BASELINE,'file':str(archive)}
        (archive_dir/(preflight.base.BASELINE['id']+'.json')).write_text(json.dumps(meta))
        src=root/'outputs/src';src.mkdir()
        parts={}
        for name in ('kernel','dtb'):
            path=src/(name+'.bin');path.write_bytes(name.encode())
            parts[name]={'file':str(path),'sha256':preflight.base.sha256_file(path),'bytes':path.stat().st_size}
        candidate=root/'outputs/candidate.json'
        candidate.write_text(json.dumps({'board':'w152d','revision':1,'components':parts}))
        tool=root/'outputs/toolchain/bin/mke2fs'
        tool.parent.mkdir(parents=True)
        tool.write_bytes(b'\x7fELF' + bytes(60))
        tool.chmod(0o700)
        return archive, candidate, tool

    def test_candidate_ready_does_not_claim_process_sandbox(self):
        _, candidate, tool=self.setup_fixture()
        with mock.patch.object(preflight.sys,'platform','linux'):
            report=preflight.inspect(candidate,tool)
        self.assertTrue(report['ready_for_real_build'])
        self.assertEqual(report['requirements']['ext4_tool']['format'],'elf')
        self.assertFalse(report['safe_to_execute_unsandboxed'])
        self.assertFalse(report['host_os_sandbox_verified'])
        self.assertFalse(report['boot_confirmed'])

    def test_corrupt_baseline_and_external_tool_fail_closed(self):
        archive,candidate,tool=self.setup_fixture()
        archive.write_bytes(b'changed!')
        result=preflight.inspect(candidate,tool)
        self.assertIn('official_arm64_rootfs_not_verified',result['blockers'])
        result=preflight.inspect(candidate,'/usr/sbin/mke2fs')
        self.assertIn('project_local_mke2fs_missing',result['blockers'])
        external=self.project/'outputs/external'
        external.symlink_to('/usr/sbin/mke2fs')
        report=preflight.inspect(candidate,external)
        self.assertFalse(report['requirements']['ext4_tool']['ready'])

if __name__=='__main__':
    unittest.main()
