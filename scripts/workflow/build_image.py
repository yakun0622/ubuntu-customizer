#!/usr/bin/env python3
"""Offline VM disk-image conversion from an approved, integrity-checked plan.

Uses qemu-img to convert *local regular image files* only. Never targets
/dev block devices or modifies the remote device. This is NOT an ISO installer
or physical-board IMG builder and does not prove the output will boot.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid

MAX_VIRTUAL_SIZE = 2 * 1024**4
ACCEPTED_INPUT_FORMATS = {"qcow2", "raw"}

def hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def safe_regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Refusing non-regular or symbolic-link image")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("Refusing non-regular input")
    return path.resolve()

def validate(plan):
    if plan.get("type") != "ubuntu-customizer/image-plan" or plan.get("schema_version") != 1:
        raise ValueError("Invalid image-plan schema")
    if plan.get("target") != "virtual-machine" or plan.get("build_allowed") is not True or plan.get("blockers"):
        raise ValueError("Only an unblocked virtual-machine conversion plan may be executed")
    if plan.get("backend") != "qemu-img-offline-convert" or plan.get("format") not in ("qcow2", "raw"):
        raise ValueError("Unsupported backend/output format")
    source_info = plan.get("source", {})
    source_name = source_info.get("path")
    if not isinstance(source_name, str) or not source_name.startswith("/"):
        raise ValueError("Source path must be an absolute path")
    path = safe_regular(source_name)
    if path.parts[:2] in (("/", "dev"), ("/", "proc"), ("/", "sys")):
        raise ValueError("Refusing source under /dev, /proc or /sys")
    if not re.fullmatch(r"[a-f0-9]{64}", source_info.get("sha256", "")):
        raise ValueError("Missing SHA256")
    if hash_file(path) != source_info["sha256"] or path.stat().st_size != source_info.get("bytes"):
        raise ValueError("Source image has changed since planning")
    return path

def inspect_image(path):
    if not shutil.which("qemu-img"):
        raise RuntimeError("qemu-img not installed")
    proc = subprocess.run(["qemu-img", "info", "--output=json", str(path)],
                          capture_output=True, text=True, timeout=90, check=False)
    if proc.returncode != 0:
        raise RuntimeError("qemu-img info failed: " + proc.stderr[:500])
    info = json.loads(proc.stdout)
    fmt = info.get("format")
    if fmt not in ACCEPTED_INPUT_FORMATS:
        raise ValueError("Unsupported source image format")
    # A backing chain may depend on external images or unsafe paths.
    if any(k in info for k in ("backing-filename", "full-backing-filename")):
        raise ValueError("Backing file chain is not supported")
    virtual = info.get("virtual-size")
    if not isinstance(virtual, int) or not 0 < virtual <= MAX_VIRTUAL_SIZE:
        raise ValueError("Invalid or excessive virtual disk size")
    return info

def build(plan, output):
    source = validate(plan)
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists")
    if output.parts[:2] in (("/", "dev"), ("/", "proc"), ("/", "sys")):
        raise ValueError("Refusing output under /dev, /proc or /sys")
    if output.suffix.lower() != (".qcow2" if plan["format"] == "qcow2" else ".img"):
        raise ValueError("Use .qcow2 for QCOW2 or .img for raw outputs")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Output parent must already exist and must not be a symlink")
    if source == output:
        raise ValueError("Refusing in-place conversion")
    info = inspect_image(source)
    tmp = output.parent / ("." + output.name + "." + uuid.uuid4().hex + ".tmp")
    manifest_path = output.with_name(output.name + ".manifest.json")
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("Manifest already exists")
    fmt = plan["format"]
    try:
        # qemu-img is invoked with an argv array, never through a shell.
        # Conversion requires only an offline image source; it does not write to disks.
        with tmp.open("xb"):
            pass
        tmp.chmod(0o600)
        proc = subprocess.run(["qemu-img", "convert", "-f", info["format"], "-O", fmt,
                               str(source), str(tmp)],
                              capture_output=True, text=True, timeout=3600, check=False)
        if proc.returncode:
            raise RuntimeError("qemu-img conversion failed: " + proc.stderr[:500])
        converted = inspect_image(tmp)
        if converted.get("format") != fmt or converted.get("virtual-size") != info["virtual-size"]:
            raise RuntimeError("Output image metadata mismatch")
        digest = hash_file(tmp)
        # Hard-link creation fails instead of overwriting an output created
        # concurrently; the output is a newly written regular file.
        os.link(tmp, output)
        output.chmod(0o600)
        report = {
            "schema_version": 1,
            "type": "ubuntu-customizer/image-build-result",
            "backend": "qemu-img-offline-convert", "boot_tested": False,
            "source_sha256": plan["source"]["sha256"],
            "output_path": str(output), "output_sha256": digest,
            "output_bytes": output.stat().st_size,
            "format": fmt, "virtual_size": info["virtual-size"],
            "warning": "Disk conversion only. Bootability, portability and machine identity reset remain unverified."
        }
        with manifest_path.open("x", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
        manifest_path.chmod(0o600)
        return report
    finally:
        if tmp.exists():
            tmp.unlink()

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plan", help="JSON created by image_plan.py")
    p.add_argument("--output", required=True, help="new image filename")
    args = p.parse_args(argv)
    try:
        plan_path = safe_regular(args.plan)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        result = build(plan, args.output)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
