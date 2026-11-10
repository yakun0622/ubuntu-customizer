#!/usr/bin/env python3
"""Assess portability and prepare a conservative image-build manifest.

Reads SHA256-verified discovery evidence. No build or target modification.
A matching CPU architecture alone never establishes physical bootability.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("uc_dossier", HERE / "dossier.py")
dossier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dossier)
progress_spec = importlib.util.spec_from_file_location("uc_image_progress", HERE / "progress.py")
progress = importlib.util.module_from_spec(progress_spec)
progress_spec.loader.exec_module(progress)
inspect_spec = importlib.util.spec_from_file_location("uc_source_image", HERE / "image_inspect.py")
image_inspect = importlib.util.module_from_spec(inspect_spec)
inspect_spec.loader.exec_module(image_inspect)

ARCH = {
    "x86_64": "amd64", "amd64": "amd64",
    "aarch64": "arm64", "arm64": "arm64",
    "armv7l": "armhf", "armv6l": "armhf",
    "riscv64": "riscv64"
}
FORMATS = {"qcow2", "raw"}
TARGETS = {"virtual-machine", "physical-device"}

def text_of(entries, category, name):
    for item, text in entries:
        if item.get("category") == category and item.get("name") == name:
            if item.get("status") == "ok" and text.strip():
                return text.strip(), item["file"]
    return None, None

def detect_arch(cpu, kernel):
    text = (kernel or "") + "\n" + (cpu or "")
    for pattern, name in [
        (r"\b(x86_64|amd64)\b", "amd64"),
        (r"\b(aarch64|arm64)\b", "arm64"),
        (r"\b(armv7l|armv6l)\b", "armhf"),
        (r"\briscv64\b", "riscv64"),
    ]:
        if re.search(pattern, text, flags=re.I):
            return name
    return None

def _plan(session, target, fmt, source_path, source_sha256, source_arch, tick=None, selected_firmware=None):
    if target not in TARGETS or fmt not in FORMATS:
        raise ValueError("Unsupported target or image format")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", source_sha256 or ""):
        raise ValueError("An independently supplied SHA-256 for the base image is required")
    original_source = Path(source_path).expanduser()
    if original_source.is_symlink():
        raise ValueError("Symbolic-link sources are not accepted")
    source = original_source.resolve()
    if not source.is_file():
        raise ValueError("Base image must be an existing regular file")
    if source.stat().st_size == 0:
        raise ValueError("Base image is empty")
    if source.parts[:2] in (("/", "dev"), ("/", "proc"), ("/", "sys")):
        raise ValueError("Pseudo-filesystem sources are not accepted")
    if source_arch not in ("amd64", "arm64", "armhf", "riscv64"):
        raise ValueError("Explicit source architecture is required")
    digest = hashlib.sha256()
    with source.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != source_sha256.lower():
        raise ValueError("Base image checksum mismatch")
    if tick is not None:
        tick(1)  # Trusted source image checksum verified
    manifest, entries = dossier.verify_session(session)
    if tick is not None:
        tick(2)  # Collected evidence checksum verified
    kernel, kernel_evidence = text_of(entries, "identity", "kernel")
    cpu, cpu_evidence = text_of(entries, "identity", "cpu")
    os_release, os_evidence = text_of(entries, "identity", "os")
    model, model_evidence = text_of(entries, "hardware", "device-tree-model")
    dt, dt_evidence = text_of(entries, "pins", "dt-source")
    blocks, blocks_evidence = text_of(entries, "storage", "blocks")
    boot, boot_evidence = text_of(entries, "boot", "boot-files")
    arch = detect_arch(cpu, kernel)
    evidence = {"architecture": [v for v in (kernel_evidence, cpu_evidence) if v],
                "os": os_evidence, "board": model_evidence,
                "device_tree": dt_evidence, "storage": blocks_evidence, "boot": boot_evidence}
    blockers = []
    warnings = []
    if arch is None:
        blockers.append("Architecture not established by available bootstrap evidence")
    elif arch != source_arch:
        blockers.append("Source image architecture does not match discovered device architecture")
    if not os_release:
        warnings.append("OS distribution/version not verified")
    if manifest.get("state") not in ("complete", None):
        blockers.append("Discovery session is incomplete")
    if target == "physical-device":
        blockers.extend([
            "Board firmware and boot chain not independently verified",
            "Bootloader location, partition layout and firmware licensing not validated",
            "Kernel, DTB/ACPI, drivers and storage-controller compatibility not validated",
            "No board-specific image assembly backend selected or tested",
        ])
        if not model and not dt:
            warnings.append("Board identity and device-tree configuration unavailable")
        if not blocks:
            warnings.append("Target storage inventory unavailable")
    else:
        warnings.append("VM portability needs a compatible hypervisor machine model and virtual drivers")
        if not boot:
            warnings.append("No boot files collected; source image bootability must be checked in an isolated VM")
    # Read-only introspection of the IMAGE ITSELF. A declaration is not proof.
    inspected = image_inspect.inspect(source, digest.hexdigest())
    actual = inspected["observations"]
    guest = actual.get("guest_os", {})
    boot_details = actual.get("boot_details", {})
    partition_rows = actual.get("partitions", [])
    measured_arch = guest.get("architecture")
    checks = []
    def check(name, ok, reason, sources):
        checks.append({"name": name, "status": "passed" if ok else "blocked",
                       "reason": None if ok else reason, "evidence": sources})
        if not ok:
            blockers.append(reason)
    check("disk_format", actual.get("format") in ("raw", "qcow2"),
          "Image disk format could not be verified", ["qemu-img:format"])
    check("partition_table", actual.get("partition_table") in ("gpt", "mbr"),
          "Image partition table (GPT/MBR) could not be verified", ["guestfish:part-get-parttype"])
    check("partitions", any(row.get("type", "").lower() == "partition" for row in partition_rows),
          "Image has no verified partition inventory", ["virt-filesystems:partitions"])
    check("guest_architecture", bool(measured_arch and measured_arch == source_arch and measured_arch == arch),
          "Guest architecture cannot be proven to match both declaration and target",
          ["virt-inspector:operatingsystem/arch", *evidence["architecture"]])
    check("guest_os", guest.get("os_class") == "linux" and bool(guest.get("distribution")),
          "Source guest Linux distribution could not be established",
          ["virt-inspector:operatingsystem/name", "virt-inspector:operatingsystem/distro"])
    check("kernel", bool(boot_details.get("kernels")),
          "No installed, bootloader-referenced kernel was verified",
          ["virt-drivers:operatingsystem/bootloader/kernel"])
    observed_modes = sorted(set(mode for mode in
        (boot_details.get("boot_modes") or [boot_details.get("boot_mode")])
        if mode in ("uefi", "bios")))
    chosen_mode = selected_firmware or boot_details.get("boot_mode")
    check("boot_firmware", chosen_mode in observed_modes,
          "Guest firmware choice is absent, unsupported or ambiguous; select one inspected BIOS/UEFI mode explicitly",
          ["virt-drivers:firmware"])
    check("bootloader", bool(boot_details.get("bootloader")),
          "Source image bootloader could not be identified",
          ["virt-drivers:operatingsystem/bootloader"])
    if guest.get("distribution") and os_release:
        if guest["distribution"].lower() not in os_release.lower():
            warnings.append("Source Linux distribution differs from inspected target distribution; cross-distribution configuration not validated")
    for gap in inspected["gaps"]:
        warnings.append("Image inspection gap: " + gap["check"] + " (" + gap["reason"] + ")")
    # Offline, verified image conversion is allowed only for the VM path.
    backend = "qemu-img-offline-convert" if target == "virtual-machine" else None
    return {
        "schema_version": 1, "type": "ubuntu-customizer/image-plan",
        "target": target, "format": fmt, "architecture": arch,
        "source": {"path": str(source), "sha256": digest.hexdigest(), "bytes": source.stat().st_size,
                   "claimed_architecture": source_arch,
                   "architecture_verified": bool(measured_arch and measured_arch == source_arch),
                   "inspection": inspected},
        "discovery": {"session": str(Path(session).resolve()),
                      "transport": manifest.get("transport"), "evidence": evidence},
        "boot_compatibility": {"supported_modes": observed_modes, "selected": chosen_mode},
        "backend": backend, "build_allowed": target == "virtual-machine" and not blockers,
        "blockers": blockers, "warnings": warnings,
        "compatibility": {"status": "blocked" if blockers else "candidate",
                          "checks": checks, "note": "Candidate for offline conversion, not proof of target bootability"},
        "verification_required": [
            "Inspect source partition table and expected boot mode",
            "Confirm source image architecture, bootloader and guest OS against target",
            "Boot-test output in an isolated QEMU VM matching desired machine/firmware",
            "Record first-boot initialization, machine identity and network behavior",
        ],
        "restrictions": [
            "Conversion is not a system installation and does not guarantee guest boot",
            "Never write images directly to block devices",
            "Physical board images require separately approved board-specific builders",
            "No credentials, SSH host keys or machine identity should be cloned blindly",
        ]
    }


def plan(session, target, fmt, source_path, source_sha256, source_arch, selected_firmware=None):
    # CLI callers and the device manager share exactly one tracked entrypoint.
    # A compatibility blocker is not a process failure; it is a safe decision.
    with progress.tracking(session, "image-plan", 4) as tracker:
        result = _plan(session, target, fmt, source_path, source_sha256,
                       source_arch, tick=tracker.advance, selected_firmware=selected_firmware)
        tracker.advance(3)  # Read-only guest image inspection completed
        tracker.advance(4)  # Compatibility decision produced
        if result["blockers"]:
            tracker.blocked()
        return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session")
    p.add_argument("--target", choices=sorted(TARGETS), required=True)
    p.add_argument("--format", choices=sorted(FORMATS), required=True)
    p.add_argument("--source", required=True, help="existing locally stored image")
    p.add_argument("--sha256", required=True, help="trusted SHA256 obtained independently")
    p.add_argument("--source-arch", choices=("amd64", "arm64", "armhf", "riscv64"), required=True)
    p.add_argument("--boot-mode", choices=("bios", "uefi"), help="select one mode reported by guest inspection")
    p.add_argument("--output", required=True, help="new JSON plan path")
    args = p.parse_args(argv)
    try:
        result = plan(args.session, args.target, args.format, args.source, args.sha256,
                      args.source_arch, selected_firmware=args.boot_mode)
        output = Path(args.output)
        if output.exists() or output.is_symlink():
            raise ValueError("Output already exists")
        with output.open("x", encoding="utf-8") as out:
            json.dump(result, out, indent=2, ensure_ascii=False)
            out.write("\n")
        output.chmod(0o600)
        print(f"Image plan: {output}; build_allowed={result['build_allowed']}; blockers={len(result['blockers'])}")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Plan derivation might have succeeded while persisting the JSON failed.
        # The CLI outcome must take precedence over the earlier stage result.
        progress.report_error(args.session, "image-plan")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
