#!/usr/bin/env python3
"""Local device catalog, safe connection discovery and interactive workflow.

Discovery never connects. 'collect' uses the approved read-only adaptive
collector and stores evidence under a per-device private directory.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("uc_adaptive", HERE / "adaptive.py")
adaptive = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adaptive)

_explore_spec = importlib.util.spec_from_file_location("uc_explore", HERE / "explore.py")
explore = importlib.util.module_from_spec(_explore_spec)
_explore_spec.loader.exec_module(explore)

_html_spec = importlib.util.spec_from_file_location("uc_export_html", HERE / "export_html.py")
export_html = importlib.util.module_from_spec(_html_spec)
_html_spec.loader.exec_module(export_html)

_image_spec = importlib.util.spec_from_file_location("uc_image_plan", HERE / "image_plan.py")
image_plan = importlib.util.module_from_spec(_image_spec)
_image_spec.loader.exec_module(image_plan)


ID = re.compile(r"^[a-z][a-z0-9-]{1,47}$")
TRANSPORTS = ("ssh", "adb", "ttl", "local")
SERIAL_PORT = re.compile(r"^/dev/[A-Za-z0-9_.-]+$")
DEFAULT_HOME = Path.home() / ".local" / "share" / "ubuntu-customizer"

def check_target(transport, target):
    if transport not in TRANSPORTS:
        raise ValueError("Unknown connection transport")
    if transport == "local":
        return "local"
    if not target:
        raise ValueError("Connection target is required")
    if transport == "ssh" and (not adaptive.collect.HOST.fullmatch(target) or target.startswith("-")):
        raise ValueError("SSH requires a named Host alias")
    if transport == "adb" and (not adaptive.collect.SERIAL.fullmatch(target) or target.startswith("-")):
        raise ValueError("Invalid ADB device serial")
    if transport == "ttl" and (not SERIAL_PORT.fullmatch(target) or ".." in target):
        raise ValueError("Invalid /dev serial path")
    return target

def _private_dir(path):
    path = Path(path).expanduser()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Unsafe data directory")
    if path.stat().st_mode & 0o077:
        raise ValueError("Data directory must not be group/world-accessible")
    return path.resolve()

def load_catalog(root):
    path = root / "registry.json"
    if not path.exists():
        return {"schema_version": 1, "devices": {}}
    if path.is_symlink():
        raise ValueError("Refusing registry symlink")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("devices"), dict):
        raise ValueError("Unsupported registry schema")
    return data

def save_catalog(root, data):
    file = root / "registry.json"
    temp = root / ("registry-" + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        temp.chmod(0o600)
        os.replace(temp, file)
    finally:
        if temp.exists():
            temp.unlink()

def register(root, name, transport, target):
    if not ID.fullmatch(name):
        raise ValueError("Device ID must be 2–48 lower-case letters, digits or hyphens; start with a letter")
    target = check_target(transport, target)
    data = load_catalog(root)
    if name in data["devices"]:
        raise ValueError("Device already registered; remove or use a different ID")
    data["devices"][name] = {
        "id": name, "transport": transport, "target": target,
        "added_at": datetime.now(timezone.utc).isoformat()
    }
    save_catalog(root, data)
    return data["devices"][name]

def ssh_aliases(config):
    # Enumerates explicit Host aliases only; does not resolve Include files or patterns.
    if not config.is_file() or config.is_symlink():
        return []
    result = []
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.strip().split()
        if not parts or parts[0].lower() != "host":
            continue
        for alias in parts[1:]:
            if (adaptive.collect.HOST.fullmatch(alias) and not alias.startswith("-")
                    and not any(x in alias for x in "*?!") and alias not in result):
                result.append(alias)
    return result

def adb_targets():
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True,
                                timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    out = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            try:
                out.append(check_target("adb", parts[0]))
            except ValueError:
                pass
    return out

def serial_ports():
    dev = Path("/dev")
    if not dev.is_dir():
        return []
    prefixes = ("ttyUSB", "ttyACM", "ttyS", "ttyAMA", "cu.usb", "tty.usb", "cu.wch", "tty.wch")
    return sorted(str(p) for p in dev.iterdir() if p.name.startswith(prefixes)
                  and SERIAL_PORT.fullmatch(str(p)))

def discover(config=None):
    config = config or Path.home() / ".ssh" / "config"
    return {"ssh": ssh_aliases(config), "adb": adb_targets(),
            "ttl": serial_ports(), "local": ["local"],
            "note": "Candidates only. No connection attempted or trust established."}

def sessions(root, name):
    if not ID.fullmatch(name):
        raise ValueError("Invalid device ID")
    parent = root / "devices" / name / "sessions"
    if not parent.is_dir():
        return []
    found = []
    for folder in sorted(parent.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        manifest = folder / "manifest.json"
        if not manifest.is_file() or manifest.is_symlink():
            continue
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            continue
        found.append({"session": folder.name, "state": data.get("state", "legacy"),
                      "collected": len(data.get("items", [])),
                      "skipped": len(data.get("skipped", []))})
    return found

def inspect_session(root, name, session_id):
    if not ID.fullmatch(name) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", session_id):
        raise ValueError("Invalid device or session ID")
    folder = root / "devices" / name / "sessions" / session_id
    manifest = folder / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("Session manifest not found")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if not isinstance(items, list):
        raise ValueError("Invalid session manifest")
    categories = {}
    for item in items:
        category = item.get("category", "unknown")
        categories.setdefault(category, {"collected": 0, "failed": 0})
        categories[category]["collected"] += 1
        if item.get("status") not in ("ok",):
            categories[category]["failed"] += 1
    return {"device_id": name, "session": session_id,
            "state": data.get("state", "legacy"), "categories": categories,
            "skipped": data.get("skipped", []),
            "artifacts": [name for name in ("device.json", "capabilities.json",
                            "topology.json", "device-tree.json", "linked-hardware.json")
                          if (folder / name).is_file() and not (folder / name).is_symlink()]}

def session_path(root, name, session_id):
    if not ID.fullmatch(name) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", session_id):
        raise ValueError("Invalid device/session ID")
    if name not in load_catalog(root)["devices"]:
        raise ValueError("Device not registered")
    parent = (root / "devices" / name / "sessions").resolve()
    candidate = parent / session_id
    if candidate.is_symlink() or not candidate.is_dir() or candidate.resolve().parent != parent:
        raise ValueError("Invalid or missing session directory")
    return candidate

def explore_session(root, name, session_id, task=None, node=None, goal=None):
    folder = session_path(root, name, session_id)
    session, manifest, _, graph = explore.load_session(folder)
    if task:
        return explore.build_plan(session, manifest, graph, task, node, goal)
    if node:
        return explore.detail(graph, node)
    return {"device": name, "session": session_id, "nodes": explore.tree_data(graph),
            "edges": len(graph["edges"]), "gaps": len(graph["gaps"])}

def collect_device(root, name, modules, timeout=12, baud=115200, duration=10):
    catalog = load_catalog(root)
    if name not in catalog["devices"]:
        raise ValueError("Device is not registered")
    device = catalog["devices"][name]
    parent = _private_dir(root / "devices" / name / "sessions")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = parent / (stamp + "-" + uuid.uuid4().hex[:8])
    return adaptive.run(device["transport"], device["target"], str(output),
                        timeout, modules, baud, duration)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default=str(DEFAULT_HOME))
    sub = p.add_subparsers(dest="command")
    sub.add_parser("discover")
    sub.add_parser("list")
    add = sub.add_parser("add")
    add.add_argument("id")
    add.add_argument("--transport", choices=TRANSPORTS, required=True)
    add.add_argument("--target", required=True)
    history = sub.add_parser("sessions")
    history.add_argument("id")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("id")
    inspect.add_argument("session")
    browse = sub.add_parser("explore")
    browse.add_argument("id")
    browse.add_argument("session")
    browse.add_argument("--node")
    browse.add_argument("--task", choices=tuple(explore.TASKS))
    browse.add_argument("--goal")
    browser = sub.add_parser("browse")
    browser.add_argument("id")
    browser.add_argument("session")
    browser.add_argument("--output", help="new offline .html file path")
    image = sub.add_parser("image-plan")
    image.add_argument("id")
    image.add_argument("session")
    image.add_argument("--target", choices=("virtual-machine", "physical-device"), required=True)
    image.add_argument("--format", choices=("qcow2", "raw"), required=True)
    image.add_argument("--source", required=True)
    image.add_argument("--sha256", required=True)
    image.add_argument("--source-arch", choices=("amd64", "arm64", "armhf", "riscv64"), required=True)
    image.add_argument("--output", required=True, help="new image compatibility JSON plan")
    run = sub.add_parser("collect")
    run.add_argument("id")
    run.add_argument("--modules", default="auto")
    run.add_argument("--yes", action="store_true",
                     help="Authorize only read-only collection")
    args = p.parse_args(argv)
    try:
        root = _private_dir(args.data_dir)
        action = args.command
        if action is None:
            print("1. Discover connections  2. List devices  3. Add device  4. Collect  5. Sessions  6. Inspect  7. Explore  8. Browse HTML")
            index = input("Select [1-8]: ").strip()
            action = {"1": "discover", "2": "list", "3": "add", "4": "collect", "5": "sessions", "6": "inspect", "7": "explore", "8": "browse"}.get(index)
            if not action:
                raise ValueError("Invalid choice")
        if action == "discover":
            output = discover()
        elif action == "list":
            output = load_catalog(root)["devices"]
        elif action == "add":
            name = getattr(args, "id", None) or input("Device ID: ").strip()
            transport = getattr(args, "transport", None) or input("Transport [ssh/adb/ttl/local]: ").strip()
            target = getattr(args, "target", None) or input("Target alias/serial (local for local): ").strip()
            output = register(root, name, transport, target)
        elif action == "sessions":
            name = getattr(args, "id", None) or input("Device ID: ").strip()
            output = sessions(root, name)
        elif action == "inspect":
            name = getattr(args, "id", None) or input("Device ID: ").strip()
            session = getattr(args, "session", None) or input("Session ID: ").strip()
            output = inspect_session(root, name, session)
        elif action == "image-plan":
            folder = session_path(root, args.id, args.session)
            output = Path(args.output)
            if output.exists() or output.is_symlink():
                raise ValueError("Image plan output exists")
            result = image_plan.plan(folder, args.target, args.format, args.source, args.sha256, args.source_arch)
            with output.open("x", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
                f.write("\n")
            output.chmod(0o600)
            output = {"plan": str(output), "build_allowed": result["build_allowed"],
                      "blockers": result["blockers"], "warnings": result["warnings"]}
        elif action == "browse":
            name = getattr(args, "id", None) or input("Device ID: ").strip()
            session_id = getattr(args, "session", None) or input("Session ID: ").strip()
            folder = session_path(root, name, session_id)
            output_file = getattr(args, "output", None)
            if not output_file:
                output_file = str(folder / "hardware-explorer.html")
            output = {"html": str(export_html.export(folder, output_file)),
                      "note": "Open locally in a browser; no web server or remote connection."}
        elif action == "explore":
            name = getattr(args, "id", None) or input("Device ID: ").strip()
            session_id = getattr(args, "session", None) or input("Session ID: ").strip()
            task = getattr(args, "task", None)
            node = getattr(args, "node", None)
            goal = getattr(args, "goal", None)
            if args.command is None:
                folder = session_path(root, name, session_id)
                session, manifest, _, graph = explore.load_session(folder)
                output = explore.wizard(session, manifest, graph)
            else:
                output = explore_session(root, name, session_id, task, node, goal)
        else:
            name = getattr(args, "id", None) or input("Device ID: ").strip()
            value = getattr(args, "modules", "auto")
            modules = list(adaptive.MODULES) if value == "auto" else [x.strip() for x in value.split(",")]
            if not modules or any(x not in adaptive.MODULES for x in modules):
                raise ValueError("Unknown collection module")
            if not getattr(args, "yes", False):
                print("Read-only collection; may store IPs, MACs and hardware IDs locally.")
                if input("Proceed? [y/N]: ").strip().lower() not in ("y", "yes"):
                    return 1
            path, manifest = collect_device(root, name, modules)
            output = {"session_dir": str(path), "state": manifest["state"],
                      "collected": len(manifest["items"]), "skipped": len(manifest["skipped"])}
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
