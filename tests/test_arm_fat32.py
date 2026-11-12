"""Portable FAT32 writer tests; all fixtures remain inside project outputs."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('fat32_tests',ROOT/'scripts/workflow/arm_fat32.py')
fat32 = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = fat32
SPEC.loader.exec_module(fat32)


class Fat32WriterTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'outputs'
        folder.mkdir(exist_ok=True)
        tmp=tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name)
        self.boot=self.base/'boot'
        self.boot.mkdir()
        self.image=self.base/'fat.img'
        with self.image.open('xb') as output:
            output.truncate(64*1024*1024)

    def test_actual_file_layout_and_long_filenames(self):
        (self.boot/'extlinux').mkdir()
        (self.boot/'extlinux'/'extlinux.conf').write_bytes(b'LINUX /Image\n')
        (self.boot/'Image').write_bytes(b'A'*350000)
        (self.boot/'w152d.dtb').write_bytes(b'DTB')
        (self.boot/'aml_autoscript').write_bytes(b'AML')
        info=fat32.write_fat32(self.boot,self.image)
        self.assertEqual(info['filesystem'],'fat32')
        self.assertEqual(info['files_and_directories'],5)
        with self.image.open('rb') as f:
            boot=f.read(512)
            self.assertEqual(boot[510:512],b'\x55\xaa')
            self.assertEqual(boot[82:90],b'FAT32   ')
            self.assertEqual(boot[71:82],b'UCBOOT     ')
            bps=struct.unpack_from('<H',boot,11)[0]
            spc=boot[13]
            reserved=struct.unpack_from('<H',boot,14)[0]
            fats=boot[16]
            fatsz=struct.unpack_from('<I',boot,36)[0]
            self.assertEqual((bps,reserved,fats),(512,32,2))
            self.assertGreater(info['clusters'],65525)
            # Independent FAT and directory inspection, not writer metadata.
            def chain(start):
                seen=set()
                while start<0x0ffffff8:
                    self.assertNotIn(start,seen)
                    seen.add(start)
                    yield start
                    f.seek(reserved*512+start*4)
                    start=struct.unpack('<I',f.read(4))[0]&0x0fffffff
            data_start=(reserved+fats*fatsz)*512
            def read_chain(start):
                payload=b''
                for cluster in chain(start):
                    f.seek(data_start+(cluster-2)*spc*512)
                    payload+=f.read(spc*512)
                return payload
            root=read_chain(2)
            self.assertIn(b'AML',read_chain(self._cluster_for(root,b'AMLAUT~1')))
            self.assertTrue(read_chain(self._cluster_for(root,b'IMAGE'))[:100].startswith(b'A'*100))
            self.assertEqual(read_chain(self._cluster_for(root,b'W152D'))[:3],b'DTB')
            self.assertIn(bytes([0x0f]),root)
            subdir=self._cluster_for(root,b'EXTLINUX')
            self.assertIn(b'LINUX /Image',read_chain(self._cluster_for(read_chain(subdir),b'EXTLIN~1')))
            f.seek(512)
            fsinfo=f.read(512)
            self.assertEqual(struct.unpack_from('<I',fsinfo,0)[0],0x41615252)
            self.assertEqual(struct.unpack_from('<I',fsinfo,484)[0],0x61417272)

    @staticmethod
    def _cluster_for(directory,name_prefix):
        for i in range(0,len(directory),32):
            entry=directory[i:i+32]
            if entry[0] == 0:break
            if entry[11] == 0x0f:continue
            if entry[:len(name_prefix)] == name_prefix:
                return struct.unpack_from('<H',entry,20)[0]<<16 | struct.unpack_from('<H',entry,26)[0]
        raise AssertionError('FAT directory entry missing: '+str(name_prefix))

    def test_reject_symlinks_and_boundary(self):
        (self.boot/'safe').write_text('ok')
        (self.boot/'unsafe').symlink_to(self.boot/'safe')
        with self.assertRaisesRegex(ValueError,'only regular'):
            fat32.write_fat32(self.boot,self.image)
        (self.boot/'unsafe').unlink()
        with self.assertRaises(ValueError):
            fat32.write_fat32(self.boot,self.image,volume_label='../OUT')
        with self.assertRaises(ValueError):
            fat32.write_fat32(self.boot,self.boot/'safe')
        with self.assertRaises(ValueError):
            fat32.write_fat32(self.boot,ROOT/'SKILL.md')

    def test_64_and_128_mib_layout_converges(self):
        for mib in (64,128):
            with self.subTest(mib=mib):
                self.assertGreaterEqual(fat32._layout(mib*2048)[2],65525)

    def test_names_unique_and_length_limited(self):
        used=set()
        first,_=fat32._short('extlinux.conf',used)
        second,_=fat32._short('extlinux.confs',used)
        self.assertNotEqual(first,second)
        with self.assertRaises(ValueError):
            fat32._lfn_entries('a'*257,b'FILE    TXT')

if __name__=='__main__':
    unittest.main()
