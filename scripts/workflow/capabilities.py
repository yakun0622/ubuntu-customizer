#!/usr/bin/env python3
"""Summarize available device discovery capabilities from verified evidence.

No device-specific heuristics or target access. Missing probes are unknown,
not evidence of missing hardware.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("uc_dossier", Path(__file__).with_name("dossier.py"))
dossier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dossier)

CAPABILITIES = {
    "system_identity": [("identity", "os"), ("identity", "kernel")],
    "processor_memory": [("identity", "cpu"), ("identity", "memory")],
    "storage": [("storage", "blocks")],
    "network": [("network", "ip-link"), ("network", "ip-route")],
    "kernel_driver_bindings": [("drivers", "sysfs-bindings"), ("drivers", "platform-bindings")],
    "peripheral_buses": [("hardware", "bus-devices")],
    "device_tree": [("pins", "dt-source"), ("hardware", "device-tree-compatible")],
    "gpio_pinctrl": [("pins", "gpioinfo"), ("pins", "pinctrl")],
    "boot_artifacts": [("boot", "boot-files")],
}
BAD = {"unavailable", "error", "truncated", "empty"}

def analyze(session):
    manifest, records = dossier.verify_session(session)
    index = {(item["category"], item["name"]): (item, value) for item, value in records}
    result = {}
    for name, probes in CAPABILITIES.items():
        observations = []
        for key in probes:
            if key not in index:
                observations.append({"probe": "/".join(key), "state": "not_collected"})
                continue
            item, value = index[key]
            status = item.get("status", "unknown")
            if status == "ok" and (not value.strip() or "unavailable" in value.strip().lower()[:120]):
                status = "unknown"
            observations.append({"probe": "/".join(key), "state": status,
                                 "source": item.get("file")})
        available = sum(x["state"] == "ok" for x in observations)
        result[name] = {
            "state": "available" if available == len(probes) else
                     "partial" if available else "unknown",
            "probes": observations
        }
    return {
        "schema_version": 1, "type": "ubuntu-customizer/capability-report",
        "transport": manifest.get("transport"),
        "target_label": manifest.get("target"),
        "capabilities": result,
        "limitations": "Capability states describe observable diagnostics, not proof that a peripheral exists or works. 'unknown' includes absent tooling and insufficient permissions."
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        report = analyze(args.session)
        output = Path(args.output) if args.output else Path(args.session) / "capabilities.json"
        if output.exists() or output.is_symlink():
            raise ValueError("Refusing to overwrite capability report")
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        output.chmod(0o600)
        print(f"Capability report: {output}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
