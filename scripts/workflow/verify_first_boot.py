#!/usr/bin/env python3
"""Isolated QEMU first-boot verification for an approved RootFS build bundle.

QEMU is launched using TCG, a temporary disk snapshot, localhost UNIX
guest-agent channel, and restricted SLIRP DHCP with no host/Internet routing.
No SSH login, external ports, target disk writes, guest package installs or
firmware flashing. A fresh nonce and *fixed* read-only guest probe are
required; QEMU process status or serial output is never boot proof.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent

def sibling(name):
    spec = importlib.util.spec_from_file_location("uc_health_" + name, HERE / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

rootfs = sibling("rootfs_builder")
nocloud = sibling("nocloud")
progress = sibling("progress")

REQUIRED = ("linux_boot", "system_state", "cloud_init", "instance_id",
            "hostname", "machine_id", "ssh_host_keys", "ssh_service", "network")
MAX_RESPONSE = 32768

# This guest code is not a user-configurable hook. It performs read-only
# checks, publishes no secrets, and returns only specific properties. QGA
# guest-exec runs it as root in the ephemeral guest snapshot.
GUEST_PROBE = r"""
import json, os, pathlib, re, stat, subprocess, sys, time, uuid
nonce, expected_host, expected_instance = sys.argv[1:4]
checks = {}
def record(name, passed):
    checks[name] = bool(passed)
def command(args, timeout=20):
    try:
        p = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout[:32768]
    except (OSError, subprocess.TimeoutExpired):
        return 255, ""
def read(path, maximum=512):
    try:
        return pathlib.Path(path).read_text(encoding="utf-8").strip()[:maximum]
    except (OSError, UnicodeError):
        return ""
boot_id = read("/proc/sys/kernel/random/boot_id")
try:
    uuid.UUID(boot_id)
    boot_id_valid = True
except ValueError:
    boot_id_valid = False
record("linux_boot", boot_id_valid and pathlib.Path("/proc/1/comm").is_file()
       and pathlib.Path("/proc/sys/kernel/osrelease").is_file())
rc, state = command(["/usr/bin/systemctl", "is-system-running"])
record("system_state", rc == 0 and state.strip() == "running")
rc, out = command(["/usr/bin/cloud-init", "status", "--format", "json"], 45)
try:
    ci = json.loads(out) if rc == 0 else {}
    stage = ci.get("status") or ci.get("extended_status")
    errs = ci.get("errors", [])
    record("cloud_init", stage == "done" and errs == [])
except (ValueError, TypeError):
    record("cloud_init", False)
try:
    instance_data = json.loads(pathlib.Path("/run/cloud-init/instance-data.json").read_text())
    current_instance = instance_data.get("v1", {}).get("instance_id")
    record("instance_id", current_instance == expected_instance)
except (OSError, ValueError, TypeError, AttributeError):
    record("instance_id", False)
record("hostname", read("/etc/hostname", 128) == expected_host
       and os.uname().nodename == expected_host)
machine_id = read("/etc/machine-id", 80)
# A newly generalized clone must have the machine ID initialized after
# this guest boot; an old nonzero ID in the source is insufficient.
try:
    mid_stat = pathlib.Path("/etc/machine-id").stat()
except OSError:
    mid_stat = None
machine_id_valid = (bool(re.fullmatch(r"[a-f0-9]{32}", machine_id))
                    and machine_id != "0"*32)
# Read boot wall clock without trusting the host's machine identifiers.
boot_time = None
try:
    for line in pathlib.Path("/proc/stat").read_text().splitlines():
        if line.startswith("btime "):
            boot_time = int(line.split()[1])
            break
except (OSError, ValueError):
    pass
record("machine_id", machine_id_valid and mid_stat is not None
       and boot_time is not None and mid_stat.st_mtime >= boot_time - 10)
# A first-boot sysprep image should generate host keys after the current
# guest boot. This time-based check fails closed if guest clock is wrong.
boot_epoch = boot_time
keys = list(pathlib.Path("/etc/ssh").glob("ssh_host_*_key"))
def valid_key(p):
    try:
        s = p.stat()
        pub = pathlib.Path(str(p) + ".pub")
        return (stat.S_ISREG(s.st_mode) and s.st_size > 200
                and s.st_mode & 0o077 == 0
                and pub.is_file() and pub.stat().st_size > 40
                and boot_epoch is not None and s.st_mtime >= boot_epoch - 10)
    except OSError:
        return False
record("ssh_host_keys", any(valid_key(p) for p in keys))
rc1, active_ssh = command(["/usr/bin/systemctl", "is-active", "ssh"])
rc2, active_sshd = command(["/usr/bin/systemctl", "is-active", "sshd"])
record("ssh_service", (rc1 == 0 and active_ssh.strip() == "active")
       or (rc2 == 0 and active_sshd.strip() == "active"))
rc, out = command(["/usr/sbin/ip", "-j", "address"])
if rc != 0:
    rc, out = command(["/usr/bin/ip", "-j", "address"])
interfaces = []
try:
    interfaces = json.loads(out) if rc == 0 else []
except (ValueError, TypeError):
    interfaces = []
def net_ready(item):
    if item.get("ifname") == "lo" or item.get("operstate") != "UP":
        return False
    return any(a.get("family") == "inet" and
               not str(a.get("local","")).startswith("127.")
               for a in item.get("addr_info", []))
record("network", any(net_ready(i) for i in interfaces if isinstance(i, dict)))
print(json.dumps({"schema_version":1, "nonce":nonce, "boot_id_valid":boot_id_valid,
                  "machine_id":machine_id, "checks":checks},
                 separators=(",", ":")))
"""

def safe_file(path):
    p = Path(path).expanduser()
    if p.is_symlink() or not p.is_file():
        raise ValueError("Required local regular file missing")
    p = p.resolve()
    if p.parts[:2] in (("/", "dev"), ("/", "proc"), ("/", "sys")):
        raise ValueError("Host pseudo-filesystem input rejected")
    if any(ch in str(p) for ch in ("\r", "\n", ",")):
        raise ValueError("Unsafe QEMU filename characters")
    return p

def validate_bundle(bundle):
    folder = Path(bundle).expanduser()
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Expected completed RootFS bundle directory")
    folder = folder.resolve()
    rootfs.verify_bundle(folder)
    report = rootfs.read_json_regular(folder / "build-manifest.json")
    if (report.get("type") != "ubuntu-customizer/rootfs-build-result"
            or report.get("boot_tested") is not False):
        raise ValueError("Expected unbooted RootFS build result")
    disk = report["output"]
    path = safe_file(folder / disk["file"])
    if path.parent != folder:
        raise ValueError("Guest disk escaped bundle directory")
    recipe = rootfs.read_json_regular(folder / "build-config.json", 16384)
    boot = recipe["first_boot"]
    if boot["mode"] != "nocloud":
        raise ValueError("NoCloud required for first-boot verification")
    expected = (recipe["hostname"], boot["instance_id"])
    if not all(isinstance(s, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", s) for s in expected):
        raise ValueError("Invalid expected guest first-boot identity")
    observed = report.get("guest_evidence", {}).get("observations", {})
    advertised = observed.get("boot_modes") or [observed.get("boot_mode")]
    firmware = report.get("selected_firmware") or observed.get("boot_mode")
    if firmware not in ("uefi", "bios") or firmware not in advertised:
        raise ValueError("Verified guest firmware must be explicitly selected from inspected supported modes")
    if report.get("source_plan_architecture") != "amd64":
        raise ValueError("Only x86_64 VM first-boot verification is implemented")
    return folder, path, report, recipe, firmware

def build_cmd(image, fmt, qga_socket, seed, firmware, ovmf_code=None, ovmf_vars=None):
    if fmt not in ("raw", "qcow2"):
        raise ValueError("Unsupported guest disk format")
    image, seed = safe_file(image), safe_file(seed)
    if not str(qga_socket).startswith("/") or "," in str(qga_socket):
        raise ValueError("Invalid QGA socket path")
    args = ["qemu-system-x86_64", "-machine", "q35", "-accel", "tcg",
            "-m", "1024", "-smp", "2", "-nodefaults", "-no-user-config",
            "-display", "none", "-monitor", "none", "-serial", "none",
            "-no-reboot", "-snapshot",
            "-drive", "file=" + str(image) + ",format=" + fmt + ",if=virtio",
            "-drive", "file=" + str(seed) + ",format=raw,media=cdrom,readonly=on",
            "-netdev", "user,id=isolated,restrict=on",
            "-device", "virtio-net-pci,netdev=isolated",
            "-chardev", "socket,id=qga,path=" + str(qga_socket) + ",server=on,wait=off",
            "-device", "virtio-serial-pci",
            "-device", "virtserialport,chardev=qga,name=org.qemu.guest_agent.0"]
    if firmware == "uefi":
        if not ovmf_code or not ovmf_vars:
            raise ValueError("UEFI images require explicit trusted OVMF code and variables")
        code, variables = safe_file(ovmf_code), safe_file(ovmf_vars)
        args += ["-drive", "if=pflash,format=raw,unit=0,readonly=on,file=" + str(code),
                 "-drive", "if=pflash,format=raw,unit=1,file=" + str(variables)]
    elif firmware != "bios":
        raise ValueError("Unverified guest firmware boot mode")
    return args

class GuestAgent:
    def __init__(self, path):
        self.path = str(path)
        self.sock = None
        self.buffer = b""

    def __enter__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(3)
        self.sock.connect(self.path)
        return self

    def __exit__(self, *args):
        if self.sock is not None:
            self.sock.close()

    def call(self, command, arguments=None):
        payload = {"execute": command}
        if arguments is not None:
            payload["arguments"] = arguments
        self.sock.sendall(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
        until = time.monotonic() + 10
        while time.monotonic() < until:
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if not line:
                    continue
                answer = json.loads(line)
                if "error" in answer:
                    raise RuntimeError("Guest Agent rejected request: " + command)
                if "return" not in answer:
                    raise ValueError("Invalid Guest Agent reply")
                return answer["return"]
            self.sock.settimeout(max(0.1, min(1.0, until-time.monotonic())))
            try:
                packet = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not packet:
                raise RuntimeError("Guest Agent disconnected")
            self.buffer += packet
            if len(self.buffer) > MAX_RESPONSE * 2:
                raise ValueError("Guest Agent response too large")
        raise TimeoutError("Guest Agent response timeout")

    def exec(self, nonce, hostname, instance_id, deadline):
        item = self.call("guest-exec", {
            "path": "/usr/bin/python3", "arg": ["-c", GUEST_PROBE, nonce, hostname, instance_id],
            "capture-output": True})
        pid = item.get("pid") if isinstance(item, dict) else None
        if type(pid) is not int or pid <= 0:
            raise ValueError("Guest Agent did not return a valid process ID")
        while time.monotonic() < deadline:
            result = self.call("guest-exec-status", {"pid": pid})
            if not isinstance(result, dict):
                raise ValueError("Malformed guest-exec-status")
            if result.get("exited") is True:
                if result.get("out-truncated") or result.get("err-truncated"):
                    raise ValueError("Truncated guest health evidence")
                if result.get("exitcode") != 0 or "signal" in result:
                    raise RuntimeError("Fixed guest health probe failed")
                out = result.get("out-data")
                if not isinstance(out, str) or len(out) > MAX_RESPONSE:
                    raise ValueError("Missing or excessive guest health evidence")
                return base64.b64decode(out, validate=True).decode("utf-8")
            time.sleep(0.5)
        raise TimeoutError("Guest health probe deadline exceeded")

def evaluate_probe(raw, nonce):
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Malformed guest health probe result")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Invalid guest health schema")
    if data.get("nonce") != nonce or data.get("boot_id_valid") is not True:
        raise ValueError("Guest health challenge/boot identity did not validate")
    checks = data.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(REQUIRED):
        raise ValueError("Missing or unexpected guest health checks")
    if any(type(value) is not bool for value in checks.values()):
        raise ValueError("Invalid boolean guest health result")
    mid = data.get("machine_id")
    if not isinstance(mid, str) or not re.fullmatch(r"[a-f0-9]{32}", mid) or mid == "0"*32:
        raise ValueError("Machine ID missing or malformed")
    return checks  # Never persist the raw machine-id, keys or guest stdout.

def verify_first_boot(bundle, timeout=240, ovmf_code=None, ovmf_vars=None):
    if type(timeout) is not int or not 30 <= timeout <= 900:
        raise ValueError("Boot timeout must be 30–900 seconds")
    folder, image, manifest, recipe, firmware = validate_bundle(bundle)
    session = progress.session_from_build(manifest)
    # For legacy RootFS manifests without session linkage, status is simply
    # unavailable; the build and checks run as normal.
    with progress.tracking(session, "verify", 6) as tracker:
        tracker.advance(1)
        if not shutil.which("qemu-system-x86_64"):
            tracker.blocked()
            raise RuntimeError("qemu-system-x86_64 is not installed")
        if firmware == "uefi" and not (ovmf_code and ovmf_vars):
            tracker.blocked()
            raise ValueError("UEFI guest requires trusted OVMF firmware files")
        with tempfile.TemporaryDirectory(prefix="uc-boot-") as temp:
            scratch = Path(temp)
            qga_socket = scratch / "qga.sock"
            seed = folder / "seed.iso"
            if not seed.is_file():
                # Build a temporary NoCloud image from the verified seed
                # files, never modifying the published bundle.
                seed = scratch / "seed.iso"
                nocloud.make_iso(folder / "seed", seed)
            if firmware == "uefi":
                template = safe_file(ovmf_vars)
                vars_copy = scratch / "OVMF_VARS.fd"
                shutil.copyfile(template, vars_copy)
                vars_copy.chmod(0o600)
            else:
                vars_copy = None
            args = build_cmd(image, manifest["output"]["format"], qga_socket,
                             seed, firmware, ovmf_code, vars_copy)
            tracker.advance(2)
            nonce = secrets.token_hex(24)
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            report = {
                "schema_version": 1, "type": "ubuntu-customizer/first-boot-health",
                "image_sha256": manifest["output"]["sha256"],
                "source_plan_sha256": manifest["image_plan_sha256"],
                "boot_attempted": True, "boot_confirmed": False,
                "first_boot_confirmed": False,
                "isolation": {"snapshot": True, "acceleration": "tcg",
                              "external_network": False, "host_port_forwarding": False},
                "qga_connected": False, "checks": {name: False for name in REQUIRED},
                "status": "blocked", "reason": "guest_not_verified",
                "warning": "Guest-agent reports are not independent hardware attestation."
            }
            try:
                tracker.advance(3)
                deadline = time.monotonic() + timeout
                guest = None
                last_checks = None
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        report["reason"] = "qemu_exited_before_health"
                        report["status"] = "failed"
                        tracker.failed()
                        break
                    if qga_socket.exists():
                        try:
                            # Ping is a readiness probe; its transient
                            # failures before the agent starts are retryable.
                            try:
                                with GuestAgent(qga_socket) as agent:
                                    agent.call("guest-ping")
                                    report["qga_connected"] = True
                                    tracker.advance(4)
                                    guest = agent.exec(nonce, recipe["hostname"],
                                                       recipe["first_boot"]["instance_id"], deadline)
                            except (OSError, TimeoutError):
                                time.sleep(1)
                                continue
                            checks = evaluate_probe(guest, nonce)
                            report["checks"] = checks
                            last_checks = checks
                            tracker.advance(5)
                            if all(checks.values()):
                                report["boot_confirmed"] = True
                                report["first_boot_confirmed"] = True
                                report["reason"] = "verified_guest_health"
                                report["status"] = "passed"
                                break
                            report["reason"] = "guest_health_checks_failed"
                            # Boot and cloud-init may still be in progress.
                            time.sleep(2)
                        except (ConnectionRefusedError, FileNotFoundError,
                                socket.timeout, TimeoutError):
                            time.sleep(1)
                        except (OSError, RuntimeError, ValueError) as exc:
                            report["reason"] = "guest_agent_protocol_or_health_failure"
                            report["status"] = "failed"
                            report["check_error_type"] = type(exc).__name__
                            tracker.failed()
                            break
                    time.sleep(0.5)
                else:
                    report["reason"] = ("guest_health_checks_failed" if last_checks is not None
                                        else "guest_agent_or_health_timeout")
                if report["status"] != "passed" and tracker.final_state is None:
                    tracker.blocked()
                tracker.advance(6)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
            if rootfs.sha256_file(image) != manifest["output"]["sha256"]:
                tracker.failed()
                raise ValueError("Original image changed despite QEMU snapshot isolation")
            return report

def save_report(path, result):
    destination = Path(path).expanduser()
    if destination.is_symlink() or destination.exists() or not destination.parent.is_dir():
        raise ValueError("Verification report must be a new regular file")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", required=True, help="RootFS Builder output directory")
    p.add_argument("--timeout", type=int, default=240)
    p.add_argument("--ovmf-code", help="trusted OVMF_CODE for UEFI guests")
    p.add_argument("--ovmf-vars", help="trusted OVMF_VARS template for UEFI guests")
    p.add_argument("--report", required=True, help="NEW local health report file")
    p.add_argument("--approved", action="store_true", help="user authorizes isolated QEMU boot")
    args = p.parse_args(argv)
    try:
        if not args.approved:
            raise ValueError("QEMU boot requires distinct explicit --approved consent")
        destination = Path(args.report).expanduser()
        if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
            raise ValueError("Health report must be new in an existing directory")
        result = verify_first_boot(args.bundle, args.timeout, args.ovmf_code, args.ovmf_vars)
        save_report(destination, result)
        print(json.dumps({"report": str(destination), "status": result["status"],
                          "boot_confirmed": result["boot_confirmed"]}))
        return 0 if result["status"] == "passed" else 2
    except (OSError, ValueError, RuntimeError, TypeError, KeyError,
            subprocess.TimeoutExpired) as exc:
        # Only after explicit user approval and a valid, new destination:
        # preserve a machine-readable failure report without guest stdout,
        # private machine IDs, SSH key data, image paths or exception text.
        if args.approved:
            destination = Path(args.report).expanduser()
            if (not destination.exists() and not destination.is_symlink()
                    and destination.parent.is_dir()):
                failure = {
                    "schema_version": 1,
                    "type": "ubuntu-customizer/first-boot-health",
                    "boot_attempted": None, "boot_confirmed": False,
                    "first_boot_confirmed": False,
                    "status": "failed", "reason": "verification_error",
                    "error_type": type(exc).__name__,
                    "checks": {name: False for name in REQUIRED},
                }
                try:
                    save_report(destination, failure)
                except (OSError, ValueError):
                    pass
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
