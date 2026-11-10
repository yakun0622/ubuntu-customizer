#!/usr/bin/env python3
"""AI Agent Skill: inspect ONE controlling host and select local image adapters.

No installs, connections to external machines, VM starts, mounts, or writes.
macOS Linux execution is supported through an explicitly pre-existing local
Lima guest with tools already installed; nothing starts automatically.
"""
import argparse
import json
import platform
import re
import shutil
import subprocess
import sys

ARCHES = {"x86_64": "amd64", "AMD64": "amd64", "aarch64": "arm64",
          "arm64": "arm64", "armv7l": "armhf", "riscv64": "riscv64"}
CORE = ("python3", "qemu-img", "virt-filesystems", "virt-inspector",
        "virt-drivers", "guestfish", "virt-cat", "virt-customize", "virt-sysprep")
QEMU = {"amd64": "qemu-system-x86_64", "arm64": "qemu-system-aarch64"}
INSTANCE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
# Script is fixed, read-only, and never incorporates user input as code.
GUEST_PROBE = (
    "import json,os,platform,shutil,sys;"
    "names=" + repr(CORE + ("qemu-system-x86_64", "qemu-system-aarch64",
                            "genisoimage", "mkisofs")) + ";"
    "print(json.dumps({'os':sys.platform,'arch':platform.machine(),"
    "'tools':{n:bool(shutil.which(n)) for n in names},"
    "'cwd_writable':os.access(sys.argv[1],os.W_OK),"
    "'input_readable':os.access(sys.argv[2],os.R_OK)}))"
)

def probe_lima(instance="default", output_parent="/", input_file="/", runner=subprocess.run):
    """Inspect existing Lima instance. --start=false prohibits implicit VM start."""
    if not INSTANCE.fullmatch(instance):
        raise ValueError("Invalid Lima instance identifier")
    if not shutil.which("limactl"):
        return {"available": False, "reason": "limactl_missing"}
    command = ["limactl", "--tty=false", "shell", "--start=false", instance,
               "python3", "-c", GUEST_PROBE, str(output_parent), str(input_file)]
    try:
        result = runner(command, stdin=subprocess.DEVNULL, capture_output=True,
                        timeout=15, check=False, text=True)
        if result.returncode:
            return {"available": False, "reason": "lima_guest_unavailable_or_not_running"}
        data = json.loads(result.stdout)
        if (data.get("os") != "linux" or not isinstance(data.get("tools"), dict)
                or not isinstance(data.get("cwd_writable"), bool)
                or not isinstance(data.get("input_readable"), bool)):
            return {"available": False, "reason": "invalid_lima_guest_probe"}
        return {"available": True, "os": "linux",
                "arch": ARCHES.get(data.get("arch"), "unknown"),
                "tools": {name: bool(data["tools"].get(name)) for name in
                          CORE + tuple(QEMU.values()) + ("genisoimage", "mkisofs")},
                "shared_output_writable": data["cwd_writable"],
                "shared_input_readable": data["input_readable"]}
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return {"available": False, "reason": "lima_probe_failed"}

def decide(host_os, host_arch, tools, target, target_arch, lima=None):
    """Return independent capabilities; never turn missing evidence into support."""
    if target not in ("virtual-machine", "physical-device"):
        raise ValueError("Unknown target type")
    if target_arch not in ("amd64", "arm64", "armhf", "riscv64", "unknown"):
        raise ValueError("Unknown target CPU architecture")
    needed = [name for name in CORE if not tools.get(name)]
    build = {"backend": None, "status": "blocked", "missing": needed}
    if target == "physical-device":
        build["reason"] = "physical_BSP_bootloader_DTB_recovery_not_verified"
    elif host_os == "linux" and not needed:
        build.update({"backend": "native-linux", "status": "available",
                      "missing": [], "reason": "local_offline_builder"})
    elif host_os == "darwin" and lima and lima.get("available"):
        miss = [name for name in CORE if not lima["tools"].get(name)]
        if miss:
            build.update({"missing": miss, "reason": "lima_guest_missing_tools"})
        elif not lima.get("shared_input_readable") or not lima.get("shared_output_writable"):
            build.update({"missing": [], "reason": "lima_shared_paths_not_accessible_or_writable"})
        else:
            build.update({"backend": "lima-local-linux", "status": "available",
                          "missing": [], "reason": "same_physical_mac_linux_vm"})
    else:
        build["reason"] = ("requires_local_linux_guest" if host_os == "darwin"
                           else "native_tools_unavailable")
    # Static device-evidence inspection is Python-only on all host OSes.
    inspections = {"device_evidence": "available",
                   "source_image": ("available" if build["status"] == "available"
                                    else "needs_libguestfs_backend"),
                   "arm_boot_log": "available"}
    backend_tools = (lima["tools"] if build["backend"] == "lima-local-linux"
                     else tools)
    vm_qemu = (target == "virtual-machine" and target_arch == "amd64"
               and build["status"] == "available"
               and bool(backend_tools.get("qemu-system-x86_64")))
    validation = [
        {"id": "static-evidence", "status": "available",
         "boot_confirmed": False},
        {"id": "arm-serial-boot-log", "status": "available" if target == "physical-device"
         else "not_applicable", "boot_confirmed": False},
        {"id": "qemu-guest-health", "status": "available" if vm_qemu else "unavailable",
         "boot_confirmed": False, "requires": "approved AMD64 VM, QGA, NoCloud, OVMF if UEFI"}
    ]
    return {"target": target, "target_arch": target_arch, "build": build,
            "inspections": inspections, "verification": validation}

def inspect(target="virtual-machine", target_arch="amd64", lima_instance="default",
            output_parent="/", input_file="/", probe=True):
    host = {"os": sys.platform, "arch": ARCHES.get(platform.machine(), "unknown"),
            "cpu_name": platform.machine()}
    tools = {name: bool(shutil.which(name)) for name in
             CORE + tuple(QEMU.values()) + ("limactl", "genisoimage", "mkisofs")}
    lima = (probe_lima(lima_instance, output_parent, input_file) if
            sys.platform == "darwin" and probe else {"available": False,
            "reason": "not_probed_or_not_macos"})
    plan = decide(host["os"], host["arch"], tools, target, target_arch, lima)
    return {"schema_version": 1, "type": "ubuntu-customizer/local-host-capabilities",
            "host": host, "tools": tools, "lima": lima, "plan": plan,
            "no_automatic_install": True, "no_vm_start": True,
            "physical_device_writes": False}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("virtual-machine", "physical-device"),
                        default="virtual-machine")
    parser.add_argument("--target-arch",
                        choices=("amd64", "arm64", "armhf", "riscv64", "unknown"),
                        default="unknown")
    parser.add_argument("--lima-instance", default="default")
    parser.add_argument("--output-parent", default="/", help="existing shared output directory for Lima probe")
    parser.add_argument("--input-file", default="/", help="existing shared input to test for Lima read access")
    parser.add_argument("--skip-lima", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = inspect(args.target, args.target_arch, args.lima_instance,
                         args.output_parent, args.input_file,
                         probe=not args.skip_lima)
        print(json.dumps(result, indent=2))
        return 0
    except ValueError as exc:
        parser.error(str(exc))

if __name__ == "__main__":
    raise SystemExit(main())
