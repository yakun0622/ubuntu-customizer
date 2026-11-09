#!/usr/bin/env python3
"""Fail-closed validation for the v0.1 JSON SystemProfile subset.
Requires only Python's standard library. This is not a general JSON Schema engine.
"""
import json
import re
import sys
from pathlib import Path

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.-]*$")


def validate(data):
    errors = []

    def obj(key, value, allowed, required=()):
        if not isinstance(value, dict):
            errors.append(f"{key}: must be an object")
            return {}
        for item in value:
            if item not in allowed:
                errors.append(f"{key}.{item}: unsupported field")
        for item in required:
            if item not in value:
                errors.append(f"{key}.{item}: required")
        return value

    root = obj("root", data, {"apiVersion", "kind", "metadata", "target", "image", "system", "packages", "execution"}, {"apiVersion", "kind", "metadata", "target", "execution"})
    if root.get("apiVersion") != "ubuntu-customizer/v1":
        errors.append("apiVersion: unsupported version")
    if root.get("kind") != "SystemProfile":
        errors.append("kind: must be SystemProfile")
    md = obj("metadata", root.get("metadata"), {"name"}, {"name"})
    if not isinstance(md.get("name"), str) or not NAME.fullmatch(md["name"]):
        errors.append("metadata.name: invalid")
    target = obj("target", root.get("target"), {"distribution", "version", "architecture", "board"}, {"distribution", "architecture"})
    if target.get("distribution") not in ("ubuntu", "debian", "armbian"):
        errors.append("target.distribution: unsupported")
    if target.get("architecture") not in ("amd64", "arm64", "armhf"):
        errors.append("target.architecture: unsupported")
    for key in ("version", "board"):
        if key in target and not isinstance(target[key], str):
            errors.append(f"target.{key}: must be string")
    if "image" in root:
        img = obj("image", root["image"], {"enabled", "format"})
        if "enabled" in img and not isinstance(img["enabled"], bool):
            errors.append("image.enabled: must be boolean")
        if "format" in img and img["format"] not in ("iso", "img", "qcow2"):
            errors.append("image.format: unsupported")
    if "system" in root:
        system = obj("system", root["system"], {"hostname", "timezone"})
        if "hostname" in system and (not isinstance(system["hostname"], str) or not HOST.fullmatch(system["hostname"])):
            errors.append("system.hostname: invalid")
        if "timezone" in system and not isinstance(system["timezone"], str):
            errors.append("system.timezone: must be string")
    if "packages" in root:
        packages = obj("packages", root["packages"], {"install", "remove"})
        for action in ("install", "remove"):
            if action not in packages:
                continue
            values = packages[action]
            if not isinstance(values, list) or any(not isinstance(v, str) or not PACKAGE.fullmatch(v) for v in values) or len(values) != len(set(values)):
                errors.append(f"packages.{action}: invalid or duplicate package")
    exe = obj("execution", root.get("execution"), {"dry_run", "backup", "verify", "reboot"}, {"dry_run", "reboot"})
    if exe.get("dry_run") is not True:
        errors.append("execution.dry_run: must be true in v0.1")
    if exe.get("reboot") != "manual":
        errors.append("execution.reboot: must be manual in v0.1")
    for flag in ("backup", "verify"):
        if flag in exe and not isinstance(exe[flag], bool):
            errors.append(f"execution.{flag}: must be boolean")
    return errors


def main():
    if len(sys.argv) != 2:
        print("Usage: validate_profile.py PROFILE.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print("VALID (v0.1 safe subset; no actions executed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
