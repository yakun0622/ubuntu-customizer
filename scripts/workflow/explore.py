#!/usr/bin/env python3
"""Evidence-backed hardware explorer and non-executing task planner.

Reads a verified collection session through existing parsers. Never contacts a
device, applies configurations, builds an image or executes arbitrary commands.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent

def module(name):
    spec = importlib.util.spec_from_file_location("uc_explore_" + name, HERE / (name + ".py"))
    imported = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imported)
    return imported

dossier = module("dossier")
link_graph = module("link_graph")

TASKS = {
    "diagnose": {"risk": "R0", "purpose": "Investigate evidence gaps and target behavior", "stage": "analysis_only"},
    "maintain": {"risk": "R2", "purpose": "Plan installed-system changes", "stage": "plan_only"},
    "image": {"risk": "R4", "purpose": "Plan an image suitable for verified target constraints", "stage": "plan_only"},
}
MAX_NODES = 6000

def load_session(session):
    session = Path(session).resolve()
    # Forces SHA-256 evidence verification and path checks, even for cached output.
    manifest, entries = dossier.verify_session(session)
    graph = link_graph.build(session)
    if len(graph["nodes"]) > MAX_NODES:
        raise ValueError("Too many nodes for terminal browser")
    if graph["type"] != "ubuntu-customizer/linked-hardware-graph":
        raise ValueError("Unexpected graph type")
    return session, manifest, entries, graph

def tree_data(graph, category=None):
    nodes = graph["nodes"]
    if category:
        valid = {"device", "driver", "device-tree-node"}
        if category not in valid:
            raise ValueError("Invalid node type")
        nodes = [n for n in nodes if n.get("type") == category]
    return [{"id": n["id"], "type": n["type"],
             "name": n.get("name"), "bus": n.get("bus")} for n in nodes]

def detail(graph, node_id):
    nodes = {n["id"]: n for n in graph["nodes"]}
    if node_id not in nodes:
        raise ValueError("Node does not exist in verified session")
    edges = [e for e in graph["edges"] if e.get("from") == node_id or e.get("to") == node_id]
    return {"node": nodes[node_id], "relationships": edges,
            "scope": graph.get("limitations"),
            "warnings": ["Software binding and DTS evidence do not prove physical wiring or function."]}

def build_plan(session, manifest, graph, task, node_id=None, goal=None):
    if task not in TASKS:
        raise ValueError("Unknown task")
    if node_id and node_id not in {n["id"] for n in graph["nodes"]}:
        raise ValueError("Selected node absent from verified collection evidence")
    if goal is not None and (not isinstance(goal, str) or len(goal) > 500):
        raise ValueError("Goal must be 500 characters or fewer")
    issues = list(graph.get("gaps", []))[:100]
    session_state = manifest.get("state", "legacy")
    blockers = []
    if session_state not in ("complete", "legacy"):
        blockers.append("Session incomplete; gather missing evidence and verify identity")
    if task == "image":
        blockers.append("Boot chain, storage layout, OS variant, source image integrity and target compatibility require independent validation")
    if task == "maintain":
        blockers.append("No approved apply/rollback executor is implemented; capture current configuration and backups before any mutation")
    if node_id and node_id.startswith("dt:"):
        blockers.append("Device-tree description is software evidence, not proof of connected hardware")
    return {
        "schema_version": 1,
        "type": "ubuntu-customizer/task-plan",
        "execution": "disabled",
        "task": task,
        "goal": goal or TASKS[task]["purpose"],
        "risk": TASKS[task]["risk"],
        "target_session": str(session),
        "transport": manifest.get("transport"),
        "target_label": manifest.get("target"),
        "selected_node": node_id,
        "evidence": [{"source": e.get("source"), "relation": e.get("relation")}
                     for e in graph["edges"]
                     if node_id and (e.get("from") == node_id or e.get("to") == node_id)][:100],
        "missing_evidence": issues,
        "blockers": blockers,
        "next_steps": [
            "Review evidence integrity, collection completeness and device identity",
            "Confirm desired behavior and collect task-specific evidence without modifying the device",
            "Produce a change/build proposal with exact files, commands, validation and recovery steps",
            "Request separate explicit authorization before any mutating action",
        ],
        "notice": "Planning artifact only: no changes, image builds, flashing, reboots or network access performed."
    }

def print_tree(graph, category=None):
    for item in tree_data(graph, category):
        print(f"[{item['type']}] {item['id']}")
    print(f"Nodes: {len(tree_data(graph, category))}; edges: {len(graph['edges'])}; gaps: {len(graph['gaps'])}")

def write_plan(path, plan):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError("Refusing to overwrite plan")
    with path.open("x", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
        f.write("\n")
    path.chmod(0o600)
    return path

def wizard(session, manifest, graph):
    print_tree(graph)
    print("Task types: diagnose / maintain / image")
    target = input("Select exact node ID (blank for whole device): ").strip() or None
    if target and target not in {n["id"] for n in graph["nodes"]}:
        raise ValueError("Unknown node ID")
    task = input("Task type: ").strip()
    goal = input("What would you like to achieve? ").strip()
    plan = build_plan(session, manifest, graph, task, target, goal)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return plan

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", help="directory containing verified discovery manifest.json")
    parser.add_argument("--mode", choices=("tree", "node", "plan", "wizard"), default="wizard")
    parser.add_argument("--type", choices=("device", "driver", "device-tree-node"))
    parser.add_argument("--node")
    parser.add_argument("--task", choices=tuple(TASKS))
    parser.add_argument("--goal")
    parser.add_argument("--output", help="new plan JSON path, only valid in plan or wizard mode")
    args = parser.parse_args(argv)
    try:
        session, manifest, _, graph = load_session(args.session)
        if args.mode == "tree":
            print_tree(graph, args.type)
        elif args.mode == "node":
            if not args.node:
                raise ValueError("--node required for node details")
            print(json.dumps(detail(graph, args.node), indent=2, ensure_ascii=False))
        else:
            if args.mode == "plan":
                if not args.task:
                    raise ValueError("--task required for plan mode")
                plan = build_plan(session, manifest, graph, args.task, args.node, args.goal)
                print(json.dumps(plan, indent=2, ensure_ascii=False))
            else:
                plan = wizard(session, manifest, graph)
            if args.output:
                print("Saved plan:", write_plan(str(workspace.checked_output(args.output)), plan))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

# The CLI enforces the project's outputs-only policy. Internal library functions
# continue to accept isolated temporary test fixtures without changing their API.
ws_spec = importlib.util.spec_from_file_location(
    "uc_workspace_explore", Path(__file__).with_name("project_workspace.py"))
workspace = importlib.util.module_from_spec(ws_spec)
ws_spec.loader.exec_module(workspace)

if __name__ == "__main__":
    raise SystemExit(main())
