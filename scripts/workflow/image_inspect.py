#!/usr/bin/env python3
"""Read-only introspection of an existing RAW/QCOW2 guest disk image.

Uses qemu-img and optional libguestfs tools without mounting a filesystem on
the host. No image conversion, installation, network access or host disk writes.
The guest image is untrusted; all observations are bounded and evidence tagged.
"""
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

MAX_OUTPUT = 2 * 1024 * 1024
MAX_SIZE = 2 * 1024**4
ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64",
        "arm64": "arm64", "armv7l": "armhf", "armv7": "armhf",
        "i386": "i386", "i686": "i386", "riscv64": "riscv64"}

def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def safe_source(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Source must be a regular, non-symlink file")
    path = path.resolve()
    if path.parts[:2] in (("/", "dev"), ("/", "proc"), ("/", "sys")):
        raise ValueError("Refusing host pseudo-filesystem source")
    if path.stat().st_size == 0:
        raise ValueError("Source image is empty")
    return path

def run_tool(tool, args, timeout=120):
    if not shutil.which(tool):
        return None, "tool_missing"
    try:
        env = {**os.environ, "LIBGUESTFS_BACKEND": "direct",
               "LIBGUESTFS_NETWORK": "0", "LIBGUESTFS_DEBUG": "0"}
        result = subprocess.run([tool, *args], capture_output=True, timeout=timeout,
                                stdin=subprocess.DEVNULL, env=env, check=False)
        if len(result.stdout) > MAX_OUTPUT:
            return None, "output_too_large"
        if result.returncode:
            return None, "inspection_failed"
        return result.stdout.decode("utf-8", "replace"), None
    except (OSError, subprocess.TimeoutExpired):
        return None, "inspection_failed"

def safe_xml(text):
    if len(text) > MAX_OUTPUT or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("Unsafe/large inspection XML")
    return ET.fromstring(text)

def xml_value(node, path):
    value = node.findtext(path)
    return value.strip() if isinstance(value, str) and value.strip() else None

def parse_guest_xml(text):
    root = safe_xml(text)
    guests = root.findall("operatingsystem")
    if root.tag != "operatingsystems" or len(guests) != 1:
        raise ValueError("Exactly one identifiable guest OS is required")
    guest = guests[0]
    raw_arch = xml_value(guest, "arch")
    mountpoints = sorted({(m.text or "").strip()
                         for m in guest.findall("./mountpoints/mountpoint")
                         if (m.text or "").strip()})
    return {
        "architecture": ARCH.get((raw_arch or "").lower()),
        "architecture_raw": raw_arch,
        "os_class": xml_value(guest, "name"),
        "distribution": xml_value(guest, "distro"),
        "product_name": xml_value(guest, "product_name"),
        "major_version": xml_value(guest, "major_version"),
        "minor_version": xml_value(guest, "minor_version"),
        "root": xml_value(guest, "root"),
        "mountpoints": mountpoints,
    }

def parse_drivers_xml(text):
    root = safe_xml(text)
    guests = root.findall("operatingsystem")
    if root.tag != "operatingsystems" or len(guests) != 1:
        raise ValueError("Exactly one guest must be present in driver report")
    # virt-drivers places firmware at /operatingsystems/firmware and Linux
    # kernel entries within /operatingsystem/bootloader/kernel.
    firmware = [x.get("type") for x in root.findall("firmware")
                if x.get("type") in ("uefi", "bios")]
    bootloader = guests[0].find("bootloader")
    boot_type = bootloader.get("type") if bootloader is not None else None
    kernels = []
    if bootloader is not None:
        for node in bootloader.findall("kernel"):
            version = xml_value(node, "version")
            path = xml_value(node, "vmlinuz")
            if version and path:
                kernels.append({"version": version[:160], "path": path[:256],
                                "virtio_blk": node.find("supports_virtio_blk") is not None})
    return {"bootloader": boot_type if boot_type and len(boot_type) <= 120 else None,
            "kernels": kernels[:30],
            "boot_modes": sorted(set(firmware)),
            "boot_mode": firmware[0] if len(set(firmware)) == 1 else None}


def parse_partition_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows) > 512:
        raise ValueError("Missing or excessive partition data")
    columns = [x.strip().lower() for x in rows[0]]
    if "name" not in columns or "type" not in columns:
        raise ValueError("Expected virt-filesystems CSV header")
    out = []
    for row in rows[1:]:
        if len(row) != len(columns):
            raise ValueError("Malformed virt-filesystems CSV row")
        item = dict(zip(columns, row))
        if item["type"].lower() in ("partition", "filesystem", "device", "block device"):
            out.append({key: item.get(key) for key in ("name", "type", "vfs", "label", "size")
                        if key in item})
    return out[:256]

def inspect(path, expected_sha256=None):
    source = safe_source(path)
    if expected_sha256 and (not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256)
                            or digest_file(source) != expected_sha256.lower()):
        raise ValueError("Trusted input SHA-256 mismatch")
    sha = expected_sha256.lower() if expected_sha256 else digest_file(source)
    report = {
        "schema_version": 1, "type": "ubuntu-customizer/source-image-inspection",
        "source": {"path": str(source), "sha256": sha, "bytes": source.stat().st_size},
        "observations": {}, "evidence": {}, "gaps": []
    }
    info, error = run_tool("qemu-img", ["info", "--output=json", str(source)], 90)
    if error:
        report["gaps"].append({"check": "disk_format", "reason": error})
        return report
    try:
        data = json.loads(info)
    except ValueError:
        report["gaps"].append({"check": "disk_format", "reason": "malformed_tool_output"})
        return report
    fmt = data.get("format")
    virtual = data.get("virtual-size")
    if fmt not in ("raw", "qcow2") or type(virtual) is not int or not 0 < virtual <= MAX_SIZE:
        report["gaps"].append({"check": "disk_format", "reason": "unsupported_disk_format_or_size"})
        return report
    if any(x in data for x in ("backing-filename", "full-backing-filename")) or data.get("encrypted") is True:
        report["gaps"].append({"check": "disk_format", "reason": "backing_or_encrypted_image"})
        return report
    report["observations"].update({"format": fmt, "virtual_size": virtual})
    report["evidence"]["format"] = {"tool": "qemu-img", "path": "format"}
    table, table_error = run_tool("guestfish",
        ["--ro", "--format=" + fmt, "-a", str(source),
         "run", ":", "part-get-parttype", "/dev/sda"])
    if table_error:
        report["gaps"].append({"check": "partition_table", "reason": table_error})
    else:
        scheme = table.strip().lower()
        if scheme in ("gpt", "msdos"):
            report["observations"]["partition_table"] = "gpt" if scheme == "gpt" else "mbr"
            report["evidence"]["partition_table"] = {
                "tool": "guestfish", "command": "part-get-parttype", "read_only": True}
        else:
            report["gaps"].append({"check": "partition_table", "reason": "unknown_partition_scheme"})
    for check, tool, args, parser in [
        ("partitions", "virt-filesystems",
         ["--format=" + fmt, "-a", str(source), "--all", "--long", "--csv"],
         parse_partition_csv),
        ("guest_os", "virt-inspector",
         ["--format=" + fmt, "-a", str(source), "--no-applications", "--no-icon"],
         parse_guest_xml),
        ("boot_details", "virt-drivers",
         ["--format=" + fmt, "-a", str(source)],
         parse_drivers_xml),
    ]:
        output, error = run_tool(tool, args)
        if error:
            report["gaps"].append({"check": check, "reason": error})
            continue
        try:
            item = parser(output)
        except (ValueError, ET.ParseError):
            report["gaps"].append({"check": check, "reason": "unrecognized_tool_output"})
            continue
        report["observations"][check] = item
        report["evidence"][check] = {"tool": tool, "image_sha256": sha,
                                     "read_only": True}
    return report

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source")
    p.add_argument("--sha256", help="independently trusted checksum")
    p.add_argument("--output", required=True, help="new JSON report")
    args = p.parse_args(argv)
    try:
        result = inspect(args.source, args.sha256)
        output = workspace.checked_output(args.output)
        if output.exists() or output.is_symlink():
            raise ValueError("Report already exists")
        with output.open("x", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            f.write("\n")
        output.chmod(0o600)
        print(json.dumps({"report": str(output), "gaps": len(result["gaps"]),
                          "observations": list(result["observations"])}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

# The CLI enforces the project's outputs-only policy. Internal library functions
# continue to accept isolated temporary test fixtures without changing their API.
ws_spec = importlib.util.spec_from_file_location(
    "uc_workspace_image_inspect", Path(__file__).with_name("project_workspace.py"))
workspace = importlib.util.module_from_spec(ws_spec)
ws_spec.loader.exec_module(workspace)

if __name__ == "__main__":
    raise SystemExit(main())
