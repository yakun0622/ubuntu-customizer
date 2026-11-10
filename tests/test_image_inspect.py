import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from image_fixtures import inspection

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_image_inspect_test", ROOT / "scripts/workflow/image_inspect.py")
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)

GUEST_XML = """<operatingsystems><operatingsystem>
<root>/dev/sda2</root><name>linux</name><arch>x86_64</arch>
<distro>ubuntu</distro><product_name>Ubuntu 24.04</product_name>
<major_version>24</major_version><minor_version>04</minor_version>
<mountpoints><mountpoint dev="/dev/sda2">/</mountpoint>
<mountpoint dev="/dev/sda1">/boot/efi</mountpoint></mountpoints>
</operatingsystem></operatingsystems>"""
DRIVERS_XML = """<operatingsystems><firmware type="uefi">/dev/sda1</firmware>
<operatingsystem><root>/dev/sda2</root>
<bootloader type="grub2" config="/boot/grub/grub.cfg">
<kernel><version>6.8.0-xx-generic</version>
<vmlinuz>/boot/vmlinuz-6.8.0-xx-generic</vmlinuz>
<supports_virtio_blk/></kernel></bootloader></operatingsystem></operatingsystems>"""
PARTITIONS = "Name,Type,VFS,Label,Size,Parent\n/dev/sda,disk,,,8192,\n/dev/sda1,partition,vfat,EFI,2048,/dev/sda\n/dev/sda2,partition,ext4,root,6144,/dev/sda\n"

class ImageInspectionTests(unittest.TestCase):
    def source(self, root):
        p = root / "guest.img"
        p.write_bytes(b"test-image-payload")
        return p

    def test_guest_os_and_boot_metadata(self):
        guest = inspector.parse_guest_xml(GUEST_XML)
        self.assertEqual(guest["architecture"], "amd64")
        self.assertEqual(guest["distribution"], "ubuntu")
        self.assertIn("/boot/efi", guest["mountpoints"])
        details = inspector.parse_drivers_xml(DRIVERS_XML)
        self.assertEqual(details["boot_mode"], "uefi")
        self.assertEqual(details["bootloader"], "grub2")
        self.assertEqual(details["kernels"][0]["version"], "6.8.0-xx-generic")
        self.assertEqual(inspector.parse_partition_csv(PARTITIONS)[0]["type"], "partition")

    def test_reject_entity_and_multiboot_xml(self):
        with self.assertRaises(ValueError):
            inspector.safe_xml('<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a/>')
        with self.assertRaises(ValueError):
            inspector.parse_guest_xml("<operatingsystems><operatingsystem/>"
                                      "<operatingsystem/></operatingsystems>")

    def test_readonly_inspection_tools_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            source = self.source(Path(d))
            seen = []
            outputs = {
                "qemu-img": json.dumps({"format": "raw", "virtual-size": 8192}),
                "guestfish": "gpt\n",
                "virt-filesystems": PARTITIONS,
                "virt-inspector": GUEST_XML,
                "virt-drivers": DRIVERS_XML,
            }
            def runner(tool, args, timeout=120):
                seen.append((tool, args))
                return outputs[tool], None
            with patch.object(inspector, "run_tool", side_effect=runner):
                result = inspector.inspect(source)
            self.assertEqual(result["gaps"], [])
            self.assertEqual(result["observations"]["partition_table"], "gpt")
            self.assertEqual(result["observations"]["guest_os"]["architecture"], "amd64")
            self.assertEqual(result["evidence"]["boot_details"]["tool"], "virt-drivers")
            self.assertTrue(all("--ro" in args for tool, args in seen if tool == "guestfish"))
            self.assertTrue(all("--format=raw" in args for tool, args in seen
                                if tool in ("guestfish", "virt-inspector", "virt-filesystems", "virt-drivers")))
            self.assertEqual(result["source"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_unknown_tools_are_gaps_not_invented_facts(self):
        with tempfile.TemporaryDirectory() as d:
            source = self.source(Path(d))
            with patch.object(inspector, "run_tool", return_value=(None, "tool_missing")):
                result = inspector.inspect(source)
            self.assertNotIn("guest_os", result["observations"])
            self.assertTrue(any(x["reason"] == "tool_missing" for x in result["gaps"]))

    def test_reject_tampered_and_symlink_source(self):
        with tempfile.TemporaryDirectory() as d:
            source = self.source(Path(d))
            with self.assertRaises(ValueError):
                inspector.inspect(source, "0"*64)
            shortcut = Path(d) / "linked.img"
            shortcut.symlink_to(source)
            with self.assertRaises(ValueError):
                inspector.inspect(shortcut)

    def test_backing_and_encryption_block_deep_inspection(self):
        with tempfile.TemporaryDirectory() as d:
            source = self.source(Path(d))
            with patch.object(inspector, "run_tool",
                              return_value=(json.dumps({"format": "qcow2",
                                                       "virtual-size": 8192,
                                                       "backing-filename": "other.qcow2"}), None)):
                result = inspector.inspect(source)
            self.assertTrue(any(x["reason"] == "backing_or_encrypted_image" for x in result["gaps"]))
            self.assertNotIn("guest_os", result["observations"])

if __name__ == "__main__":
    unittest.main()
