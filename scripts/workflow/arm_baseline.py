#!/usr/bin/env python3
"""Acquire a pinned official ARM64 Ubuntu Base rootfs into this project's outputs.

This is a userspace rootfs archive, NOT a bootable board image. No host file
search, no reading arbitrary source paths, no extraction and no device writes.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "uc_workspace_arm_baseline", HERE / "project_workspace.py")
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)

BASELINE = {
    "id": "ubuntu-base-24.04.5-arm64",
    "distribution": "ubuntu",
    "release": "24.04.5",
    "architecture": "arm64",
    "filename": "ubuntu-base-24.04.5-base-arm64.tar.gz",
    "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.5-base-arm64.tar.gz",
    "sha256": "a91d5a93010193712d346d761372b7c9db6dfcf093893161c64ca107f05914f2",
    "source_sha256_url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/SHA256SUMS",
    "kind": "rootfs-tarball",
    "bootable": False,
    "includes_board_kernel": False,
    "includes_board_dtb": False,
    "includes_board_bootloader": False,
}
MAX_BYTES = 128 * 1024 * 1024


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def planned():
    """Offline source selection: never inspect the host for candidate images."""
    return dict(BASELINE, downloaded=False, note=(
        "Official minimal ARM64 userspace only; board boot components must "
        "be adapted in subsequent iterations."))


def acquire(approved=False):
    """Stream a pinned HTTPS source to outputs; preserve its original bytes."""
    if not approved:
        raise ValueError("Official baseline download requires explicit approval")
    # Fail closed when not started in this repository's actual current directory.
    base = workspace.project_root()
    output = workspace.output_path("baselines", root=base)
    output.mkdir(mode=0o700, exist_ok=True)
    destination = workspace.output_path("baselines", BASELINE["filename"], root=base)
    report = workspace.output_path("baselines", BASELINE["id"] + ".json", root=base)
    if destination.exists() or destination.is_symlink():
        if not destination.is_file() or sha256_file(destination) != BASELINE["sha256"]:
            raise ValueError("Existing baseline is not the pinned official source")
    else:
        temporary = workspace.output_path(
            "baselines", "." + BASELINE["filename"] + "." + secrets.token_hex(8) + ".part",
            root=base)
        try:
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            digest = hashlib.sha256()
            count = 0
            try:
                with os.fdopen(fd, "wb") as stream:
                    request = Request(BASELINE["url"], headers={"User-Agent": "ubuntu-customizer/arm-baseline"})
                    with urlopen(request, timeout=60) as remote:
                        for part in iter(lambda: remote.read(1024 * 1024), b""):
                            count += len(part)
                            if count > MAX_BYTES:
                                raise ValueError("Official baseline exceeds size cap")
                            stream.write(part)
                            digest.update(part)
                if digest.hexdigest() != BASELINE["sha256"]:
                    raise ValueError("Official baseline checksum mismatch")
                if destination.exists() or destination.is_symlink():
                    raise ValueError("Baseline destination was created concurrently")
                os.link(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    result = dict(BASELINE, downloaded=True,
                  file=str(destination), bytes=destination.stat().st_size,
                  checksum_verified=True)
    if report.exists() or report.is_symlink():
        existing = json.loads(workspace.checked_input(report).read_text(encoding="utf-8"))
        if existing != result:
            raise ValueError("Existing baseline metadata differs from verified source")
    else:
        fd = os.open(report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-download", action="store_true",
                        help="Allow one pinned HTTPS download under ./outputs")
    args = parser.parse_args(argv)
    try:
        result = acquire(True) if args.approved_download else planned()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
