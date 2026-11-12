#!/usr/bin/env python3
"""Create a private NoCloud first-boot seed for a cloud-init-enabled VM.

This is an OFFLINE artifact builder. It does not modify a disk image or run
commands in a guest. The guest must already have cloud-init/NoCloud support.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import importlib.util

_progress_spec = importlib.util.spec_from_file_location("uc_seed_progress", Path(__file__).with_name("progress.py"))
progress = importlib.util.module_from_spec(_progress_spec)
_progress_spec.loader.exec_module(progress)

HOST = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
KEY = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/]+={0,3}(?: [^\r\n]{0,180})?$")
MAX_KEY_BYTES = 4096

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def check_image_plan(plan):
    if (plan.get("type") != "ubuntu-customizer/image-plan" or
            plan.get("schema_version") != 1 or
            plan.get("target") != "virtual-machine" or
            plan.get("build_allowed") is not True or plan.get("blockers")):
        raise ValueError("NoCloud generation requires an unblocked VM image plan")
    if plan.get("backend") != "qemu-img-offline-convert":
        raise ValueError("Unsupported image backend")

def read_key(path):
    p = Path(path).expanduser()
    if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_KEY_BYTES:
        raise ValueError("SSH public key must be a regular file (<= 4 KiB)")
    value = p.read_text(encoding="ascii").strip()
    if "\n" in value or "\r" in value or not KEY.fullmatch(value):
        raise ValueError("Expected one OpenSSH public key, not a private key or multiline content")
    return value

def make_files(plan, hostname, username, key_path, instance_id, output_dir):
    check_image_plan(plan)
    if not HOST.fullmatch(hostname) or not USER.fullmatch(username) or username == "root":
        raise ValueError("Invalid hostname or login name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", instance_id):
        raise ValueError("Invalid instance ID")
    key = read_key(key_path)
    output = Path(output_dir).expanduser()
    if output.exists() or output.is_symlink():
        raise ValueError("Output directory must be new")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Output parent must exist without symlink")
    output.mkdir(mode=0o700)
    # JSON is a YAML 1.2 subset. Cloud-init processes the document following
    # its #cloud-config header as YAML mapping.
    user_data = {
        "preserve_hostname": False,
        "hostname": hostname,
        "ssh_pwauth": False,
        "disable_root": True,
        "users": [{
            "name": username,
            "lock_passwd": True,
            "ssh_authorized_keys": [key]
        }],
        "growpart": {"mode": "auto", "devices": ["/"], "ignore_growroot_disabled": False},
        "resize_rootfs": True
    }
    files = {
        "user-data": "#cloud-config\n" + json.dumps(user_data, indent=2) + "\n",
        "meta-data": json.dumps({"instance-id": instance_id, "local-hostname": hostname}, indent=2) + "\n",
    }
    for name, content in files.items():
        p = output / name
        with p.open("x", encoding="utf-8") as f:
            f.write(content)
        p.chmod(0o600)
    manifest = {
        "schema_version": 1,
        "type": "ubuntu-customizer/nocloud-seed",
        "instance_id": instance_id,
        "hostname": hostname,
        "username": username,
        "files": {name: {"sha256": sha256(output / name), "bytes": (output / name).stat().st_size} for name in files},
        "assumptions": [
            "Base image includes enabled cloud-init with NoCloud datasource",
            "SSH access depends on an existing SSH server and network configuration",
            "Disk has a compatible root filesystem and partition layout for growpart",
            "Source machine-id, SSH host keys and existing cloud-init state are NOT cleaned by this tool",
        ]
    }
    p = output / "manifest.json"
    with p.open("x", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    p.chmod(0o600)
    return output, manifest

def make_iso(directory, output):
    directory = Path(directory)
    output = Path(output).expanduser()
    if output.exists() or output.is_symlink():
        raise ValueError("ISO output already exists")
    if output.suffix.lower() != ".iso" or not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("ISO output needs an existing real parent and .iso extension")
    tool = shutil.which("genisoimage") or shutil.which("mkisofs")
    if not tool:
        raise RuntimeError("genisoimage or mkisofs required to create a NoCloud seed ISO")
    temp = output.parent / ("." + output.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        args = [tool, "-quiet", "-output", str(temp), "-volid", "cidata",
                "-joliet", "-rock", "user-data", "meta-data"]
        proc = subprocess.run(args, cwd=directory, text=True, capture_output=True,
                              timeout=120, check=False)
        if proc.returncode:
            raise RuntimeError("Seed ISO generation failed: " + proc.stderr[:500])
        temp.chmod(0o600)
        # Never silently overwrite an existing output.
        os.link(temp, output)
        output.chmod(0o600)
        return {"path": str(output), "sha256": sha256(output), "bytes": output.stat().st_size}
    finally:
        if temp.exists():
            temp.unlink()

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plan", help="JSON created by image_plan.py")
    p.add_argument("--hostname", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--ssh-public-key", required=True, help="existing .pub file")
    p.add_argument("--instance-id", required=True, help="unique per deployment")
    p.add_argument("--output-dir", required=True, help="new private output directory")
    p.add_argument("--iso", help="optional new NoCloud seed ISO output")
    args = p.parse_args(argv)
    try:
        with workspace.checked_input(args.plan).open(encoding="utf-8") as f:
            plan = json.load(f)
        with progress.tracking(progress.session_from_plan(plan), "first-boot",
                               3 if args.iso else 2) as tracker:
            if (plan.get("target") != "virtual-machine" or
                    plan.get("build_allowed") is not True or plan.get("blockers") or
                    plan.get("backend") != "qemu-img-offline-convert"):
                tracker.blocked()
            folder, manifest = make_files(plan, args.hostname, args.username,
                                          args.ssh_public_key, args.instance_id,
                                          str(workspace.checked_output(args.output_dir)))
            tracker.advance(1)  # NoCloud user-data/meta-data generated
            if args.iso:
                manifest["iso"] = make_iso(folder, args.iso)
                tracker.advance(2)  # Optional cidata ISO created
                path = folder / "manifest.json"
                with path.open("w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)
                    f.write("\n")
                tracker.advance(3)  # Final seed manifest updated
            else:
                tracker.advance(2)  # Seed manifest created by make_files
        print(json.dumps({"output_dir": str(folder), "iso": manifest.get("iso"),
                          "cloud_init_required": True}, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

# The CLI enforces the project's outputs-only policy. Internal library functions
# continue to accept isolated temporary test fixtures without changing their API.
ws_spec = importlib.util.spec_from_file_location(
    "uc_workspace_nocloud", Path(__file__).with_name("project_workspace.py"))
workspace = importlib.util.module_from_spec(ws_spec)
ws_spec.loader.exec_module(workspace)

if __name__ == "__main__":
    raise SystemExit(main())
