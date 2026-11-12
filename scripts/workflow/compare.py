#!/usr/bin/env python3
"""Compare two verified device dossier snapshots without contacting devices."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

FIELDS = ("os", "kernel", "cpu", "memory", "board_model", "compatible", "network_interfaces")

def compare(a, b):
    changes = []
    for field in FIELDS:
        old = a.get("identity", {}).get(field, {})
        new = b.get("identity", {}).get(field, {})
        if old.get("state") != new.get("state") or old.get("value") != new.get("value"):
            changes.append({"field": field, "before": old, "after": new})
    old_assets = {(category, asset["name"]): asset for category, assets in a.get("evidence", {}).items() for asset in assets}
    new_assets = {(category, asset["name"]): asset for category, assets in b.get("evidence", {}).items() for asset in assets}
    evidence_changes = []
    for key in sorted(old_assets.keys() | new_assets.keys()):
        previous, current = old_assets.get(key), new_assets.get(key)
        if previous is None or current is None or previous.get("sha256") != current.get("sha256") or previous.get("status") != current.get("status"):
            evidence_changes.append({"category": key[0], "name": key[1],
                                     "before": None if previous is None else {"sha256": previous.get("sha256"), "status": previous.get("status")},
                                     "after": None if current is None else {"sha256": current.get("sha256"), "status": current.get("status")}})
    return {"schema_version": 1, "before_session": a.get("session"), "after_session": b.get("session"),
            "identity_changes": changes, "evidence_changes": evidence_changes,
            "warning": "Changes to dynamic counters or listings may be normal. A changed evidence hash is not proof of a hardware change."}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--output", help="new JSON output; by default print to stdout")
    args = parser.parse_args(argv)
    try:
        before = json.loads(workspace.checked_input(args.before).read_text())
        after = json.loads(workspace.checked_input(args.after).read_text())
        if before.get("type") != "ubuntu-customizer/device-dossier" or after.get("type") != "ubuntu-customizer/device-dossier":
            raise ValueError("Expected device dossiers created by dossier.py")
        result = compare(before, after)
        body = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            p = workspace.checked_output(args.output)
            if p.exists() or p.is_symlink():
                raise ValueError("Refusing to overwrite comparison file")
            p.write_text(body)
            p.chmod(0o600)
        else:
            print(body, end="")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

ws_spec = importlib.util.spec_from_file_location(
    "uc_workspace_compare", Path(__file__).with_name("project_workspace.py"))
workspace = importlib.util.module_from_spec(ws_spec)
ws_spec.loader.exec_module(workspace)

if __name__ == "__main__":
    raise SystemExit(main())
