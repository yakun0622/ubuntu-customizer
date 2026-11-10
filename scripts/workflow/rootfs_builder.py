#!/usr/bin/env python3
"""Opt-in, offline, VM-only RootFS customization from a verified image-plan.

Never operate on a live guest, remote system, host block device, or the
original image. Fixed operations only: hostname, MOTD, NoCloud seed,
machine-id and SSH host-key sysprep. No packages, arbitrary scripts, networking,
flash, mount or physical-board BSP actions. A built disk is NOT a verified boot.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent

def sibling(name):
    spec = importlib.util.spec_from_file_location("uc_rootfs_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

build_image = sibling("build_image")
image_inspect = sibling("image_inspect")
nocloud = sibling("nocloud")
progress = sibling("progress")

MAX_CONFIG = 16 * 1024
MAX_MOTD = 2048
TOOLS = ("qemu-img", "virt-cat", "virt-customize", "virt-sysprep",
         "virt-inspector", "virt-filesystems", "virt-drivers", "guestfish")
SYSPREP_OPERATIONS = "machine-id,ssh-hostkeys"
GUEST_FORMATS = {"raw": "image.img", "qcow2": "image.qcow2"}

def sha256_file(path):
    return build_image.hash_file(Path(path))

def read_json_regular(path, size_limit=2 * 1024 * 1024):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > size_limit:
        raise ValueError("Missing, oversized or symbolic-link JSON input")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Input must be a JSON object")
    return result

def validate_config(config):
    if not isinstance(config, dict) or set(config) != {"schema_version", "hostname", "motd", "first_boot"}:
        raise ValueError("RootFS recipe must contain exactly schema_version, hostname, motd, first_boot")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("Unsupported RootFS recipe version")
    hostname = config["hostname"]
    motd = config["motd"]
    boot = config["first_boot"]
    if not isinstance(hostname, str) or not nocloud.HOST.fullmatch(hostname):
        raise ValueError("Invalid guest hostname")
    if (not isinstance(motd, str) or len(motd.encode("utf-8")) > MAX_MOTD
            or any(ord(ch) < 32 and ch not in "\n\t" for ch in motd)
            or "\r" in motd):
        raise ValueError("MOTD must be short, safe UTF-8 text")
    if not isinstance(boot, dict) or set(boot) != {
            "mode", "username", "instance_id", "ssh_public_key", "seed_iso"}:
        raise ValueError("First-boot requires a strict NoCloud specification")
    if boot["mode"] != "nocloud" or type(boot["seed_iso"]) is not bool:
        raise ValueError("Only NoCloud first-boot is supported; seed_iso must be boolean")
    if (not isinstance(boot["username"], str) or boot["username"] == "root"
            or not nocloud.USER.fullmatch(boot["username"])):
        raise ValueError("Invalid first-boot username")
    if (not isinstance(boot["instance_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", boot["instance_id"])):
        raise ValueError("Invalid first-boot instance ID")
    if not isinstance(boot["ssh_public_key"], str):
        raise ValueError("SSH public key path required")
    nocloud.read_key(boot["ssh_public_key"])  # Reject private keys or unsafe files.
    return config

def safe_destination(output_dir):
    target = Path(output_dir).expanduser().absolute()
    if ".." in target.parts:
        raise ValueError("Parent-directory traversal is not allowed for output bundles")
    if target.exists() or target.is_symlink():
        raise ValueError("Output bundle directory must be new")
    if target.parts[:2] in (("/", "dev"), ("/", "proc"), ("/", "sys")):
        raise ValueError("Cannot create build results on host pseudo-filesystems")
    for ancestor in (target.parent, *target.parent.parents):
        if ancestor.is_symlink():
            raise ValueError("Symlink output ancestors are not allowed")
    if not target.parent.is_dir():
        raise ValueError("Output parent must already exist")
    if any(ch in str(target) for ch in (":", ",", "\n", "\r")):
        raise ValueError("Unsupported characters in output path")
    return target

def tool_env():
    return {**os.environ, "LIBGUESTFS_BACKEND": "direct",
            "LIBGUESTFS_NETWORK": "0", "LIBGUESTFS_DEBUG": "0"}

def run_checked(args, timeout=1800, max_output=65536):
    if not shutil.which(args[0]):
        raise RuntimeError("Required offline builder tool unavailable: " + args[0])
    try:
        proc = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                              env=tool_env(), timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Offline build operation unavailable or timed out: " + args[0]) from exc
    if proc.returncode or len(proc.stdout) > max_output or len(proc.stderr) > max_output:
        # Avoid reproducing guest contents or secrets from tool stdout/stderr.
        raise RuntimeError("Offline build operation failed: " + args[0])
    return proc.stdout

def stable_guest(observed):
    os_info = observed.get("guest_os", {})
    boot = observed.get("boot_details", {})
    return {
        "architecture": os_info.get("architecture"),
        "os_class": os_info.get("os_class"),
        "distribution": os_info.get("distribution"),
        "partition_table": observed.get("partition_table"),
        "partitions": observed.get("partitions"),
        "bootloader": boot.get("bootloader"),
        "boot_mode": boot.get("boot_mode"),
        "kernels": boot.get("kernels"),
    }

def inspect_output(path, source_observations, hostname, motd):
    sha = sha256_file(path)
    report = image_inspect.inspect(path, sha)
    if report.get("gaps") or stable_guest(report.get("observations", {})) != stable_guest(source_observations):
        raise ValueError("Customized image guest/boot/partition evidence is incomplete or changed")
    value = run_checked(["virt-cat", "--format=qcow2" if path.suffix == ".qcow2"
                         else "--format=raw", "-a", str(path), "/etc/hostname"],
                        timeout=120).decode("utf-8", "replace").strip()
    if value != hostname:
        raise ValueError("Guest hostname customization not verified")
    value = run_checked(["virt-cat", "--format=qcow2" if path.suffix == ".qcow2"
                         else "--format=raw", "-a", str(path), "/etc/motd"],
                        timeout=120).decode("utf-8", "replace")
    if value != motd:
        raise ValueError("Guest MOTD customization not verified")
    return report

def dry_run(plan, config):
    validate_config(config)
    # Rechecks trusted input SHA-256 and independent guest inspection, not just
    # an editable JSON plan that claims the source image is compatible.
    source = build_image.validate(plan)
    inspection = plan["source"]["inspection"]["observations"]
    if inspection.get("guest_os", {}).get("os_class") != "linux":
        raise ValueError("Only inspected Linux guest RootFS images supported")
    missing = sorted(name for name in TOOLS if not shutil.which(name))
    if config["first_boot"]["seed_iso"] and not (shutil.which("genisoimage") or shutil.which("mkisofs")):
        missing.append("genisoimage/mkisofs")
    return {
        "schema_version": 1,
        "type": "ubuntu-customizer/rootfs-preview",
        "target": "virtual-machine",
        "source_sha256": sha256_file(source),
        "source_architecture": plan.get("architecture"),
        "format": plan["format"],
        "operations": ["qemu-img copy into private RAW staging", "check cloud-init configuration",
                       "virt-customize hostname and MOTD on private clone",
                       "virt-sysprep machine-id and SSH host keys on clone",
                       "generate NoCloud seed files" + (" and ISO" if config["first_boot"]["seed_iso"] else ""),
                       "convert staged disk", "re-inspect guest, validate files, hash artifact"],
        "missing_tools": missing,
        "execution": "disabled",
        "limitations": ["No target writes, no package installation, no arbitrary scripts",
                        "NoCloud activation and first boot are not validated by offline inspection",
                        "Source image must be powered off and not concurrently modified",
                        "Physical-device BSP/firmware integration is not supported"],
    }

def assemble(plan, config, output_dir, approved=False):
    if not approved:
        raise ValueError("Offline artifact customization requires explicit --approved")
    session = progress.session_from_plan(plan)
    with progress.tracking(session, "rootfs-build", 7) as tracker:
        if (plan.get("target") != "virtual-machine"
                or plan.get("build_allowed") is not True or plan.get("blockers")):
            tracker.blocked()
            raise ValueError("Only an unblocked VM image plan can be customized")
        preview = dry_run(plan, config)
        if preview["missing_tools"]:
            tracker.blocked()
            raise RuntimeError("Offline builder dependencies missing: " + ", ".join(preview["missing_tools"]))
        source = build_image.validate(plan)
        original_info = build_image.inspect_image(source)
        if original_info["format"] not in GUEST_FORMATS:
            raise ValueError("Unsupported base disk format")
        if original_info["virtual-size"] > 64 * 1024**3:
            tracker.blocked()
            raise ValueError("RootFS v1 limits virtual image size to 64 GiB")
        tracker.advance(1)
        output = safe_destination(output_dir)
        cfg_sha = hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        raw_baseline = plan["source"]["inspection"]["observations"]
        with tempfile.TemporaryDirectory(prefix=".uc-rootfs-", dir=output.parent) as work:
            stage = Path(work)
            scratch = stage / "working.raw"
            run_checked(["qemu-img", "convert", "-f", original_info["format"], "-O", "raw",
                         str(source), str(scratch)])
            scratch.chmod(0o600)
            if sha256_file(source) != plan["source"]["sha256"]:
                raise ValueError("Original source image changed during staging")
            tracker.advance(2)
            # If the original guest is not cloud-init capable, a NoCloud seed
            # would be silently ignored. Fail closed before any guest edit.
            run_checked(["virt-cat", "--format=raw", "-a", str(scratch),
                         "/etc/cloud/cloud.cfg"], timeout=120)
            motd_path = stage / "motd.txt"
            motd_path.write_text(config["motd"], encoding="utf-8")
            motd_path.chmod(0o600)
            run_checked(["virt-customize", "--no-network", "--no-logfile",
                         "--key", "all:error", "--format", "raw", "-a", str(scratch),
                         "--hostname", config["hostname"],
                         "--upload", str(motd_path) + ":/etc/motd",
                         "--chmod", "0644:/etc/motd",
                         "--chown", "0:0:/etc/motd"])
            tracker.advance(3)
            run_checked(["virt-sysprep", "--no-network", "--key", "all:error",
                         "--format", "raw", "-a", str(scratch),
                         "--operations", SYSPREP_OPERATIONS])
            tracker.advance(4)
            first = config["first_boot"]
            seed, seed_manifest = nocloud.make_files(
                plan, config["hostname"], first["username"],
                first["ssh_public_key"], first["instance_id"], stage / "seed")
            iso_metadata = None
            if first["seed_iso"]:
                iso_metadata = nocloud.make_iso(seed, stage / "seed.iso")
            tracker.advance(5)
            name = GUEST_FORMATS[plan["format"]]
            staged_image = stage / name
            run_checked(["qemu-img", "convert", "-f", "raw", "-O", plan["format"],
                         str(scratch), str(staged_image)])
            staged_image.chmod(0o600)
            output_info = build_image.inspect_image(staged_image)
            if (output_info["format"] != plan["format"]
                    or output_info["virtual-size"] != original_info["virtual-size"]):
                raise ValueError("Converted customized disk metadata mismatch")
            verification = inspect_output(staged_image, raw_baseline,
                                          config["hostname"], config["motd"])
            tracker.advance(6)
            image_digest = sha256_file(staged_image)
            config_summary = {
                "schema_version": 1,
                "hostname": config["hostname"],
                "motd": config["motd"],
                "first_boot": {
                    "mode": "nocloud",
                    "username": first["username"],
                    "instance_id": first["instance_id"],
                    "ssh_public_key_sha256": hashlib.sha256(
                        nocloud.read_key(first["ssh_public_key"]).encode("utf-8")).hexdigest(),
                    "seed_iso": first["seed_iso"],
                }
            }
            summary_file = stage / "build-config.json"
            with summary_file.open("x", encoding="utf-8") as f:
                json.dump(config_summary, f, indent=2, ensure_ascii=False)
                f.write("\n")
            summary_file.chmod(0o600)
            manifest = {
                "schema_version": 1, "type": "ubuntu-customizer/rootfs-build-result",
                "source_sha256": plan["source"]["sha256"],
                "source_plan_architecture": plan.get("architecture"),
                "recipe_sha256": cfg_sha,
                "image_plan_sha256": hashlib.sha256(json.dumps(
                    plan, sort_keys=True, ensure_ascii=False,
                    separators=(",", ":")).encode("utf-8")).hexdigest(),
                "build_config": {"file": "build-config.json",
                                 "sha256": sha256_file(summary_file)},
                "output": {"file": name, "sha256": image_digest,
                           "bytes": staged_image.stat().st_size,
                           "format": plan["format"], "virtual_size": output_info["virtual-size"]},
                "seed": {"directory": "seed", "files": seed_manifest["files"],
                         "manifest_sha256": sha256_file(seed / "manifest.json"),
                         "iso": {"file": "seed.iso", **{k:v for k,v in iso_metadata.items() if k in ("sha256","bytes")}}
                         if iso_metadata else None},
                "guest_evidence": {"image_sha256": verification["source"]["sha256"],
                                   "observations": stable_guest(verification["observations"])},
                "operations": ["hostname", "motd", "sysprep:machine-id,ssh-hostkeys",
                               "nocloud-seed"],
                "boot_tested": False, "first_boot_confirmed": False,
                "warnings": ["Cloud-init/SSH regeneration are not proven until isolated boot",
                             "No package updates or vendor BSP integration performed",
                             "Image portability to physical devices is unverified"],
            }
            if output.exists() or output.is_symlink():
                raise ValueError("Output bundle already exists")
            created = False
            try:
                output.mkdir(mode=0o700)
                created = True
                os.link(staged_image, output / name)  # No overwrite.
                shutil.copytree(seed, output / "seed", symlinks=False)
                shutil.copy2(summary_file, output / "build-config.json")
                if iso_metadata:
                    os.link(stage / "seed.iso", output / "seed.iso")
                with (output / "build-manifest.json").open("x", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                (output / "build-manifest.json").chmod(0o600)
                verify_bundle(output)
            except BaseException:
                if created:
                    shutil.rmtree(output)
                raise
            tracker.advance(7)
            return output, manifest

def verify_bundle(path):
    bundle = Path(path).expanduser()
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("Build bundle must be a real directory")
    result = read_json_regular(bundle / "build-manifest.json")
    if result.get("type") != "ubuntu-customizer/rootfs-build-result" or result.get("schema_version") != 1:
        raise ValueError("Unsupported build manifest")
    configured = result.get("build_config", {})
    if not isinstance(configured, dict) or configured.get("file") != "build-config.json":
        raise ValueError("Missing sanitized build configuration manifest")
    config_file = bundle / "build-config.json"
    if (config_file.is_symlink() or not config_file.is_file()
            or sha256_file(config_file) != configured.get("sha256")):
        raise ValueError("Build configuration manifest checksum mismatch")
    info = result.get("output", {})
    if not isinstance(info, dict):
        raise ValueError("Invalid image manifest")
    name = info.get("file")
    if name not in GUEST_FORMATS.values():
        raise ValueError("Unexpected image name")
    image = build_image.safe_regular(bundle / name)
    if image.parent != bundle.resolve():
        raise ValueError("Image is outside output bundle")
    if sha256_file(image) != info.get("sha256") or image.stat().st_size != info.get("bytes"):
        raise ValueError("Output disk hash/size mismatch")
    image_info = build_image.inspect_image(image)
    if image_info.get("format") != info.get("format") or image_info.get("virtual-size") != info.get("virtual_size"):
        raise ValueError("Output disk header mismatch")
    seed = result.get("seed", {})
    if (not isinstance(seed, dict) or seed.get("directory") != "seed"
            or not isinstance(seed.get("files"), dict)):
        raise ValueError("Invalid NoCloud seed manifest")
    seed_folder = bundle / "seed"
    if seed_folder.is_symlink() or not seed_folder.is_dir():
        raise ValueError("NoCloud seed directory must not be a symbolic link")
    for file in ("user-data", "meta-data", "manifest.json"):
        item = (seed.get("files") or {}).get(file)
        if file == "manifest.json":
            # NoCloud manifest itself is not included in its files map.
            item = None
        p = bundle / "seed" / file
        if p.is_symlink() or not p.is_file():
            raise ValueError("Missing or unsafe seed artifact")
        if file == "manifest.json" and sha256_file(p) != seed.get("manifest_sha256"):
            raise ValueError("NoCloud manifest hash mismatch")
        if item and (sha256_file(p) != item["sha256"] or p.stat().st_size != item["bytes"]):
            raise ValueError("NoCloud artifact hash mismatch")
    iso = seed.get("iso")
    if iso:
        if not isinstance(iso, dict) or iso.get("file") != "seed.iso":
            raise ValueError("Unexpected or unsafe ISO artifact path")
        p = bundle / iso["file"]
        if (p.is_symlink() or not p.is_file() or sha256_file(p) != iso["sha256"]
                or p.stat().st_size != iso["bytes"]):
            raise ValueError("Seed ISO hash mismatch")
    return {"hash_verified": True, "boot_tested": False,
            "image_sha256": info["sha256"], "format": info["format"]}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plan", nargs="?", help="image-plan.json with verified compatibility")
    p.add_argument("--config", help="strict rootfs-config.json recipe")
    p.add_argument("--verify-bundle", help="verify existing bundle without writing it")
    p.add_argument("--output-dir", help="NEW directory for image, manifest and seed")
    p.add_argument("--approved", action="store_true", help="explicit offline customization approval")
    p.add_argument("--dry-run", action="store_true", help="validate and preview without building")
    args = p.parse_args(argv)
    try:
        if args.verify_bundle:
            if args.plan or args.config or args.output_dir or args.approved or args.dry_run:
                raise ValueError("Bundle verification cannot be combined with build options")
            print(json.dumps(verify_bundle(args.verify_bundle), ensure_ascii=False, indent=2))
            return 0
        if not args.plan or not args.config:
            raise ValueError("Plan and --config are required for dry-run/build")
        plan = read_json_regular(args.plan)
        config = read_json_regular(args.config, MAX_CONFIG)
        if args.dry_run:
            print(json.dumps(dry_run(plan, config), ensure_ascii=False, indent=2))
        else:
            if not args.output_dir:
                raise ValueError("Build mode requires --output-dir")
            bundle, _ = assemble(plan, config, args.output_dir, approved=args.approved)
            print(json.dumps({"bundle": str(bundle), **verify_bundle(bundle)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
