#!/usr/bin/env python3
"""Reproducible, explicitly approved Ubuntu Cloud Image end-to-end VM check.

This is an optional helper of the AI Agent Skill, not an unattended CI or a
physical device image builder. No packages are installed, no host block devices
are touched, and the original source remains read-only. The official pinned
image requires a separate qemu-guest-agent provisioning step if it lacks QGA.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import urllib.request
from urllib.parse import urlparse
import uuid

HERE = Path(__file__).resolve().parent
IMAGE_NAME = "noble-server-cloudimg-amd64.img"
RELEASE = "20261017"
BASE = "https://cloud-images.ubuntu.com/noble/" + RELEASE + "/"
PINNED_SHA256 = "04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94"
MAX_DOWNLOAD = 1536 * 1024**2
MIN_AVAILABLE_GIB = 12
PACKAGES = ("python3", "cloud-init", "openssh-server", "qemu-guest-agent")
REQUIRED_TOOLS = ("qemu-img", "guestfish", "virt-filesystems", "virt-inspector",
                  "virt-drivers", "virt-customize", "virt-sysprep", "virt-cat",
                  "qemu-system-x86_64")

def sibling(name):
    spec = importlib.util.spec_from_file_location("uc_e2e_" + name, HERE / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def _load_safe_output():
    spec = importlib.util.spec_from_file_location("uc_e2e_safe_output", HERE / "safe_output.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()

def expected_hash(sums, filename=IMAGE_NAME):
    found = []
    for line in sums.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *]([A-Za-z0-9_.-]+)", line.strip())
        if match and match.group(2) == filename:
            found.append(match.group(1).lower())
    if len(found) != 1:
        raise ValueError("Official checksum index must identify the image exactly once")
    return found[0]

def pinned_source(filename=IMAGE_NAME):
    if filename != IMAGE_NAME:
        raise ValueError("Unapproved official image filename")
    return {"release": RELEASE, "url": BASE + filename, "sha256": PINNED_SHA256,
            "checksum_index": BASE + "SHA256SUMS"}

def download_official(output):
    """Network operation ONLY on explicit --download; TLS and pinned hash."""
    target = Path(output)
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        raise ValueError("Download destination must be a new file under an existing directory")
    entry = pinned_source()
    def fetch(url, limit):
        with urllib.request.urlopen(url, timeout=40) as response:
            if urlparse(response.geturl()).scheme != "https" or urlparse(response.geturl()).hostname != "cloud-images.ubuntu.com":
                raise ValueError("Unexpected checksum/image redirect")
            chunks = []
            read = 0
            while True:
                part = response.read(min(1024 * 1024, limit + 1 - read))
                if not part:
                    break
                read += len(part)
                if read > limit:
                    raise ValueError("Official download exceeded the safety size limit")
                chunks.append(part)
            return b"".join(chunks)
    sums = fetch(entry["checksum_index"], 128 * 1024).decode("ascii")
    if expected_hash(sums) != PINNED_SHA256:
        raise ValueError("Official checksum index does not match pinned release hash")
    # Exclusive creation. On checksum error remove only our own partial.
    part_path = target.with_name("." + target.name + "." + uuid.uuid4().hex + ".part")
    h = hashlib.sha256()
    written = 0
    try:
        with urllib.request.urlopen(entry["url"], timeout=60) as response:
            if urlparse(response.geturl()).scheme != "https" or urlparse(response.geturl()).hostname != "cloud-images.ubuntu.com":
                raise ValueError("Unexpected official image redirect")
            with part_path.open("xb") as output_file:
                part_path.chmod(0o600)
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > MAX_DOWNLOAD:
                        raise ValueError("Image exceeds maximum allowed transfer")
                    h.update(block)
                    output_file.write(block)
        if written < 1024 * 1024 or h.hexdigest() != PINNED_SHA256:
            raise ValueError("Downloaded image SHA-256/size does not match pinned official release")
        os.link(part_path, target)  # Never overwrite a concurrently created file.
        target.chmod(0o600)
    finally:
        part_path.unlink(missing_ok=True)
    return entry

def host_preflight(workspace, firmware_mode=None, ovmf_code=None, ovmf_vars=None, minimum_gib=MIN_AVAILABLE_GIB):
    """Return structured blockers without installing or changing anything."""
    missing = [tool for tool in REQUIRED_TOOLS if not shutil.which(tool)]
    iso = shutil.which("genisoimage") or shutil.which("mkisofs")
    if not iso:
        missing.append("genisoimage|mkisofs")
    space = shutil.disk_usage(workspace).free if Path(workspace).is_dir() else 0
    blockers = []
    if sys.platform != "linux":
        blockers.append("Real libguestfs/QEMU integration is supported on Linux build hosts only")
    if missing:
        blockers.append("Build host tools are missing: " + ", ".join(missing))
    if space < minimum_gib * 1024**3:
        blockers.append("Insufficient free workspace disk (need at least " + str(minimum_gib) + " GiB)")
    if firmware_mode == "uefi":
        if not ovmf_code or not ovmf_vars:
            blockers.append("Inspected UEFI guest requires both trusted OVMF code and vars")
        else:
            for file in (ovmf_code, ovmf_vars):
                p = Path(file)
                if p.is_symlink() or not p.is_file():
                    blockers.append("Trusted UEFI firmware input missing/unsafe")
    return {"platform": sys.platform, "host_arch": platform.machine(),
            "tools_available": {tool: bool(shutil.which(tool)) for tool in REQUIRED_TOOLS},
            "iso_tool_available": bool(iso), "free_gib": round(space / 1024**3, 2),
            "missing_tools": missing, "blockers": blockers,
            "no_auto_install": True}

def parse_dpkg_status(raw):
    """Read-only Ubuntu guest package inventory. No guest executable runs."""
    if not isinstance(raw, str) or len(raw) > 4 * 1024 * 1024:
        raise ValueError("Invalid guest package inventory")
    installed = set()
    for para in raw.split("\n\n"):
        name = None
        state = None
        for line in para.splitlines():
            if line.startswith("Package: "):
                name = line[9:].strip()
            elif line.startswith("Status: "):
                state = line[8:].strip()
        if name and state == "install ok installed":
            installed.add(name)
    return {pkg: pkg in installed for pkg in PACKAGES}

def guest_preflight(image, image_format, inspector=None):
    if image_format not in ("qcow2", "raw"):
        raise ValueError("Cannot inspect unknown guest image format")
    inspector = inspector or sibling("image_inspect")
    data, error = inspector.run_tool("virt-cat",
        ["--format=" + image_format, "-a", str(image), "/var/lib/dpkg/status"], 120)
    if error or not data:
        return {"packages": {k: None for k in PACKAGES},
                "blockers": ["Guest dpkg inventory is unavailable: " + str(error or "empty")]}
    installed = parse_dpkg_status(data)
    missing = [name for name, present in installed.items() if not present]
    return {"packages": installed,
            "blockers": ["Guest package missing: " + name for name in missing],
            "qga_readiness": "package_present_not_service_verified" if installed["qemu-guest-agent"] else "missing"}

def write_report(folder, data):
    folder = Path(folder)
    target = folder / "e2e-report.json"
    temp = folder / ("." + uuid.uuid4().hex + ".json")
    try:
        with temp.open("x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        temp.chmod(0o600)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)

def require_new_workdir(path):
    dest = _load_safe_output().canonical_new_directory(path)
    dest.mkdir(mode=0o700)
    return dest


def run(args):
    """Execute only after separately approved offline build and QEMU boot."""
    if not args.approve_build or not args.approve_boot:
        raise ValueError("Explicit --approve-build and --approve-boot are both required")
    if bool(args.image) == bool(args.download):
        raise ValueError("Specify exactly one existing --image or --download")
    if args.image and not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256 or ""):
        raise ValueError("Local source requires an independently trusted --sha256")
    if not Path(args.session).is_dir():
        raise ValueError("Verified session directory required")
    if not Path(args.public_key).is_file() or Path(args.public_key).is_symlink():
        raise ValueError("Existing public SSH key required")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", args.hostname):
        raise ValueError("Invalid hostname")
    if not 30 <= args.boot_timeout <= 900:
        raise ValueError("Boot timeout must be 30–900 seconds")
    if not 1 <= args.minimum_gib <= 128:
        raise ValueError("Minimum free workspace GiB must be between 1 and 128")
    work = require_new_workdir(args.workdir)
    result = {"schema_version": 1, "type": "ubuntu-customizer/ubuntu-cloud-e2e",
              "status": "blocked", "boot_confirmed": False,
              "release": RELEASE if args.download else "provided-by-user",
              "source": None, "steps": [], "blockers": [],
              "artifact_integrity_verified": False, "actual_vm_run": False}
    def step(name, status, **fields):
        item = {"name": name, "status": status, **fields}
        result["steps"].append(item)
        write_report(work, result)
    try:
        base = work / "source.img" if args.download else Path(args.image).expanduser()
        if args.download:
            entry = download_official(base)
            trusted = entry["sha256"]
            step("official_download", "passed", release=RELEASE, source_url=entry["url"],
                 source_sha256=trusted)
        else:
            trusted = args.sha256.lower()
        if base.is_symlink() or not base.is_file():
            raise ValueError("Source disk must be an existing regular file")
        if sha256(base) != trusted:
            raise ValueError("Source image SHA-256 did not match trusted checksum")
        result["source"] = {"sha256": trusted, "source_type": "official-pinned" if args.download else "local-verified"}
        step("source_hash", "passed", sha256=trusted)
        inspection = sibling("image_inspect").inspect(base, trusted)
        observations = inspection["observations"]
        fmt = observations.get("format")
        if inspection.get("gaps") or fmt not in ("raw", "qcow2"):
            result["blockers"].append("Source guest image inspection has missing evidence")
            step("source_inspection", "blocked", missing=[x.get("check") for x in inspection.get("gaps", [])])
            return result
        supported_modes = observations.get("boot_details", {}).get("boot_modes") or [
            observations.get("boot_details", {}).get("boot_mode")]
        chosen_mode = args.boot_mode or observations.get("boot_details", {}).get("boot_mode")
        if chosen_mode not in ("bios", "uefi") or chosen_mode not in supported_modes:
            result["blockers"].append("Choose an observed BIOS/UEFI mode explicitly when image supports multiple modes")
            step("firmware_selection", "blocked", supported_modes=supported_modes)
            return result
        step("source_inspection", "passed", format=fmt,
             guest_architecture=observations.get("guest_os", {}).get("architecture"),
             supported_boot_modes=supported_modes, selected_boot_mode=chosen_mode)
        host = host_preflight(work, chosen_mode,
                              args.ovmf_code, args.ovmf_vars, args.minimum_gib)
        if host["blockers"]:
            result["blockers"].extend(host["blockers"])
            step("host_dependencies", "blocked", missing_tools=host["missing_tools"],
                 problems=host["blockers"])
            return result
        step("host_dependencies", "passed", tools=list(host["tools_available"]))
        guest = guest_preflight(base, fmt)
        if guest["blockers"]:
            result["blockers"].extend(guest["blockers"])
            step("guest_dependencies", "blocked", packages=guest["packages"])
            return result
        step("guest_dependencies", "passed", packages=guest["packages"])
        planner = sibling("image_plan")
        plan = planner.plan(args.session, "virtual-machine", "qcow2", base, trusted,
                            "amd64", selected_firmware=chosen_mode)
        if not plan["build_allowed"]:
            result["blockers"].extend(plan["blockers"])
            step("image_plan", "blocked", check_results=plan.get("compatibility", {}).get("checks", []))
            return result
        plan_file = work / "image-plan.json"
        with plan_file.open("x", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
        plan_file.chmod(0o600)
        step("image_plan", "passed", source_sha256=trusted)
        recipe = {
            "schema_version": 1, "hostname": args.hostname,
            "motd": "Ubuntu Customizer reproducible isolated boot test\n",
            "first_boot": {"mode": "nocloud", "username": "ubuntu",
                           "instance_id": "uc-e2e-" + uuid.uuid4().hex,
                           "ssh_public_key": str(Path(args.public_key).resolve()),
                           "seed_iso": True}
        }
        recipe_file = work / "rootfs-config.json"
        with recipe_file.open("x", encoding="utf-8") as f:
            json.dump(recipe, f, indent=2)
        recipe_file.chmod(0o600)
        builder = sibling("rootfs_builder")
        preview = builder.dry_run(plan, recipe)
        if preview["missing_tools"]:
            result["blockers"].append("RootFS build dependencies are missing")
            step("rootfs_preflight", "blocked", missing_tools=preview["missing_tools"])
            return result
        step("rootfs_preflight", "passed", operations=preview["operations"])
        bundle, _ = builder.assemble(plan, recipe, work / "rootfs-bundle", approved=True)
        integrity = builder.verify_bundle(bundle)
        result["artifact_integrity_verified"] = bool(integrity["hash_verified"])
        step("rootfs_build", "passed", output_sha256=integrity["image_sha256"])
        verifier = sibling("verify_first_boot")
        result["actual_vm_run"] = True  # Attempted, not successful.
        health = verifier.verify_first_boot(bundle, args.boot_timeout, args.ovmf_code, args.ovmf_vars)
        health_file = work / "first-boot-health.json"
        with health_file.open("x", encoding="utf-8") as f:
            json.dump(health, f, indent=2)
        health_file.chmod(0o600)
        result["boot_confirmed"] = health.get("boot_confirmed") is True
        if result["boot_confirmed"] and health.get("status") == "passed":
            result["status"] = "passed"
            step("first_boot_health", "passed", checks=health["checks"])
        else:
            result["status"] = "blocked" if health.get("status") == "blocked" else "failed"
            result["blockers"].append(health.get("reason", "Unverified boot"))
            step("first_boot_health", result["status"], checks=health.get("checks", {}))
        if sha256(base) != trusted:
            result["status"] = "failed"
            result["boot_confirmed"] = False
            result["blockers"].append("Original source image changed during integration test")
        return result
    except Exception as exc:
        # Never persist raw command outputs or guest private identifiers.
        result["status"] = "failed"
        result["boot_confirmed"] = False
        result["blockers"].append("Integration stage raised " + type(exc).__name__)
        step("pipeline_exception", "failed", error_type=type(exc).__name__)
        return result
    finally:
        write_report(work, result)

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preflight", action="store_true", help="check local host tools only, no downloads or writes")
    p.add_argument("--workdir", required=True, help="new private work directory for full run")
    p.add_argument("--session", help="verified device/session evidence (required for run)")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--image", help="existing local image")
    source.add_argument("--download", action="store_true", help="explicitly download pinned Ubuntu 24.04 Cloud Image")
    p.add_argument("--sha256", help="independently verified SHA256 for local source")
    p.add_argument("--public-key", help="real OpenSSH public key path")
    p.add_argument("--hostname", default="uc-e2e")
    p.add_argument("--boot-mode", choices=("bios", "uefi"),
                   help="explicitly choose BIOS/UEFI when inspection reports both")
    p.add_argument("--ovmf-code")
    p.add_argument("--ovmf-vars")
    p.add_argument("--minimum-gib", type=int, default=MIN_AVAILABLE_GIB)
    p.add_argument("--boot-timeout", type=int, default=600)
    p.add_argument("--approve-build", action="store_true")
    p.add_argument("--approve-boot", action="store_true")
    return p

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.preflight:
            location = Path(args.workdir).expanduser().absolute().parent
            report = host_preflight(location, "uefi" if args.download else None,
                                    args.ovmf_code, args.ovmf_vars, args.minimum_gib)
            print(json.dumps(report, indent=2))
            return 0 if not report["blockers"] else 2
        if not args.session or not args.public_key:
            raise ValueError("Run needs --session and --public-key")
        result = run(args)
        print(json.dumps({"workdir": str(Path(args.workdir).absolute()), "status": result["status"],
                          "boot_confirmed": result["boot_confirmed"], "blockers": result["blockers"]}))
        return 0 if result["status"] == "passed" and result["boot_confirmed"] else 2
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERROR: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
