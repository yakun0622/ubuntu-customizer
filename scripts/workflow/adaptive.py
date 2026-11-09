#!/usr/bin/env python3
"""Capability-aware, read-only staged device discovery.

Bootstrap -> feature detection -> selected modules -> checkpointed evidence.
No arbitrary remote command, sudo, flashing or system modification.
TTL is passive capture only; it cannot perform feature negotiation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("uc_collect", HERE / "collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)

PROBES = {(category, name): command for category, name, command in collect.PROBES}
BOOTSTRAP = [
    ("identity", "os"), ("identity", "kernel"),
    ("identity", "cpu"), ("identity", "memory"),
]
# Only fixed, read-only tests; results describe access, not absence of hardware.
FEATURE_COMMAND = (
    "for entry in "
    "'devicetree:/proc/device-tree' "
    "'sysfs:/sys/class' "
    "'buses:/sys/bus' "
    "'pinctrl:/sys/kernel/debug/pinctrl' "
    "'boot:/boot'; do "
    "key=${entry%%:*}; path=${entry#*:}; "
    "if test -d \"$path\"; then printf '%s=1\\n' \"$key\"; "
    "else printf '%s=0\\n' \"$key\"; fi; done; "
    "for tool in dtc gpioinfo ip lsblk; do "
    "if command -v \"$tool\" >/dev/null 2>&1; then "
    "printf '%s=1\\n' \"$tool\"; else printf '%s=0\\n' \"$tool\"; fi; done"
)
MODULES = {
    "hardware": [("hardware", "device-tree-model"),
                 ("hardware", "device-tree-compatible"),
                 ("hardware", "usb"), ("hardware", "pci")],
    "drivers": [("drivers", "modules"), ("drivers", "tty"),
                ("drivers", "network-drivers"), ("drivers", "gpio-chips"),
                ("drivers", "sysfs-bindings"), ("drivers", "platform-bindings"),
                ("drivers", "of-node-bindings")],
    "buses": [("hardware", "bus-devices")],
    "pins": [("pins", "gpioinfo"), ("pins", "pinctrl"), ("pins", "dt-source")],
    "network": [("network", "ip-link"), ("network", "ip-route"),
                ("network", "phy")],
    "storage": [("storage", "blocks")],
    "boot": [("boot", "boot-files")],
}
REQUIREMENTS = {
    ("hardware", "device-tree-model"): ("devicetree",),
    ("hardware", "device-tree-compatible"): ("devicetree",),
    ("drivers", "sysfs-bindings"): ("sysfs",),
    ("drivers", "platform-bindings"): ("sysfs",),
    ("drivers", "of-node-bindings"): ("devicetree", "sysfs"),
    ("hardware", "bus-devices"): ("buses",),
    ("pins", "gpioinfo"): ("gpioinfo",),
    ("pins", "pinctrl"): ("pinctrl",),
    ("pins", "dt-source"): ("dtc", "devicetree"),
    ("network", "ip-link"): ("ip",),
    ("network", "ip-route"): ("ip",),
    ("storage", "blocks"): ("lsblk",),
    ("boot", "boot-files"): ("boot",),
}

def parse_features(output):
    features = {}
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in {"devicetree", "sysfs", "buses", "pinctrl", "boot",
                           "dtc", "gpioinfo", "ip", "lsblk"} and value in ("0", "1"):
            features[key] = value == "1"
    return features

def plan(modules, features):
    actions = []
    for module in modules:
        for category, name in MODULES[module]:
            requirements = REQUIREMENTS.get((category, name), ())
            missing = [key for key in requirements if features.get(key) is not True]
            actions.append({"module": module, "category": category, "name": name,
                            "status": "skipped" if missing else "pending",
                            "reason": "prerequisite_not_observed:" + ",".join(missing) if missing else None})
    return actions

def checkpoint(output, manifest):
    target = output / "manifest.json"
    tmp = output / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, target)

def record(output, manifest, category, name, status, payload, err, code, stage):
    folder = output / category
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / (name + ".txt")
    if path.exists():
        raise ValueError("Duplicate evidence file: " + str(path))
    with path.open("xb") as f:
        f.write(payload)
    path.chmod(0o600)
    manifest["items"].append({
        "category": category, "name": name, "stage": stage,
        "file": str(path.relative_to(output)),
        "status": status, "returncode": code, "error": err[:1000],
        "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()
    })
    checkpoint(output, manifest)

def collect_probe(transport, target, command, timeout):
    return collect.capture(collect.shell_invocation(transport, target, command), timeout)

def run(transport, target, output, timeout, modules, baud=115200, duration=10):
    folder = collect.safe_output_dir(output)
    manifest = {
        "schema_version": 1, "workflow_version": "adaptive-v1",
        "transport": transport, "target": target,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "state": "running", "read_only": True,
        "selected_modules": modules, "items": [], "skipped": [],
        "limitations": ["Probes can be denied or truncated; unknown is not absent.",
                        "Raw evidence can include device identifiers, IP and MAC information.",
                        "No target writes, privilege escalation or automatic upload."]
    }
    checkpoint(folder, manifest)
    try:
        if transport == "ttl":
            result = collect.collect_ttl(target, folder, baud, duration)
            manifest["items"] = result["items"]
            manifest["limitations"].extend(result["limitations"])
            manifest["state"] = "complete"
            manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
            checkpoint(folder, manifest)
            return folder, manifest
        for category, name in BOOTSTRAP:
            status, payload, err, code = collect_probe(transport, target, PROBES[(category, name)], timeout)
            record(folder, manifest, category, name, status, payload, err, code, "bootstrap")
        status, payload, err, code = collect_probe(transport, target, FEATURE_COMMAND, timeout)
        record(folder, manifest, "hardware", "feature-check", status, payload, err, code, "capability")
        features = parse_features(payload.decode("utf-8", "replace")) if status == "ok" else {}
        manifest["features"] = {key: ("observed" if value else "unavailable") for key, value in features.items()}
        checkpoint(folder, manifest)
        for action in plan(modules, features):
            if action["status"] == "skipped":
                manifest["skipped"].append(action)
                checkpoint(folder, manifest)
                continue
            category, name = action["category"], action["name"]
            status, payload, err, code = collect_probe(transport, target, PROBES[(category, name)], timeout)
            record(folder, manifest, category, name, status, payload, err, code, "detail")
        manifest["state"] = "complete"
    except Exception as exc:
        manifest["state"] = "incomplete"
        manifest["failure"] = str(exc)
        raise
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        checkpoint(folder, manifest)
    return folder, manifest

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("ssh", "adb", "local", "ttl"))
    parser.add_argument("--target")
    parser.add_argument("--output", help="New session directory; parent must exist")
    parser.add_argument("--modules", default="auto", help="auto or comma-separated: " + ",".join(MODULES))
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--yes", action="store_true", help="Explicit permission for unattended read-only collection")
    args = parser.parse_args(argv)
    transport = args.transport
    if not transport and not args.yes:
        transport = collect.choose("Choose connection method", ["ssh", "adb", "ttl", "local"])
    if transport is None:
        parser.error("--transport required with --yes")
    target = args.target or ("local" if transport == "local" else None)
    if not target and not args.yes:
        target = input("Target (SSH alias / ADB serial / /dev/tty path): ").strip()
    if transport == "ssh" and (not target or not collect.HOST.fullmatch(target) or target.startswith("-")):
        parser.error("SSH requires a safe configured Host alias")
    if transport == "adb" and (not target or not collect.SERIAL.fullmatch(target) or target.startswith("-")):
        parser.error("ADB requires a safe device serial")
    if transport == "ttl" and (not target or not target.startswith("/dev/") or ".." in target):
        parser.error("TTL requires a serial device path under /dev")
    if transport == "local" and target != "local":
        parser.error("Local target must be 'local'")
    if not 1 <= args.timeout <= 120 or not 1 <= args.duration <= 300 or not 1200 <= args.baud <= 3000000:
        parser.error("Invalid timeout, serial duration or baud")
    modules = list(MODULES) if args.modules == "auto" else [v.strip() for v in args.modules.split(",")]
    if not modules or len(set(modules)) != len(modules) or any(m not in MODULES for m in modules):
        parser.error("Unknown or repeated collection module")
    if transport == "ttl":
        modules = []  # Passive capture, no Linux shell available.
    output = args.output or ("./device-session-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if not args.yes:
        print("Read-only collection; no sudo and no remote changes. Evidence may contain private infrastructure data.")
        if input("Proceed? [y/N]: ").strip().lower() not in ("y", "yes"):
            print("Cancelled")
            return 1
    try:
        folder, manifest = run(transport, target, output, args.timeout, modules, args.baud, args.duration)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"session": str(folder), "state": manifest["state"],
                      "collected": len(manifest["items"]), "skipped": len(manifest["skipped"])},
                     ensure_ascii=False))
    return 0 if manifest["state"] == "complete" else 2

if __name__ == "__main__":
    raise SystemExit(main())
