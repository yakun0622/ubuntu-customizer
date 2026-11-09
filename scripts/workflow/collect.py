#!/usr/bin/env python3
"""Interactive, read-only discovery workflow for Linux/Android/serial devices.

SSH and ADB execute only hardcoded read-only probes. TTL is passive RX only.
Reports stay local and are never automatically uploaded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone

HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SERIAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_BYTES = 262144
# Commands are immutable trusted constants, never synthesized from user input.
PROBES = [
    ("identity", "os", "cat /etc/os-release"),
    ("identity", "kernel", "uname -a"),
    ("identity", "cpu", "cat /proc/cpuinfo"),
    ("identity", "memory", "cat /proc/meminfo"),
    ("hardware", "device-tree-model", "if test -r /proc/device-tree/model; then tr '\\000' '\\n' < /proc/device-tree/model; else echo unavailable; fi"),
    ("hardware", "device-tree-compatible", "if test -r /proc/device-tree/compatible; then tr '\\000' '\\n' < /proc/device-tree/compatible; else echo unavailable; fi"),
    ("hardware", "usb", "if command -v lsusb >/dev/null 2>&1; then lsusb; else echo unavailable; fi"),
    ("hardware", "pci", "if command -v lspci >/dev/null 2>&1; then lspci -nnk; else echo unavailable; fi"),
    # Tab-separated read-only sysfs mapping: class, logical device, driver, bus device.
    # This expresses Linux binding only, never physical board wiring.
    ("drivers", "sysfs-bindings", "for class in net tty gpio; do for node in /sys/class/$class/*; do test -e \"$node\" || continue; device=$(readlink -f \"$node/device\" 2>/dev/null) || device=; driver=$(readlink -f \"$node/device/driver\" 2>/dev/null) || driver=; printf '%s\\t%s\\t%s\\t%s\\n' \"$class\" \"${node##*/}\" \"${driver##*/}\" \"$device\"; done; done"),
    ("drivers", "platform-bindings", "for node in /sys/bus/platform/devices/*; do test -e \"$node\" || continue; driver=$(readlink -f \"$node/driver\" 2>/dev/null) || driver=; test -n \"$driver\" || continue; printf 'platform\\t%s\\t%s\\t%s\\n' \"${node##*/}\" \"${driver##*/}\" \"$(readlink -f \"$node\")\"; done"),
    ("hardware", "bus-devices", "for bus in i2c spi mdio_bus; do for node in /sys/bus/$bus/devices/*; do test -e \"$node\" || continue; driver=$(readlink -f \"$node/driver\" 2>/dev/null) || driver=; printf '%s\\t%s\\t%s\\t%s\\n' \"$bus\" \"${node##*/}\" \"${driver##*/}\" \"$(readlink -f \"$node\")\"; done; done"),
    ("drivers", "modules", "cat /proc/modules"),
    ("drivers", "tty", "ls -l /sys/class/tty/"),
    ("drivers", "network-drivers", "ls -l /sys/class/net/"),
    ("drivers", "gpio-chips", "ls -l /sys/class/gpio/"),
    ("pins", "pinctrl", "if test -d /sys/kernel/debug/pinctrl; then ls -l /sys/kernel/debug/pinctrl; else echo 'pinctrl debugfs unavailable or not mounted'; fi"),
    ("pins", "gpioinfo", "if command -v gpioinfo >/dev/null 2>&1; then gpioinfo; else echo unavailable; fi"),
    ("pins", "dt-source", "if command -v dtc >/dev/null 2>&1 && test -d /proc/device-tree; then dtc -I fs -O dts /proc/device-tree 2>/dev/null; else echo 'dtc or device tree unavailable'; fi"),
    ("network", "ip-link", "if command -v ip >/dev/null 2>&1; then ip -s link; else echo unavailable; fi"),
    ("network", "ip-route", "if command -v ip >/dev/null 2>&1; then ip route; else echo unavailable; fi"),
    ("network", "phy", "if command -v ethtool >/dev/null 2>&1; then ethtool --version; else echo unavailable; fi"),
    ("storage", "blocks", "if command -v lsblk >/dev/null 2>&1; then lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS; else echo unavailable; fi"),
    ("boot", "boot-files", "if test -d /boot; then ls -la /boot; else echo unavailable; fi"),
]
# No kernel cmdline, environment, secrets, journal or unrestricted file traversal.
# Output is still sensitive (MAC, hostnames, topology); review before sharing.

def shell_invocation(transport, target, command):
    remote = "sh -c " + shlex.quote(command)
    if transport == "ssh":
        return ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "ConnectTimeout=8", "-o", "NumberOfPasswordPrompts=0",
                target, remote]
    if transport == "adb":
        return ["adb", "-s", target, "shell", remote]
    if transport == "local":
        return ["sh", "-c", command]
    raise ValueError("Unsupported shell transport")

def capture(argv, timeout):
    try:
        r = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        data = r.stdout[:MAX_BYTES]
        error = r.stderr[:8192].decode("utf-8", errors="replace")
        status = "ok" if r.returncode == 0 else "error"
        if status == "ok" and (data.strip() == b"unavailable" or data.strip().endswith(b"unavailable")):
            status = "unavailable"
        if len(r.stdout) > MAX_BYTES:
            status = "truncated" if status == "ok" else status
        return status, data, error, r.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "error", b"", str(exc), None

def safe_output_dir(base):
    # A newly created directory; avoid reusing another device's evidence.
    base = Path(base).expanduser()
    if base.exists() or base.is_symlink():
        raise ValueError("Output directory already exists; use a new directory")
    parent = base.parent.resolve()
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("Output parent must be an existing directory")
    base = parent / base.name
    base.mkdir(mode=0o700)
    return base

def collect_shell(transport, target, output, timeout):
    manifest = {"schema_version": 1, "transport": transport,
                "target": target, "collected_at": datetime.now(timezone.utc).isoformat(),
                "read_only": True, "items": [], "limitations": [
                    "Pinmux/device-tree does not prove physical PCB pinout",
                    "Unprivileged probes may omit hardware details",
                    "Evidence may contain IPs, MAC addresses and device identifiers",
                    "No files are automatically uploaded"]}
    for category, name, command in PROBES:
        status, payload, err, code = capture(shell_invocation(transport, target, command), timeout)
        folder = output / category
        folder.mkdir(mode=0o700, exist_ok=True)
        path = folder / (name + ".txt")
        path.write_bytes(payload)
        path.chmod(0o600)
        manifest["items"].append({"category": category, "name": name,
            "file": str(path.relative_to(output)), "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload), "status": status, "returncode": code, "error": err[:1000]})
        print(f"  {category}/{name}: {status} ({len(payload)} bytes)", flush=True)
    return manifest

def collect_ttl(target, output, baud, duration):
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("TTL capture requires pyserial: python3 -m pip install pyserial") from exc
    folder = output / "serial"
    folder.mkdir(mode=0o700)
    path = folder / "receive.log"
    payload = bytearray()
    start = time.monotonic()
    # No writes to serial, no RTS/DTR toggling requested.
    with serial.Serial(port=target, baudrate=baud, timeout=0.2, rtscts=False,
                       dsrdtr=False) as conn:
        while time.monotonic() - start < duration and len(payload) < MAX_BYTES:
            payload.extend(conn.read(min(4096, MAX_BYTES - len(payload))))
    path.write_bytes(payload)
    path.chmod(0o600)
    return {"schema_version": 1, "transport": "ttl", "target": target,
            "collected_at": datetime.now(timezone.utc).isoformat(), "read_only": True,
            "items": [{"category": "serial", "name": "receive", "file": "serial/receive.log",
                       "sha256": hashlib.sha256(payload).hexdigest(),
                       "bytes": len(payload), "status": "ok" if payload else "empty"}],
            "limitations": ["Passive serial RX only; no shell commands run",
                            "Serial output alone does not identify physical pinout",
                            "Opening a serial port can affect modem control lines on some adapters",
                            "No files are automatically uploaded"]}

def choose(prompt, options):
    print(prompt)
    for number, label in enumerate(options, 1):
        print(f"  {number}. {label}")
    while True:
        answer = input("Select number: ").strip()
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=["ssh", "adb", "ttl", "local"])
    parser.add_argument("--target", help="SSH alias, ADB serial or local serial-port path")
    parser.add_argument("--output", help="New local evidence directory")
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--duration", type=int, default=10)
    args = parser.parse_args(argv)
    transport = args.transport or choose("Choose connection method", ["ssh", "adb", "ttl", "local"])
    target = args.target or ("local" if transport == "local" else input("Target (SSH Host alias / ADB serial / TTL port): ").strip())
    if transport == "ssh" and (not HOST.fullmatch(target) or target.startswith("-")):
        parser.error("SSH target must be a configured Host alias")
    if transport == "adb" and (not SERIAL.fullmatch(target) or target.startswith("-")):
        parser.error("ADB target must be a device serial (run adb devices)")
    if transport == "ttl" and (not target.startswith("/dev/") or ".." in target):
        parser.error("TTL target must be a /dev/ serial path")
    if transport == "local" and target != "local":
        parser.error("Local transport requires target=local")
    if not 1 <= args.timeout <= 120 or not 1 <= args.duration <= 300 or not 1200 <= args.baud <= 3000000:
        parser.error("Invalid timeout, duration or baud")
    output = args.output or input("New local output directory (e.g. ./devices/w152d/session-001): ").strip()
    if not output:
        parser.error("Output directory required")
    print(f"Transport: {transport}, target: {target}, output: {output}")
    if input("Begin read-only evidence collection? [y/N]: ").strip().lower() not in ("y", "yes"):
        print("Cancelled")
        return 1
    try:
        folder = safe_output_dir(output)
        try:
            manifest = collect_ttl(target, folder, args.baud, args.duration) if transport == "ttl" else collect_shell(transport, target, folder, args.timeout)
            (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (folder / "manifest.json").chmod(0o600)
        except Exception:
            # Keep partial evidence for investigation; explicitly identify failure.
            (folder / "INCOMPLETE").write_text("Collection interrupted; inspect files before use.\n")
            raise
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Evidence saved: {folder}/manifest.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
