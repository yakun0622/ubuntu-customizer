#!/usr/bin/env python3
"""Read-only comparison between a validated v0.1 JSON profile and a local Linux host.

Produces a plan; NEVER applies changes. No sudo, shell or network calls.
"""
import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("profile_validator", BASE / "safety" / "validate_profile.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

def command(args):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None

def os_release():
    data = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                data[k] = v.strip().strip('"')
    except OSError:
        pass
    return data

def installed(package):
    if not shutil.which("dpkg-query"):
        return None
    return command(["dpkg-query", "-W", "-f=${Status}", package]) == "install ok installed"

def collect(profile):
    osinfo = os_release()
    target = profile["target"]
    detected_arch = command(["dpkg", "--print-architecture"]) or platform.machine()
    distro = osinfo.get("ID", "")
    version = osinfo.get("VERSION_ID", "")
    compatibility = {
        "distribution": distro == target["distribution"],
        "architecture": detected_arch == target["architecture"],
        "version": not target.get("version") or target["version"] == version,
    }
    # Armbian often reports ID=debian or ubuntu; require explicit review instead.
    if target["distribution"] == "armbian":
        compatibility["distribution"] = False
    actions = []
    for package in profile.get("packages", {}).get("install", []):
        current = installed(package)
        actions.append({"kind": "package_install", "target": package, "state": "satisfied" if current is True else "unknown" if current is None else "pending", "risk": "R2"})
    for package in profile.get("packages", {}).get("remove", []):
        current = installed(package)
        actions.append({"kind": "package_remove", "target": package, "state": "pending" if current is True else "unknown" if current is None else "satisfied", "risk": "R2"})
    hostname = profile.get("system", {}).get("hostname")
    if hostname:
        current = socket.gethostname()
        actions.append({"kind": "set_hostname", "target": hostname, "current": current, "state": "satisfied" if hostname == current else "pending", "risk": "R2"})
    timezone = profile.get("system", {}).get("timezone")
    if timezone:
        try:
            current_tz = str(Path("/etc/localtime").resolve()).removeprefix("/usr/share/zoneinfo/")
        except OSError:
            current_tz = None
        actions.append({"kind": "set_timezone", "target": timezone, "current": current_tz, "state": "satisfied" if timezone == current_tz else "unknown" if current_tz is None else "pending", "risk": "R2"})
    return {
        "schema_version": 1,
        "mode": "dry-run",
        "system": {"distribution": distro, "version": version, "architecture": detected_arch, "kernel": platform.release()},
        "compatibility": compatibility,
        "blocked": not all(compatibility.values()),
        "actions": actions,
        "notice": "Read-only plan. No changes were applied. Unknown state requires manual inspection."
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="validated JSON SystemProfile")
    args = parser.parse_args()
    try:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        parser.error(str(e))
    errors = validator.validate(profile)
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 2
    plan = collect(profile)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 3 if plan["blocked"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
