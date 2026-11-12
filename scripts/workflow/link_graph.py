#!/usr/bin/env python3
"""Link verified runtime sysfs bindings to DTS nodes through observed of_node paths."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

def load(name):
    spec = importlib.util.spec_from_file_location("uc_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

dossier = load("dossier")
topology = load("topology")
device_tree = load("device_tree")

PREFIXES = ("/sys/firmware/devicetree/base", "/proc/device-tree")

def normalized_of_path(path):
    for prefix in PREFIXES:
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            suffix = path[len(prefix):]
            if ".." not in Path(suffix).parts:
                return suffix
    return None

def build(session):
    manifest, entries = dossier.verify_session(session)
    runtime = topology.build_topology(session)
    dt = device_tree.build(session)
    nodes = {n["id"]: n for n in runtime["nodes"]}
    dt_ids = {n["id"] for n in dt["nodes"]}
    for n in dt["nodes"]:
        nodes["dt:" + n["id"]] = {"id": "dt:" + n["id"], "type": "device-tree-node",
                                  "name": n["name"], "properties": n["properties"]}
    edges = list(runtime["edges"])
    edges.extend({**edge, "from": "dt:" + edge["from"], "to": "dt:" + edge["to"]}
                 for edge in dt["edges"])
    gaps = list(runtime["gaps"]) + list(dt["gaps"])
    probes = [(i, s) for i, s in entries if i.get("category") == "drivers" and i.get("name") == "of-node-bindings"]
    if not probes:
        gaps.append({"kind": "not_collected", "probe": "drivers/of-node-bindings"})
    else:
        item, raw = probes[0]
        if item.get("status") != "ok":
            gaps.append({"kind": "probe_unavailable", "probe": "drivers/of-node-bindings", "status": item.get("status")})
        else:
            for lineno, line in enumerate(raw.splitlines()[:5000], 1):
                fields = line.split("\t")
                if len(fields) != 3 or fields[0] != "platform":
                    gaps.append({"kind": "invalid_of_node_record", "line": lineno})
                    continue
                _, name, path = fields
                if not name or "/" in name or ".." in name:
                    gaps.append({"kind": "invalid_of_node_device", "line": lineno})
                    continue
                dev_id = "device:platform:" + name
                dt_path = normalized_of_path(path)
                if dev_id in nodes and dt_path in dt_ids:
                    edges.append({"from": dev_id, "to": "dt:" + dt_path,
                                  "relation": "described_by", "confidence": "observed_sysfs_of_node",
                                  "source": item["file"], "line": lineno})
                else:
                    gaps.append({"kind": "unresolved_of_node", "line": lineno,
                                 "device": dev_id, "dt_path": dt_path})
    return {
        "schema_version": 1, "type": "ubuntu-customizer/linked-hardware-graph",
        "session": str(Path(session).resolve()), "target_label": manifest.get("target"),
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": edges, "gaps": gaps,
        "limitations": "Describes kernel binding and DTS references only; no physical wiring, voltage or verified electrical pin states."
    }

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session")
    p.add_argument("--output")
    args = p.parse_args(argv)
    try:
        result = build(args.session)
        output = workspace.checked_output(args.output or (Path(args.session) / "linked-hardware.json"))
        if output.exists() or output.is_symlink():
            raise ValueError("Refusing to overwrite")
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        output.chmod(0o600)
        print(f"Linked graph: {output}; nodes={len(result['nodes'])}, edges={len(result['edges'])}, gaps={len(result['gaps'])}")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

ws_spec = importlib.util.spec_from_file_location(
    "uc_workspace_link_graph", Path(__file__).with_name("project_workspace.py"))
workspace = importlib.util.module_from_spec(ws_spec)
ws_spec.loader.exec_module(workspace)

if __name__ == "__main__":
    raise SystemExit(main())
