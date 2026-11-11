#!/usr/bin/env python3
"""Persistent, authorized device consoles for TTL/picocom, ADB and SSH.

One local process per session; only named, immutable read-only shell probes.
TTL never sends input without an observed shell prompt (or an explicitly
approved blank-line wake after the operator confirms the input is clear).
U-Boot, login prompts and unknown consoles never receive shell probes.
"""
import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import secrets
import shutil
import signal
import sys
import time

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SERIAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
UBOOT = re.compile(r"(?:^|\n)(?:=>|U-Boot>|[\w.-]+_bt\d+#)\s*\Z", re.I)
ANDROID_PROMPT = re.compile(r"(?:^|\n)\S+:/[^\n]*?\s*[#$]\s*\Z")
LINUX_PROMPT = re.compile(r"(?:^|\n)(?:[\w.-]+@[\w.-]+:[^\n]*|[\w.-]+:[~/#][^\n]*)[#$]\s*\Z")
LOGIN = re.compile(r"(?:login:|password:)\s*\Z", re.I)
MAX_PROBE_BYTES = 262144

# Allowlist only. Never pass user-provided shell strings to a device.
PROBES = {
    "common": (
        ("kernel", "uname -a"),
        ("cpu", "cat /proc/cpuinfo"),
        ("memory", "cat /proc/meminfo"),
        ("boot-args", "cat /proc/cmdline"),
        ("partitions", "cat /proc/partitions"),
        ("dt-compatible", "if test -r /sys/firmware/devicetree/base/compatible; then tr '\\000' '\\n' < /sys/firmware/devicetree/base/compatible; else echo unavailable; fi"),
        ("network", "ip -s link"),
        ("routes", "ip route"),
    ),
    "android": (
        ("os", "getprop ro.build.version.release"),
        ("model", "getprop ro.product.model"),
        ("platform", "getprop ro.board.platform"),
        ("hardware", "getprop ro.hardware"),
        ("boot-slot", "getprop ro.boot.slot_suffix"),
        ("block-names", "ls -l /dev/block/by-name"),
    ),
    "linux": (
        ("os", "cat /etc/os-release"),
        ("model", "if test -r /sys/firmware/devicetree/base/model; then cat /sys/firmware/devicetree/base/model; else echo unavailable; fi"),
        ("mounts", "cat /proc/mounts"),
    ),
}
IDENTIFY = "if command -v getprop >/dev/null 2>&1; then getprop ro.build.version.release; else printf 'linux\\n'; fi"


def console_state(data):
    """State from *last* console prompt, not an old U-Boot boot banner."""
    text = ANSI.sub("", data.decode("utf-8", "replace")).replace("\r", "").rstrip()
    tail = text[-2048:]
    if LOGIN.search(tail):
        return "login-required"
    if UBOOT.search(tail):
        return "uboot"
    if ANDROID_PROMPT.search(tail) or LINUX_PROMPT.search(tail):
        return "shell"
    return "unknown"


def transport_argv(transport, target, baud):
    """Fixed argv, no shell=True and no interpolated remote commands."""
    if transport == "ttl":
        if not target.startswith("/dev/") or ".." in target or "\x00" in target:
            raise ValueError("TTL target must be a serial device under /dev")
        argv = ["picocom", "-b", str(baud), "-d", "8", "-p", "1", "-f", "n", target]
        tool = "picocom"
    elif transport == "adb":
        if not SERIAL.fullmatch(target) or target.startswith("-"):
            raise ValueError("Invalid ADB serial")
        tool, argv = "adb", ["adb", "-s", target, "shell"]
    elif transport == "ssh":
        if not HOST.fullmatch(target) or target.startswith("-"):
            raise ValueError("SSH requires a configured Host alias")
        tool = "ssh"
        argv = ["ssh", "-tt", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
                target]
    else:
        raise ValueError("Unsupported transport")
    path = shutil.which(tool)
    if not path:
        raise RuntimeError(f"Missing {tool}; install it on the host before connecting")
    return [path] + argv[1:]


def fresh_directory(path):
    path = Path(path).expanduser()
    if path.exists() or path.is_symlink():
        raise ValueError("Session directory already exists")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("Session parent is not a directory")
    path = parent / path.name
    path.mkdir(mode=0o700)
    return path


class PersistentConsole:
    """Single PTY process, retained across all probes (including picocom)."""

    def __init__(self, argv, transcript):
        self.argv = argv
        self.transcript = Path(transcript)
        self.pid = None
        self.fd = None
        self.log = None
        self.recent = bytearray()
        self.closed = False

    def __enter__(self):
        self.log = os.open(str(self.transcript), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            pid, master = pty.fork()
        except Exception:
            os.close(self.log)
            self.log = None
            raise
        if pid == 0:  # pragma: no cover: executed only in forked PTY child
            try:
                os.execv(self.argv[0], self.argv)
            except OSError:
                os._exit(127)
        self.pid, self.fd = pid, master
        return self

    def _read(self, timeout):
        if self.fd is None:
            return b""
        readable, _, _ = select.select([self.fd], [], [], max(0, timeout))
        if not readable:
            return b""
        try:
            data = os.read(self.fd, 8192)
        except OSError as exc:
            if exc.errno != errno.EIO:
                raise
            return b""
        if data:
            os.write(self.log, data)
            self.recent.extend(data)
            if len(self.recent) > 8192:
                del self.recent[:-8192]
        return data

    def observe(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._read(min(.2, end - time.monotonic()))
        return console_state(bytes(self.recent))

    def wake_blank_line(self):
        """Only after operator confirms no unfinished input is on the UART."""
        os.write(self.fd, b"\r")

    def run_fixed(self, command, timeout=12):
        """Caller must only supply a command from the internal allowlist."""
        if command not in {IDENTIFY, *(c for entries in PROBES.values() for _, c in entries)}:
            raise ValueError("Command is not a permitted read-only probe")
        begin = "__UC_BEGIN_" + secrets.token_hex(8) + "__"
        end = "__UC_END_" + secrets.token_hex(8) + "__"
        # No newline/user input in any command; the marker lines are distinct
        # from terminal command echo. The rc is captured before printf.
        line = ("printf '\\n%s\\n' '" + begin + "'; " + command +
                "; _uc_rc=$?; printf '\\n%s:%s\\n' '" + end + "' \"$_uc_rc\"")
        os.write(self.fd, (line + "\r").encode("ascii"))
        collected = bytearray()
        deadline = time.monotonic() + timeout
        begin_pattern = re.compile(rb"(?:^|\n)" + begin.encode() + rb"\r?\n")
        end_pattern = re.compile(rb"(?:^|\n)" + end.encode() + rb":(\d+)\r?(?:\n|$)")
        while time.monotonic() < deadline and len(collected) < MAX_PROBE_BYTES:
            chunk = self._read(min(.2, deadline - time.monotonic()))
            if chunk:
                collected.extend(chunk)
                start = begin_pattern.search(collected)
                finish = end_pattern.search(collected)
                if start and finish and finish.start() >= start.end():
                    body = bytes(collected[start.end():finish.start()]).replace(b"\r", b"")
                    rc = int(finish.group(1))
                    if rc != 0:
                        return "error", body, rc
                    if not body.strip():
                        return "empty", body, rc
                    if body.strip() == b"unavailable":
                        return "unavailable", body, rc
                    return "ok", body, rc
        return "timeout" if len(collected) < MAX_PROBE_BYTES else "truncated", bytes(collected[-4096:]), None

    def __exit__(self, exc_type, exc, tb):
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            # Interactive programs may ignore SIGTERM (notably sh -i).
            # Never block forever while closing an owned PTY process.
            reaped = False
            for _ in range(20):
                try:
                    result, _ = os.waitpid(self.pid, os.WNOHANG)
                    if result:
                        reaped = True
                        break
                except ChildProcessError:
                    reaped = True
                    break
                time.sleep(.05)
            if not reaped:
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(self.pid, 0)
                except ChildProcessError:
                    pass
            self.pid = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.log is not None:
            os.close(self.log)
            self.log = None
        self.closed = True


def run_collection(transport, target, output, baud, timeout, wake_console=False, console_factory=PersistentConsole):
    argv = transport_argv(transport, target, baud)
    directory = fresh_directory(output)
    manifest = {"schema_version": 1, "workflow_version": "device-session-v1",
                "transport": transport, "target": target,
                "read_only": True, "state": "running", "items": [],
                "started_at": datetime.now(timezone.utc).isoformat(),
                "limitations": ["Session transcript may contain sensitive device identifiers",
                                "No login, U-Boot commands, privilege escalation or device writes"]}
    report = directory / "manifest.json"

    def save():
        temp = report.with_suffix(".tmp")
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        temp.chmod(0o600)
        os.replace(temp, report)

    def record(name, result):
        status, body, code = result
        filepath = directory / (name + ".txt")
        with filepath.open("xb") as stream:
            stream.write(body)
        filepath.chmod(0o600)
        manifest["items"].append({"name": name, "file": filepath.name,
                                   "status": status, "bytes": len(body),
                                   "returncode": code,
                                   "sha256": hashlib.sha256(body).hexdigest()})
        save()

    save()
    try:
        with console_factory(argv, directory / "console.log") as console:
            observed = console.observe(min(2, timeout))
            if transport == "ttl" and observed == "unknown" and wake_console:
                console.wake_blank_line()
                observed = console.observe(min(2, timeout))
            manifest["console_state"] = observed
            save()
            if transport == "ttl" and observed != "shell":
                manifest["state"] = "blocked"
                manifest["reason"] = ("No verified shell prompt. Login/U-Boot/unknown consoles "
                                      "never receive commands; do not send blind Enter.")
            elif observed in ("uboot", "login-required"):
                manifest["state"] = "blocked"
                manifest["reason"] = "Untrusted prompt; no automatic commands permitted"
            else:
                os_status, os_body, os_rc = console.run_fixed(IDENTIFY, timeout)
                record("identity", (os_status, os_body, os_rc))
                if os_status != "ok":
                    manifest["state"] = "blocked"
                    manifest["reason"] = "Could not positively identify an interactive shell"
                else:
                    platform = "linux" if os_body.strip() == b"linux" else "android"
                    manifest["os_family"] = platform
                    save()
                    for name, command in (*PROBES["common"], *PROBES[platform]):
                        status, body, code = console.run_fixed(command, timeout)
                        record(name, (status, body, code))
                        if status in ("timeout", "truncated"):
                            break  # Do not issue more input after losing prompt synchronization.
                    manifest["state"] = ("partial" if any(
                        x["status"] in ("error", "timeout", "truncated") for x in manifest["items"]
                    ) else "complete")
    except Exception as exc:
        manifest["state"] = "incomplete"
        manifest["failure"] = type(exc).__name__ + ": " + str(exc)[:200]
        raise
    finally:
        logfile = directory / "console.log"
        if logfile.exists():
            manifest["console_log_sha256"] = hashlib.sha256(logfile.read_bytes()).hexdigest()
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    return directory, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", required=True, choices=("ttl", "adb", "ssh"))
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True, help="Fresh private session directory")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--wake-console", action="store_true",
                        help="Operator confirmed serial input line is blank; send one CR")
    parser.add_argument("--approved-readonly", action="store_true",
                        help="Explicit approval for this session's fixed read-only commands")
    args = parser.parse_args(argv)
    if not args.approved_readonly:
        parser.error("Explicit --approved-readonly required")
    if not 1200 <= args.baud <= 3000000 or not 2 <= args.timeout <= 120:
        parser.error("Invalid baud/timeout")
    try:
        folder, manifest = run_collection(args.transport, args.target, args.output,
                                          args.baud, args.timeout, args.wake_console)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"session": str(folder), "state": manifest["state"],
                      "os_family": manifest.get("os_family"),
                      "console_state": manifest["console_state"],
                      "collected": len(manifest["items"])}, ensure_ascii=False))
    return 0 if manifest["state"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
