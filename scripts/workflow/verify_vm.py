#!/usr/bin/env python3
"""Verify a converted VM image with static checks and optional isolated boot smoke.

By default no guest execution. Optional --boot runs QEMU with TCG, no network,
and a snapshot overlay. Exit codes/serial data cannot alone confirm boot success.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

def checksum(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def validate_result(result):
    if result.get("type") != "ubuntu-customizer/image-build-result" or result.get("schema_version") != 1:
        raise ValueError("Unexpected image result schema")
    p = Path(result.get("output_path", ""))
    if not p.is_absolute() or p.is_symlink() or not p.is_file():
        raise ValueError("Missing or unsafe output disk image")
    if p.parts[:2] in (("/", "dev"), ("/", "sys"), ("/", "proc")):
        raise ValueError("Pseudo-filesystem source is forbidden")
    if checksum(p) != result.get("output_sha256") or p.stat().st_size != result.get("output_bytes"):
        raise ValueError("Output image hash/length mismatch")
    if result.get("format") not in ("raw", "qcow2"):
        raise ValueError("Unsupported output image format")
    return p

def qemu_info(image):
    if not shutil.which("qemu-img"):
        raise RuntimeError("qemu-img not installed")
    p = subprocess.run(["qemu-img", "info", "--output=json", str(image)],
                       capture_output=True, text=True, timeout=90, check=False)
    if p.returncode:
        raise RuntimeError("qemu-img info failed: " + p.stderr[:500])
    info = json.loads(p.stdout)
    if any(k in info for k in ("backing-filename", "full-backing-filename")):
        raise ValueError("Backing chain is unsupported")
    return info

def verify(result, boot=False, timeout=45, serial_log=None, seed_iso=None):
    image = validate_result(result)
    info = qemu_info(image)
    if info.get("format") != result["format"] or info.get("virtual-size") != result.get("virtual_size"):
        raise ValueError("qemu-img metadata differs from build result")
    report = {
        "schema_version": 1, "type": "ubuntu-customizer/vm-verification",
        "image_path": str(image), "image_sha256": result["output_sha256"],
        "format": result["format"], "static_image_check": "passed",
        "boot_attempted": False, "boot_confirmed": False,
        "boot_state": "not_tested",
        "warnings": ["Static disk checks do not prove guest OS bootability.",
                     "Guest architecture and firmware have not been established by disk conversion."]
    }
    if not boot:
        return report
    if result.get("architecture") != "amd64":
        raise ValueError("Automatic x86_64 QEMU smoke test requires an amd64 image report")
    if not 5 <= timeout <= 300:
        raise ValueError("Boot timeout must be between 5 and 300 seconds")
    if not shutil.which("qemu-system-x86_64"):
        raise RuntimeError("qemu-system-x86_64 is not installed")
    if serial_log is None:
        raise ValueError("Explicit serial log path required for boot smoke test")
    if "," in str(image) or "\\n" in str(image):
        raise ValueError("Image path contains unsupported QEMU drive syntax")
    serial = Path(serial_log).expanduser()
    if serial.exists() or serial.is_symlink() or not serial.parent.is_dir() or serial.parent.is_symlink():
        raise ValueError("Serial output must be a new file in an existing real directory")
    cmd = ["qemu-system-x86_64", "-machine", "q35", "-accel", "tcg",
           "-m", "1024", "-smp", "2", "-nic", "none", "-display", "none",
           "-monitor", "none", "-no-reboot",
           "-drive", "file=" + str(image) + ",format=" + result["format"] + ",if=virtio,snapshot=on",
           "-serial", "file:" + str(serial)]
    if seed_iso is not None:
        seed = Path(seed_iso).expanduser()
        if seed.is_symlink() or not seed.is_file() or seed.suffix.lower() != ".iso" or "," in str(seed):
            raise ValueError("Invalid seed ISO")
        cmd += ["-drive", "file=" + str(seed.resolve()) + ",media=cdrom,readonly=on"]
    report["boot_attempted"] = True
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        report["boot_state"] = "qemu_exited"
        report["qemu_exit_code"] = run.returncode
        report["qemu_stderr_excerpt"] = run.stderr[-1000:]
    except subprocess.TimeoutExpired:
        report["boot_state"] = "timeout_inconclusive"
    report["serial_log"] = str(serial)
    report["warnings"].append("Review serial output manually; QEMU exit/timeout is not a verified boot success signal.")
    return report

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("build_manifest", help="output.qcow2.manifest.json")
    p.add_argument("--boot", action="store_true", help="explicitly allow isolated x86_64 QEMU execution")
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--serial-log", help="new local log path for optional QEMU boot")
    p.add_argument("--seed-iso", help="optional NoCloud seed ISO")
    p.add_argument("--report", required=True, help="new verification JSON file")
    args = p.parse_args(argv)
    try:
        path = Path(args.report)
        if path.exists() or path.is_symlink():
            raise ValueError("Report already exists")
        result = json.loads(Path(args.build_manifest).read_text(encoding="utf-8"))
        report = verify(result, args.boot, args.timeout, args.serial_log, args.seed_iso)
        with path.open("x", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        path.chmod(0o600)
        print(json.dumps({"report": str(path), "static_image_check": "passed",
                          "boot_state": report["boot_state"], "boot_confirmed": False}))
        return 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
