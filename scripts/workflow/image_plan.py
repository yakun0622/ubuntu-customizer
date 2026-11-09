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

def plan(session, target, fmt, source_path, source_sha256):
    if target not in TARGETS or fmt not in FORMATS:
        raise ValueError("Unsupported target or image format")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", source_sha256 or ""):
        raise ValueError("An independently supplied SHA-256 for the base image is required")
    source = Path(source_path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise ValueError("Base image must be an existing regular file")
    if source.stat().st_size == 0:
        raise ValueError("Base image is empty")
    digest = hashlib.sha256()
    with source.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != source_sha256.lower():
        raise ValueError("Base image checksum mismatch")
    manifest, entries = dossier.verify_session(session)
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
    # Offline, verified image conversion is allowed only for the VM path.
    backend = "qemu-img-offline-convert" if target == "virtual-machine" else None
    return {
        "schema_version": 1, "type": "ubuntu-customizer/image-plan",
        "target": target, "format": fmt, "architecture": arch,
        "source": {"path": str(source), "sha256": digest.hexdigest(), "bytes": source.stat().st_size},
        "discovery": {"session": str(Path(session).resolve()),
                      "transport": manifest.get("transport"), "evidence": evidence},
        "backend": backend, "build_allowed": target == "virtual-machine" and not blockers,
        "blockers": blockers, "warnings": warnings,
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

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session")
    p.add_argument("--target", choices=sorted(TARGETS), required=True)
    p.add_argument("--format", choices=sorted(FORMATS), required=True)
    p.add_argument("--source", required=True, help="existing locally stored image")
    p.add_argument("--sha256", required=True, help="trusted SHA256 obtained independently")
    p.add_argument("--output", required=True, help="new JSON plan path")
    args = p.parse_args(argv)
    try:
        result = plan(args.session, args.target, args.format, args.source, args.sha256)
        output = Path(args.output)
        if output.exists() or output.is_symlink():
            raise ValueError("Output already exists")
        with output.open("x", encoding="utf-8") as out:
            json.dump(result, out, indent=2, ensure_ascii=False)
            out.write("\n")
        output.chmod(0o600)
        print(f"Image plan: {output}; build_allowed={result['build_allowed']}; blockers={len(result['blockers'])}")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
