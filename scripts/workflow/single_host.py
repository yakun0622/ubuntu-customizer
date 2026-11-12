#!/usr/bin/env python3
"""Dispatch fixed Skill image operations on ONE Linux host or local Mac Lima VM.

No generic shell/command execution. On macOS, invokes an already-running,
user-configured local Lima Linux VM (not a remote machine), only using
filesystem paths within the user's shared home. Never starts/provisions a
VM, changes guest mounts, installs packages, flashes hardware or edits
original source images. RootFS/boot operations need separate approval.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
INSTANCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ACTIONS = {
    "inspect": "image_inspect.py",
    "plan": "image_plan.py",
    "rootfs": "rootfs_builder.py",
    "verify-bundle": "rootfs_builder.py",
    "verify-boot": "verify_first_boot.py",
}

def module(name):
    spec = importlib.util.spec_from_file_location("uc_local_" + name,
                                                  HERE / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

safe_output = module("safe_output")

def shared_path(path, *, output=False, directory=False, home=None):
    """Validate a host-home path shared into Lima at the same absolute path."""
    if path is None:
        raise ValueError("Required input/output path missing")
    home = (Path.home() if home is None else Path(home)).expanduser().resolve()
    raw = Path(path).expanduser().absolute()
    # Avoid confusing aliases and any user-controlled parent symlinks.
    if raw.is_symlink() or ".." in raw.parts:
        raise ValueError("Symlink/path traversal not allowed for Lima shared files")
    # Accept only verified macOS system-owned /var and /tmp aliases.
    # A user-created symlink anywhere in the parent chain is still rejected.
    safe_output.validate_system_alias_ancestors(raw)
    parent = raw.parent
    final = parent.resolve(strict=True) / raw.name if output else raw.resolve(strict=True)
    if home != final and home not in final.parents:
        raise ValueError("Lima inputs/outputs must be within the mounted host home")
    if output:
        if final.exists() or final.is_symlink():
            raise ValueError("Output already exists")
        if not final.parent.is_dir():
            raise ValueError("Output parent not a directory")
    elif directory and not final.is_dir():
        raise ValueError("Expected directory input")
    elif not directory and not final.is_file():
        raise ValueError("Expected regular-file input")
    return str(final)

def command_for(action, args, lima=False):
    """Build strictly fixed script invocation; no caller-provided shell code."""
    if action not in ACTIONS:
        raise ValueError("Unsupported workflow action")
    path = (lambda p, **kw: shared_path(p, **kw)) if lima else (
        lambda p, **kw: str(Path(p).expanduser().absolute()))
    script = path(HERE / ACTIONS[action]) if lima else str(HERE / ACTIONS[action])
    cmd = ["python3", script]
    inp = lambda p: path(p)
    out = lambda p: path(p, output=True)
    outdir = lambda p: path(p, output=True, directory=True)
    if action == "inspect":
        if not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256 or ""):
            raise ValueError("Trusted SHA-256 is required for source inspection")
        cmd += [inp(args.source), "--sha256", args.sha256, "--output", out(args.output)]
    elif action == "plan":
        if not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256 or ""):
            raise ValueError("Trusted SHA-256 is required for image planning")
        cmd += [path(args.session, directory=True), "--target", args.target,
                "--format", args.format, "--source", inp(args.source),
                "--sha256", args.sha256, "--source-arch", args.source_arch,
                "--output", out(args.output)]
        if args.boot_mode:
            cmd += ["--boot-mode", args.boot_mode]
    elif action == "rootfs":
        if not args.approved and not args.dry_run:
            raise ValueError("RootFS customization requires separate explicit --approved")
        cmd += [inp(args.plan), "--config", inp(args.config)]
        if lima:
            # Reject plans with source or public-key paths unavailable in Lima
            # before any rootfs script is allowed to write.
            plan_data = json.loads(Path(args.plan).read_text(encoding="utf-8"))
            recipe = json.loads(Path(args.config).read_text(encoding="utf-8"))
            inp(plan_data["source"]["path"])
            inp(recipe["first_boot"]["ssh_public_key"])
            path(plan_data["discovery"]["session"], directory=True)
        if args.dry_run:
            cmd += ["--dry-run"]
        else:
            cmd += ["--output-dir", outdir(args.output_dir), "--approved"]
    elif action == "verify-bundle":
        cmd += ["--verify-bundle", path(args.bundle, directory=True)]
    else:
        if not args.approved:
            raise ValueError("VM boot requires separate explicit --approved")
        cmd += ["--bundle", path(args.bundle, directory=True), "--report", out(args.report),
                "--timeout", str(args.timeout), "--approved"]
        if args.ovmf_code:
            cmd += ["--ovmf-code", inp(args.ovmf_code)]
        if args.ovmf_vars:
            cmd += ["--ovmf-vars", inp(args.ovmf_vars)]
    return cmd

def prepare(action, args, backend=None, instance="default", *,
            runner=subprocess.run, host_platform=None):
    """Inspect availability without executing the image operation."""
    host_platform = sys.platform if host_platform is None else host_platform
    backend = backend or ("lima" if host_platform == "darwin" else "native")
    if backend not in ("native", "lima"):
        raise ValueError("Unknown single-host adapter")
    if backend == "native" and host_platform != "linux":
        raise ValueError("Native RootFS/image adapter currently requires Linux")
    if backend == "lima" and host_platform != "darwin":
        raise ValueError("Lima local adapter is only supported on macOS")
    if not INSTANCE.fullmatch(instance):
        raise ValueError("Invalid local Lima instance")
    cmd = command_for(action, args, lima=(backend == "lima"))
    if backend == "native":
        return {"backend": "native-linux", "status": "ready", "command": cmd}
    # Never start a previously stopped Lima VM.
    destination = (args.output_dir if action == "rootfs" and not args.dry_run else
                   args.report if action == "verify-boot" else
                   args.output if action in ("inspect", "plan") else None)
    output_parent = Path(destination).expanduser().absolute().parent if destination else Path.home()
    capabilities = module("host_capabilities").probe_lima(
        instance, output_parent, HERE / ACTIONS[action], runner=runner)
    if not capabilities.get("available"):
        raise ValueError("Existing local Lima VM is unavailable: " + capabilities.get("reason", "unknown"))
    if not capabilities["shared_input_readable"]:
        raise ValueError("Skill scripts not mounted readably in Lima")
    write_action = action in ("inspect", "plan", "rootfs", "verify-boot") and not (
        action == "rootfs" and args.dry_run)
    if write_action and not capabilities["shared_output_writable"]:
        raise ValueError("Lima host-home mount is not writable for output. Change Lima mount only after user approval")
    needed = {"inspect": ("qemu-img", "guestfish", "virt-inspector", "virt-filesystems", "virt-drivers"),
              "plan": ("qemu-img", "guestfish", "virt-inspector", "virt-filesystems", "virt-drivers"),
              "rootfs": ("qemu-img", "virt-customize", "virt-sysprep", "guestfish",
                         "virt-inspector", "virt-drivers", "virt-filesystems", "virt-cat"),
              "verify-bundle": ("qemu-img",),
              "verify-boot": ("qemu-system-x86_64", "qemu-img")}
    missing = [x for x in needed[action] if not capabilities["tools"].get(x)]
    if missing:
        raise ValueError("Local Lima Linux VM lacks required tools: " + ",".join(missing))
    return {"backend": "lima-local-linux", "status": "ready",
            "command": ["limactl", "--tty=false", "shell", "--start=false", instance, *cmd]}

def execute(action, args, backend=None, instance="default", runner=subprocess.run,
            host_platform=None):
    prepared = prepare(action, args, backend, instance, runner=runner,
                       host_platform=host_platform)
    if args.check_only:
        return {"backend": prepared["backend"], "status": "ready",
                "will_execute": False}
    proc = runner(prepared["command"], stdin=subprocess.DEVNULL, timeout=3600,
                  check=False)
    return {"backend": prepared["backend"], "status": "completed" if proc.returncode == 0
            else "failed", "exit_code": proc.returncode, "will_execute": True}

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=tuple(ACTIONS))
    p.add_argument("--backend", choices=("native", "lima"))
    p.add_argument("--lima-instance", default="default")
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--source")
    p.add_argument("--sha256")
    p.add_argument("--session")
    p.add_argument("--target", choices=("virtual-machine", "physical-device"),
                   default="virtual-machine")
    p.add_argument("--source-arch", choices=("amd64", "arm64", "armhf", "riscv64"),
                   default="amd64")
    p.add_argument("--format", choices=("raw", "qcow2"), default="qcow2")
    p.add_argument("--boot-mode", choices=("bios", "uefi"))
    p.add_argument("--plan")
    p.add_argument("--config")
    p.add_argument("--bundle")
    p.add_argument("--output")
    p.add_argument("--output-dir")
    p.add_argument("--report")
    p.add_argument("--ovmf-code")
    p.add_argument("--ovmf-vars")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--approved", action="store_true")
    return p

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action in ("inspect", "plan") and args.output:
            args.output = str(workspace.checked_output(args.output))
        elif args.action == "rootfs" and not args.dry_run and args.output_dir:
            args.output_dir = str(workspace.checked_output(args.output_dir))
        elif args.action == "verify-boot" and args.report:
            args.report = str(workspace.checked_output(args.report))
        result = execute(args.action, args, args.backend, args.lima_instance)
        print(json.dumps(result))
        return 0 if result["status"] in ("ready", "completed") else 2
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print("ERROR: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2

ws_spec = importlib.util.spec_from_file_location(
    "uc_workspace_single_host", Path(__file__).with_name("project_workspace.py"))
workspace = importlib.util.module_from_spec(ws_spec)
ws_spec.loader.exec_module(workspace)

if __name__ == "__main__":
    raise SystemExit(main())
