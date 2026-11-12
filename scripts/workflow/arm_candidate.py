#!/usr/bin/env python3
"""Stage versioned, board-specific ARM boot components beside a verified rootfs.

All local reads stay inside the active project; all outputs stay in outputs.
Never assume that an ARM rootfs or this staging bundle is USB bootable.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "uc_workspace_arm_candidate", HERE / "project_workspace.py")
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)
BASE_SPEC = importlib.util.spec_from_file_location(
    "uc_arm_baseline_candidate", HERE / "arm_baseline.py")
baseline = importlib.util.module_from_spec(BASE_SPEC)
BASE_SPEC.loader.exec_module(baseline)

BOARD = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")
COMPONENTS = ("kernel", "dtb", "bootloader", "firmware")
COMPONENT_LIMIT = 256 * 1024 * 1024


def verified_baseline(report):
    path = workspace.checked_input(report, max_bytes=32 * 1024)
    record = json.loads(path.read_text(encoding="utf-8"))
    source = baseline.BASELINE
    if not isinstance(record, dict) or not all(
            record.get(key) == source[key] for key in
            ("id", "sha256", "architecture", "kind", "url")):
        raise ValueError("Baseline report does not match pinned official source")
    archive = workspace.checked_input(record.get("file"), max_bytes=baseline.MAX_BYTES)
    if archive.name != source["filename"] or baseline.sha256_file(archive) != source["sha256"]:
        raise ValueError("Baseline archive failed independent hash validation")
    return archive


def stage(board, report, revision, component_paths=None, evidence=None):
    """Create a non-overwriting iteration folder; original input files stay intact."""
    if not BOARD.fullmatch(board) or not 1 <= revision <= 9999:
        raise ValueError("Invalid board or revision")
    paths = component_paths or {}
    if not isinstance(paths, dict) or set(paths) - set(COMPONENTS):
        raise ValueError("Unrecognized ARM component type")
    archive = verified_baseline(report)
    evidence_path = workspace.checked_input(evidence, max_bytes=4 * 1024 * 1024) if evidence else None
    evidence_summary = None
    if evidence_path:
        # Tie the candidate to actual device evidence, not just a supplied
        # filename. Every referenced read remains within this project.
        session = json.loads(evidence_path.read_text(encoding="utf-8"))
        if (not isinstance(session, dict) or session.get("schema_version") != 1
                or not isinstance(session.get("items"), list)
                or len(session["items"]) > 512):
            raise ValueError("Invalid device evidence manifest")
        categories = set()
        for item in session["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("file"), str):
                raise ValueError("Invalid device evidence item")
            evidence_file = workspace.checked_input(
                evidence_path.parent / item["file"], max_bytes=4 * 1024 * 1024)
            digest = item.get("sha256")
            if (not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)
                    or baseline.sha256_file(evidence_file) != digest.lower()):
                raise ValueError("Device evidence hash mismatch")
            categories.add(str(item.get("category", "unknown"))[:32])
        evidence_summary = {
            "manifest_sha256": baseline.sha256_file(evidence_path),
            "items_hash_verified": len(session["items"]),
            "categories": sorted(categories),
        }
    inputs = {
        key: workspace.checked_input(value, max_bytes=COMPONENT_LIMIT)
        for key, value in paths.items()
    }
    base = workspace.output_path("arm-candidates", board)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = workspace.output_path("arm-candidates", board, "rev-%04d" % revision)
    folder.mkdir(mode=0o700)  # fail if revision exists
    components = {}
    try:
        for key, path in inputs.items():
            target = workspace.output_path("arm-candidates", board,
                                           folder.name, key + path.suffix)
            # Protect against implicit hardlink/symlink creation or overwrite.
            with path.open("rb") as stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output, length=1024 * 1024)
            target.chmod(0o600)
            components[key] = {
                "file": str(target.relative_to(workspace.project_root())),
                "sha256": baseline.sha256_file(target),
                "bytes": target.stat().st_size,
            }
        missing = [part for part in ("kernel", "dtb", "bootloader")
                   if part not in components]
        result = {
            "schema_version": 1,
            "type": "ubuntu-customizer/arm-candidate-stage",
            "board": board, "revision": revision,
            "base_archive": str(archive.relative_to(workspace.project_root())),
            "base_sha256": baseline.BASELINE["sha256"],
            "evidence": str(evidence_path.relative_to(workspace.project_root())) if evidence_path else None,
            "evidence_summary": evidence_summary,
            "components": components,
            "missing_boot_components": missing,
            "rootfs_verified": True,
            "bootable_image_created": False,
            "boot_confirmed": False,
            "deployment_allowed": False,
            "next_action": ("locate_or_extract_board_components" if missing
                            else "assemble_board_boot_image_and_verify_usb"),
        }
        manifest = workspace.output_path("arm-candidates", board,
                                         folder.name, "candidate.json")
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        manifest.chmod(0o600)
        return result
    except BaseException:
        # Never replace a previous revision, and clean only this new folder.
        shutil.rmtree(folder)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True)
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--baseline", default="outputs/baselines/ubuntu-base-24.04.5-arm64.json")
    parser.add_argument("--evidence", help="Existing project-local evidence manifest")
    for part in COMPONENTS:
        parser.add_argument("--" + part, help="Optional project-local board component")
    args = parser.parse_args(argv)
    try:
        found = {name: getattr(args, name) for name in COMPONENTS if getattr(args, name)}
        result = stage(args.board, args.baseline, args.revision, found, args.evidence)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
