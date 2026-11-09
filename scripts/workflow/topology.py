#!/usr/bin/env python3
"""Derive conservative device-driver topology from SHA256-verified discovery evidence.

No live target access. Binding edges represent observed Linux sysfs relationships,
not board electrical connectivity, pinctrl assignments or full DT graph.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("uc_dossier", Path(__file__).with_name("dossier.py"))
dossier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dossier)
MAX_ROWS = 5000
SAFE = re.compile(r"^[A-Za-z0-9_:.@+/-]{1,512}$")
INPUTS = {
    ("drivers", "sysfs-bindings"),
    ("drivers", "platform-bindings"),
    ("hardware", "bus-devices"),
}
BUS_MAP = {"net": "network", "tty": "serial", "gpio": "gpio", "platform": "platform",
           "i2c": "i2c", "spi": "spi", "mdio_bus": "mdio"}
def build_topology(session):
    manifest, entries = dossier.verify_session(session)
    nodes = {}
    edges = []
    gaps = []
    seen = set()
    for item, data in entries:
        key = (item.get("category"), item.get("name"))
        if key not in INPUTS:
            continue
        if item.get("status") != "ok":
            gaps.append({"probe": "/".join(key), "status": item.get("status", "unknown")})
            continue
        for lineno, row in enumerate(data.splitlines(), 1):
            if lineno > MAX_ROWS:
                gaps.append({"probe": "/".join(key), "status": "row_limit"})
                break
            parts = row.split("\t")
            if len(parts) != 4:
                gaps.append({"probe": "/".join(key), "line": lineno, "status": "malformed"})
                continue
            kind, name, driver, sysfs = parts
            if kind not in BUS_MAP or not SAFE.fullmatch(name) or not SAFE.fullmatch(sysfs) or (driver and not SAFE.fullmatch(driver)):
                gaps.append({"probe": "/".join(key), "line": lineno, "status": "invalid"})
                continue
            if not sysfs.startswith("/sys/") or ".." in Path(sysfs).parts:
                gaps.append({"probe": "/".join(key), "line": lineno, "status": "invalid_path"})
                continue
            device_id = "device:" + kind + ":" + name
            nodes[device_id] = {"id": device_id, "type": "device", "bus": BUS_MAP[kind],
                                "name": name, "sysfs": sysfs}
            if driver:
                driver_id = "driver:" + kind + ":" + driver
                nodes[driver_id] = {"id": driver_id, "type": "driver", "bus": BUS_MAP[kind], "name": driver}
                edge_id = (device_id, driver_id)
                if edge_id not in seen:
                    edges.append({"from": device_id, "to": driver_id, "relation": "bound_to",
                                  "confidence": "observed_sysfs", "source": item["file"], "line": lineno})
                    seen.add(edge_id)
            else:
                gaps.append({"probe": "/".join(key), "line": lineno,
                             "status": "driver_not_observed", "device": device_id})
    for key in sorted(INPUTS):
        if not any((it.get("category"), it.get("name")) == key for it, _ in entries):
            gaps.append({"probe": "/".join(key), "status": "not_collected"})
    return {
        "schema_version": 1, "type": "ubuntu-customizer/hardware-topology",
        "session": str(Path(session).resolve()), "target_label": manifest.get("target"),
        "nodes": sorted(nodes.values(), key=lambda x: x["id"]),
        "edges": edges, "gaps": gaps,
        "scope": "Linux sysfs driver binding evidence only; no physical pin map, voltage, register addresses, or verified PHY relationship."
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session")
    parser.add_argument("--output", help="new output path (default: session/topology.json)")
    args = parser.parse_args(argv)
    try:
        result = build_topology(args.session)
        path = Path(args.output) if args.output else Path(args.session) / "topology.json"
        if path.exists() or path.is_symlink():
            raise ValueError("Refusing to overwrite topology file")
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        path.chmod(0o600)
        print(f"Topology: {path} | nodes={len(result['nodes'])} edges={len(result['edges'])} gaps={len(result['gaps'])}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
