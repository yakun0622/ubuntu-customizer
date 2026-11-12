#!/usr/bin/env python3
"""Create a local content snapshot of explicitly named regular files.

No implicit /etc-wide collection; no symlinks, devices or directory recursion.
Does not restore files or change the system. A snapshot is NOT a complete rollback.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="new directory to create; must not exist")
    parser.add_argument("files", nargs="+", help="absolute paths to regular files")
    args = parser.parse_args()
    try:
        out = workspace.checked_output(args.output_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if out.exists() or out.is_symlink():
        parser.error("Output directory must be new under ./outputs")
    sources = []
    for index, item in enumerate(args.files):
        src = Path(item)
        if not src.is_absolute():
            parser.error(f"Not an absolute path: {item}")
        try:
            st = src.lstat()
        except OSError as exc:
            parser.error(str(exc))
        if not stat.S_ISREG(st.st_mode):
            parser.error(f"Refusing non-regular file: {item}")
        if st.st_size > 20 * 1024 * 1024:
            parser.error(f"Refusing file larger than 20 MiB: {item}")
        sources.append((src, st))
    out.mkdir(mode=0o700, parents=False)
    manifest = {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "files": []}
    try:
        for i, (src, original) in enumerate(sources):
            # O_NOFOLLOW avoids following symlinks replaced after lstat.
            fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                now = os.fstat(fd)
                if not stat.S_ISREG(now.st_mode) or (now.st_dev, now.st_ino) != (original.st_dev, original.st_ino):
                    raise RuntimeError(f"Source changed during snapshot: {src}")
                name = f"{i:04d}.backup"
                target = out / name
                digest = hashlib.sha256()
                with os.fdopen(fd, "rb", closefd=False) as source, target.open("xb") as dest:
                    while True:
                        block = source.read(65536)
                        if not block:
                            break
                        digest.update(block)
                        dest.write(block)
                os.chmod(target, 0o600)
                manifest["files"].append({"source": str(src), "backup": name, "sha256": digest.hexdigest(), "mode": stat.S_IMODE(now.st_mode), "uid": now.st_uid, "gid": now.st_gid})
            finally:
                os.close(fd)
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.chmod(out / "manifest.json", 0o600)
    except Exception:
        shutil.rmtree(out)
        raise
    print(json.dumps({"snapshot": str(out), "files": len(sources), "notice": "Backup created, restore must be planned and approved."}))
    return 0

workspace_spec = importlib.util.spec_from_file_location(
    "uc_snapshot_workspace", Path(__file__).resolve().parents[1] / "workflow" / "project_workspace.py")
workspace = importlib.util.module_from_spec(workspace_spec)
workspace_spec.loader.exec_module(workspace)

if __name__ == "__main__":
    raise SystemExit(main())
