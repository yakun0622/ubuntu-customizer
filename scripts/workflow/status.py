#!/usr/bin/env python3
"""Publish a minimal, non-sensitive Agent Skill progress checkpoint.

Only allowlisted stage, state and integer counters. No free-form text,
credentials, paths or command output are persisted. The agent owns the stage.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

STAGES = ("connect", "bootstrap", "capability", "collect", "analyze",
          "image-plan", "image-build", "rootfs-build", "first-boot", "verify", "finish")
STATES = ("pending", "running", "complete", "failed", "blocked")
MAX_STEPS = 1000000

def update(session, stage, state, done=0, total=0):
    if stage not in STAGES or state not in STATES:
        raise ValueError("Unsupported stage or state")
    if not (isinstance(done, int) and isinstance(total, int)
            and 0 <= done <= total <= MAX_STEPS):
        raise ValueError("Invalid progress counters")
    folder = Path(session).expanduser()
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Session folder must exist")
    target = folder / "skill-status.json"
    if target.is_symlink():
        raise ValueError("Refusing status symlink")
    payload = {"schema_version": 1, "stage": stage, "state": state,
               "completed": done, "total": total,
               "updated_at": datetime.now(timezone.utc).isoformat()}
    temp = folder / ("." + uuid.uuid4().hex + ".status.tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        temp.chmod(0o600)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    return payload

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session")
    p.add_argument("--stage", choices=STAGES, required=True)
    p.add_argument("--state", choices=STATES, required=True)
    p.add_argument("--completed", type=int, default=0)
    p.add_argument("--total", type=int, default=0)
    args = p.parse_args(argv)
    try:
        print(json.dumps(update(args.session, args.stage, args.state, args.completed, args.total)))
        return 0
    except (OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
