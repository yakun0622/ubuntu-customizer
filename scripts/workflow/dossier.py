#!/usr/bin/env python3
"""Build a provenance-preserving device dossier from collect.py evidence.

This program never connects to a target or executes a probe. A 'missing'
observation is not an assertion that hardware is absent.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_FILE = 524288
CATEGORIES = ("identity", "hardware", "drivers", "pins", "network", "storage", "boot", "serial")
SENSITIVE = ("serial", "mac", "address", "ip")

def verify_session(path):
    path = Path(path).resolve()
    manifest_file = path / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("items"), list):
        raise ValueError("Unsupported manifest format")
    findings = []
    for item in manifest["items"]:
        rel = item.get("file")
        if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ValueError("Unsafe evidence path")
        f = path / rel
        if not f.resolve().is_relative_to(path) or not f.is_file() or f.is_symlink():
            raise ValueError("Missing or unsafe evidence file: " + rel)
        if f.stat().st_size > MAX_FILE:
            raise ValueError("Evidence file exceeds size cap: " + rel)
        raw = f.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
            raise ValueError("Evidence digest mismatch: " + rel)
        if item.get("category") not in CATEGORIES:
            raise ValueError("Unknown evidence category")
        findings.append((item, raw.decode("utf-8", errors="replace")))
    return manifest, findings

def property_value(entries, category, name):
    for item, value in entries:
        if item.get("category") == category and item.get("name") == name:
            return item, value
    return None, None

def observation(item, value, parse=lambda x: x.strip()):
    if item is None:
        return {"state": "not_collected", "value": None, "source": None}
    status = item.get("status")
    if status != "ok":
        return {"state": status or "unknown", "value": None, "source": item["file"]}
    result = parse(value)
    if not result or result == "unavailable":
        return {"state": "unknown", "value": None, "source": item["file"]}
    return {"state": "observed", "value": result, "source": item["file"]}

def parse_os(text):
    parsed = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("ID", "VERSION_ID", "PRETTY_NAME", "ID_LIKE"):
            parsed[key] = value.strip().strip('"').replace("\\n", " ")
    return parsed or None

def first_line(value):
    return value.splitlines()[0].strip() if value.strip() else None

def parse_cpu(value):
    # Keep the original source separately; the extracted fields are conservative.
    out = {}
    for line in value.splitlines():
        if ":" not in line:
            continue
        k, v = (piece.strip() for piece in line.split(":", 1))
        if k in ("model name", "Hardware", "Processor", "CPU implementer", "CPU part", "cpu model"):
            out.setdefault(k, v)
    return out or None

def parse_links(value):
    # ip -s link output includes interface header lines; flags can be multiline.
    names = []
    for line in value.splitlines():
        found = re.match(r"^\d+:\s+([^:]+):\s+", line)
        if found:
            name = found.group(1).split("@", 1)[0]
            if name not in names:
                names.append(name)
    return names or None

def make_dossier(session):
    manifest, entries = verify_session(session)
    specs = [
        ("os", "identity", "os", parse_os),
        ("kernel", "identity", "kernel", first_line),
        ("cpu", "identity", "cpu", parse_cpu),
        ("memory", "identity", "memory", lambda x: {"raw_available": bool(x.strip()), "mem_total_kib": int(re.search(r"^MemTotal:\s+(\d+)", x, re.M).group(1)) if re.search(r"^MemTotal:\s+(\d+)", x, re.M) else None}),
        ("board_model", "hardware", "device-tree-model", first_line),
        ("compatible", "hardware", "device-tree-compatible", lambda x: [v for v in x.splitlines() if v and v != "unavailable"] or None),
        ("network_interfaces", "network", "ip-link", parse_links),
    ]
    identity = {}
    for key, cat, name, parser in specs:
        item, value = property_value(entries, cat, name)
        identity[key] = observation(item, value, parser)
    assets = {}
    for item, _ in entries:
        assets.setdefault(item["category"], []).append({
            "name": item["name"], "source": item["file"], "status": item.get("status", "unknown"),
            "sha256": item["sha256"], "bytes": item.get("bytes", 0)
        })
    missing = [{"category": item["category"], "name": item["name"], "reason": item.get("status")}
               for item, _ in entries if item.get("status") != "ok"]
    return {
        "schema_version": 1,
        "type": "ubuntu-customizer/device-dossier",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session": str(Path(session).resolve()),
        "transport": manifest.get("transport"),
        "target_label": manifest.get("target"),
        "identity": identity,
        "evidence": assets,
        "gaps": missing,
        "pin_mapping": {"state": "unverified", "note": "Software pinctrl/GPIO evidence does not establish physical PCB wiring."},
        "driver_bindings": {"state": "not_analyzed", "note": "Raw driver evidence indexed; device-driver relation analysis requires further probes."},
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", help="existing discovery session containing manifest.json")
    parser.add_argument("--output", help="new dossier JSON path; defaults to session/device.json")
    args = parser.parse_args(argv)
    try:
        dossier = make_dossier(args.session)
        output = Path(args.output) if args.output else Path(args.session) / "device.json"
        if output.exists() or output.is_symlink():
            raise ValueError("Output exists; refusing overwrite: " + str(output))
        output.write_text(json.dumps(dossier, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        output.chmod(0o600)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Device dossier: {output}; evidence categories: {len(dossier['evidence'])}; collection gaps: {len(dossier['gaps'])}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
