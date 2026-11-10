#!/usr/bin/env python3
"""Read-only physical ARM device static-image and serial boot-log evidence.

Never flash, connect, reset a device, or infer verified boot solely from
unauthenticated UART text. Existing collected sessions may be checked against
their SHA256 evidence manifest. Optional RAW/QCOW2 image introspection is
advisory: a generic guest OS inspection does not validate a board BSP/DTB.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
MAX_LOG = 4 * 1024 * 1024
MARKERS = (
    ("uboot", r"\bU-Boot\s+(?:20\d\d|v20\d\d)"),
    ("kernel", r"\bLinux version\s+\d"),
    ("fdt", r"(?:Machine model:|OF: fdt:)"),
    ("root_mounted", r"(?:VFS: Mounted root|mounted filesystem with ordered data mode|EXT4-fs .+ mounted filesystem)"),
    ("init_started", r"(?:Run /sbin/init as init process|systemd\[1\]:|Welcome to (?:Armbian|Ubuntu|Debian))"),
    ("login_prompt", r"(?:^|\s)(?:[A-Za-z0-9_.-]{1,64}\s+)?login:\s*$"),
    ("network_link", r"(?:Link is Up|Link detected: yes|link up - \d{2,4}Mbps)"),
    ("kernel_panic", r"(?:Kernel panic|not syncing:|VFS: Unable to mount root fs)"),
    ("init_failure", r"(?:Failed to execute /sbin/init|No working init found)"),
    ("emergency_mode", r"(?:You are in emergency mode|Entering emergency mode)"),
)
COMPILED = [(name, re.compile(pattern, re.I)) for name, pattern in MARKERS]

def sibling(name):
    spec = importlib.util.spec_from_file_location("uc_physical_" + name,
                                                  HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def hash_file(path):
    result = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()

def safe_log(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Boot log must be a regular non-symlink local file")
    if path.stat().st_size > MAX_LOG:
        raise ValueError("Boot log exceeds 4 MiB read-only limit")
    return path.resolve()

def classify_log(raw):
    """Return only marker IDs and line numbers; do not expose raw serial data."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_LOG * 3:
        raise ValueError("Invalid or oversized boot log")
    hits = {}
    for line_no, line in enumerate(raw.splitlines(), 1):
        # Limit scan complexity and prevent attacker-controlled mega-lines.
        line = line[:2000]
        for name, regex in COMPILED:
            if name not in hits and regex.search(line):
                hits[name] = line_no
    blockers = [name for name in ("kernel_panic", "init_failure", "emergency_mode")
                if name in hits]
    userspace = "init_started" in hits or "login_prompt" in hits
    state = "boot_error_observed" if blockers else (
        "userspace_markers_observed" if "kernel" in hits and userspace else
        "partial_boot_evidence")
    return {"state": state, "markers": hits, "boot_errors": blockers,
            "kernel_observed": "kernel" in hits,
            "userspace_observed": userspace,
            "network_link_observed": "network_link" in hits,
            "boot_confirmed": False,
            "reason": "Unauthenticated serial text cannot certify successful boot or device identity"}

def check_session(session, bootlog=None):
    """Session verification is separate from any untrusted external boot log."""
    if session is None:
        return {"provided": False, "manifest_verified": False,
                "log_bound_to_session": False}
    dossier = sibling("dossier")
    manifest, entries = dossier.verify_session(session)
    link = False
    if bootlog is not None:
        digest = hash_file(bootlog)
        # Require matching SHA and exact evidence file path inside this session.
        entry_files = {(Path(session).resolve() / item["file"]).resolve(): item["sha256"]
                       for item in manifest["items"] if "file" in item and "sha256" in item}
        link = entry_files.get(Path(bootlog).resolve()) == digest
    return {"provided": True, "manifest_verified": True,
            "log_bound_to_session": link, "session_items": len(entries)}

def inspect_image(image, checksum):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", checksum or ""):
        raise ValueError("Trusted SHA-256 required for optional source image")
    source = sibling("image_inspect").safe_source(image)
    if hash_file(source) != checksum.lower():
        raise ValueError("Physical candidate image SHA-256 mismatch")
    result = sibling("image_inspect").inspect(source, checksum.lower())
    observation = result.get("observations", {})
    return {"image_sha256": checksum.lower(), "disk_format": observation.get("format"),
            "partition_table": observation.get("partition_table"),
            "guest_architecture": observation.get("guest_os", {}).get("architecture"),
            "guest_os": observation.get("guest_os", {}).get("distribution"),
            "kernel_versions": [
                x.get("version") for x in observation.get("boot_details", {}).get("kernels", [])
                if isinstance(x, dict)],
            "inspection_gaps": [gap.get("check") for gap in result.get("gaps", [])],
            "physical_bsp_verified": False,
            "bootloader_dtb_compatibility": "unverified"}

def evaluate(log=None, session=None, image=None, sha256=None):
    if not any((log, session, image)):
        raise ValueError("Supply a boot log, a verified session, or a source image")
    if bool(image) != bool(sha256):
        raise ValueError("Image and trusted SHA-256 must be supplied together")
    log_file = safe_log(log) if log else None
    session_summary = check_session(session, log_file)
    report = {"schema_version": 1, "type": "ubuntu-customizer/physical-boot-evidence",
              "target": "physical-device", "session": session_summary,
              "boot_log": None, "static_image": None,
              "boot_confirmed": False, "physical_deployment_allowed": False,
              "missing_gates": ["exact_board_identity", "BSP_kernel_DTB", "bootloader",
                                "storage_layout", "recovery", "authenticated_live_health"]}
    if log_file:
        observed = classify_log(log_file.read_bytes())
        report["boot_log"] = {"source_sha256": hash_file(log_file), "bytes": log_file.stat().st_size,
                              **observed}
    if image:
        report["static_image"] = inspect_image(image, sha256)
    report["state"] = ("boot_error_observed" if report["boot_log"] and
                       report["boot_log"]["state"] == "boot_error_observed" else
                       "evidence_only")
    return report

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", help="existing local captured serial/UART boot log")
    p.add_argument("--session", help="optional SHA256-verified device discovery session")
    p.add_argument("--image", help="optional RAW/QCOW2 image for read-only structure check")
    p.add_argument("--sha256", help="trusted hash for --image")
    p.add_argument("--output", required=True, help="NEW private JSON evidence report")
    args = p.parse_args(argv)
    try:
        result = evaluate(args.log, args.session, args.image, args.sha256)
        output = Path(args.output).expanduser()
        if output.is_symlink() or output.exists() or not output.parent.is_dir():
            raise ValueError("Output report must be a new file")
        import os
        fd = os.open(output, os.O_WRONLY | os.O_EXCL | os.O_CREAT, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
                f.write("\n")
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        print(json.dumps({"report": str(output), "state": result["state"],
                          "boot_confirmed": False, "deploy_allowed": False}))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("ERROR: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
