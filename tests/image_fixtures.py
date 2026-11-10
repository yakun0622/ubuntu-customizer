"""Synthetic, explicitly verified-looking evidence for unit tests only.

Never use these fixtures to authorize a real image build.
"""
import hashlib
from pathlib import Path

def inspection(source, architecture="amd64", boot_mode="uefi"):
    source = Path(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "type": "ubuntu-customizer/source-image-inspection",
        "source": {"path": str(source), "sha256": digest,
                   "bytes": source.stat().st_size},
        "observations": {
            "format": "raw", "virtual_size": 8192,
            "partition_table": "gpt",
            "partitions": [{"name": "/dev/sda1", "type": "partition", "vfs": "ext4"}],
            "guest_os": {"os_class": "linux", "architecture": architecture,
                         "distribution": "ubuntu", "product_name": "Ubuntu"},
            "boot_details": {"boot_mode": boot_mode, "boot_modes": [boot_mode],
                             "bootloader": "grub2",
                             "kernels": [{"version": "6.8.0-test", "path": "/boot/vmlinuz-test"}]}
        },
        "evidence": {
            "format": {"tool": "qemu-img"},
            "partition_table": {"tool": "guestfish"},
            "partitions": {"tool": "virt-filesystems"},
            "guest_os": {"tool": "virt-inspector"},
            "boot_details": {"tool": "virt-drivers"}
        },
        "gaps": []
    }

def plan(source, session=None):
    source = Path(source)
    observed = inspection(source)
    digest = observed["source"]["sha256"]
    return {
        "schema_version": 1, "type": "ubuntu-customizer/image-plan",
        "target": "virtual-machine", "format": "qcow2",
        "backend": "qemu-img-offline-convert", "build_allowed": True,
        "architecture": "amd64", "blockers": [],
        "compatibility": {"status": "candidate",
                          "checks": [{"name": name, "status": "passed"} for name in (
                              "disk_format", "partition_table", "partitions",
                              "guest_architecture", "guest_os", "kernel",
                              "boot_firmware", "bootloader")]},
        "discovery": {"session": str(session)} if session is not None else {},
        "source": {"path": str(source), "sha256": digest,
                   "bytes": source.stat().st_size,
                   "claimed_architecture": "amd64", "architecture_verified": True,
                   "inspection": observed}
    }
