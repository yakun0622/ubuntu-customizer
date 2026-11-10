#!/usr/bin/env python3
"""Explicit, replaceable Skill verification adapters.

Choose exactly one: static image inspection, passive ARM UART evidence, or
an approved QEMU guest-health test. Boot proof is NEVER inferred from
static inspection, raw serial text, or a wrapper's exit status.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BACKENDS = ("static-image", "arm-boot-log", "qemu-health")

def module(name):
    spec = importlib.util.spec_from_file_location("uc_verify_adapter_" + name,
                                                  HERE / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

def execute(args):
    if args.backend not in BACKENDS:
        raise ValueError("Unrecognized verification backend")
    if args.backend == "arm-boot-log":
        if not (args.log or args.session or args.source):
            raise ValueError("ARM boot evidence requires a log, session or image")
        if not args.output:
            raise ValueError("NEW evidence report path required")
        physical = module("physical_verify")
        # Dedicated read-only adapter, never invokes QEMU.
        result = physical.evaluate(args.log, args.session, args.source, args.sha256)
        output = Path(args.output)
        if output.exists() or output.is_symlink() or not output.parent.is_dir():
            raise ValueError("Output report already exists or has no parent")
        import os
        fd = os.open(output, os.O_WRONLY | os.O_EXCL | os.O_CREAT, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
                f.write("\n")
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        return {"backend": args.backend, "status": "evidence_collected",
                "report": str(output), "boot_confirmed": False}
    dispatcher = module("single_host")
    action = "inspect" if args.backend == "static-image" else "verify-boot"
    if action == "inspect" and (not args.source or not args.sha256 or not args.output):
        raise ValueError("Static image verification requires --source, --sha256 and --output")
    if action == "verify-boot" and (not args.bundle or not args.report or not args.approved):
        raise ValueError("QEMU boot requires bundle, report and separate --approved")
    subargs = dispatcher.parser().parse_args(
        ([action] + (["--source", args.source, "--sha256", args.sha256,
                      "--output", args.output] if action == "inspect" else
                     ["--bundle", args.bundle, "--report", args.report,
                      "--timeout", str(args.timeout), "--approved"] +
                     (["--ovmf-code", args.ovmf_code] if args.ovmf_code else []) +
                     (["--ovmf-vars", args.ovmf_vars] if args.ovmf_vars else [])) +
         (["--backend", args.host_backend] if args.host_backend else []) +
         ["--lima-instance", args.lima_instance]))
    result = dispatcher.execute(action, subargs, subargs.backend, subargs.lima_instance)
    if result["status"] != "completed":
        return {"backend": args.backend, "status": "unverified", "boot_confirmed": False,
                "operation_exit_code": result.get("exit_code")}
    if action == "inspect":
        # qemu-img and guest filesystem inspection are never boot evidence.
        return {"backend": args.backend, "status": "inspected",
                "report": args.output, "boot_confirmed": False}
    report = module("rootfs_builder").read_json_regular(args.report)
    accepted = (report.get("type") == "ubuntu-customizer/first-boot-health"
                and report.get("boot_confirmed") is True
                and report.get("first_boot_confirmed") is True
                and report.get("status") == "passed"
                and isinstance(report.get("checks"), dict)
                and bool(report["checks"])
                and all(value is True for value in report["checks"].values()))
    return {"backend": args.backend, "status": "verified_guest_health" if accepted
            else "unverified", "boot_confirmed": accepted,
            "report": args.report}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=BACKENDS, required=True)
    p.add_argument("--host-backend", choices=("native", "lima"))
    p.add_argument("--lima-instance", default="default")
    p.add_argument("--log")
    p.add_argument("--session")
    p.add_argument("--source")
    p.add_argument("--sha256")
    p.add_argument("--bundle")
    p.add_argument("--output")
    p.add_argument("--report")
    p.add_argument("--approved", action="store_true")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--ovmf-code")
    p.add_argument("--ovmf-vars")
    args = p.parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps(result))
        return 0 if result["status"] in ("evidence_collected", "inspected",
                                          "verified_guest_health") else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
