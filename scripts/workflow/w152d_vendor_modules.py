#!/usr/bin/env python3
"""Extract and verify W152D Linux 5.4.210 vendor_boot kernel modules into a driver overlay.

Reads only a project-local Android vendor_boot v3/v4 image, validates every .ko
ELF64 ARM64 relocatable header and exact vermagic before staging into a
deterministic usr/lib/modules/<release>/ tar.gz archive under ./outputs/.
Never executes target commands or opens host paths outside the active project.
"""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tarfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "uc_workspace_w152d_vendor_modules", HERE / "project_workspace.py")
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)

VNDRBOOT_MAGIC = b"VNDRBOOT"
MAX_VENDOR_BOOT_BYTES = 64 * 1024 * 1024
MAX_RAMDISK_BYTES = 128 * 1024 * 1024
EXPECTED_RELEASE = "5.4.210"
EXPECTED_VERMAGIC = "5.4.210 SMP preempt mod_unload modversions aarch64"
SAFE_KO_NAME = re.compile(r"[A-Za-z0-9_.-]+\.ko\Z")
SAFE_FW_NAME = re.compile(r"[A-Za-z0-9_.-]+\Z")
MAX_EXTRA_BUNDLE_BYTES = 64 * 1024 * 1024

# Topologically ordered W152D S905L4 (gxlx4) Ethernet MAC + MDIO + internal PHY stack.
ETH0_MODULES = (
    "pps_core.ko",
    "ptp.ko",
    "phylink.ko",
    "mdio_mux.ko",
    "aml_mailbox.ko",
    "aml_mdio_g12a.ko",
    "meson-gxl.ko",
    "stmmac.ko",
    "stmmac-platform.ko",
    "dwmac-meson8b.ko",
    "dwmac-dwc-qos-eth.ko",
)

# Topologically ordered W152D Unisoc UWE5621 SDIO Wi-Fi + Bluetooth stack.
WIFI_MODULES = (
    "wifi_comm.ko",
    "uwe5621_bsp_sdio.ko",
    "sprdbt_tty.ko",
    "sprdwl_ng.ko",
)


def _decompress_gzip_bounded(payload, limit=MAX_RAMDISK_BYTES):
    out = bytearray()
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as gz:
        while True:
            chunk = gz.read(1024 * 1024)
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > limit:
                raise ValueError("Decompressed vendor ramdisk exceeds safety limit")
    return bytes(out)


def extract_vendor_ramdisk(blob):
    """Parse Android vendor_boot v3/v4 header and return uncompressed ramdisk bytes."""
    if len(blob) < 2112 or blob[:8] != VNDRBOOT_MAGIC:
        raise ValueError("Not a valid Android VNDRBOOT image")
    hdr_ver, page_sz, _, _, vr_sz = struct.unpack_from("<5I", blob, 8)
    if hdr_ver not in (3, 4) or page_sz < 2048 or (page_sz & (page_sz - 1)) != 0:
        raise ValueError("Unsupported vendor_boot header version or page size")
    hdr_bytes = 2112 if hdr_ver == 3 else 2128
    ramdisk_offset = ((hdr_bytes + page_sz - 1) // page_sz) * page_sz
    if vr_sz == 0 or ramdisk_offset + vr_sz > len(blob):
        raise ValueError("Vendor ramdisk bounds are invalid")
    compressed = blob[ramdisk_offset:ramdisk_offset + vr_sz]
    if compressed[:2] != b"\x1f\x8b":
        raise ValueError("Unsupported vendor ramdisk compression (expected gzip)")
    return _decompress_gzip_bounded(compressed)


def parse_newc_cpio(raw):
    """Parse SVR4 newc/crc CPIO into {normalized_path: (mode, payload_bytes)}."""
    pos = 0
    files = {}
    while pos + 110 <= len(raw):
        magic = raw[pos:pos + 6]
        if magic not in (b"070701", b"070702"):
            raise ValueError("Unexpected CPIO header magic")
        mode = int(raw[pos + 14:pos + 22], 16)
        filesize = int(raw[pos + 54:pos + 62], 16)
        namesize = int(raw[pos + 94:pos + 102], 16)
        name_start = pos + 110
        if namesize < 1 or name_start + namesize > len(raw):
            raise ValueError("Truncated CPIO entry name")
        raw_name = raw[name_start:name_start + namesize - 1]
        if b"\x00" in raw_name or b"\\" in raw_name:
            raise ValueError("Unsafe CPIO entry name")
        name = raw_name.decode("utf-8")
        data_start = (name_start + namesize + 3) & ~3
        if data_start + filesize > len(raw):
            raise ValueError("Truncated CPIO entry data")
        data = raw[data_start:data_start + filesize]
        pos = (data_start + filesize + 3) & ~3
        if name == "TRAILER!!!":
            break
        posix = PurePosixPath(name)
        if posix.is_absolute() or ".." in posix.parts:
            raise ValueError("CPIO entry escapes root")
        clean = "/".join(p for p in posix.parts if p not in ("", "."))
        if not clean:
            continue
        files[clean] = (mode, data)
    return files


def inspect_ko(name, data, expected_vermagic=EXPECTED_VERMAGIC):
    """Validate ARM64 ELF64 relocatable module and return (vermagic, depends_tuple)."""
    if not SAFE_KO_NAME.fullmatch(name):
        raise ValueError("Unsafe kernel module filename: " + name)
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Module is not 64-bit little-endian ELF: " + name)
    e_type, e_machine = struct.unpack_from("<HH", data, 16)
    if e_type != 1 or e_machine != 183:
        raise ValueError("Module is not an ARM64 ET_REL object: " + name)
    vm_match = re.search(rb"(?:^|\x00)vermagic=([^\x00]+)\x00", data)
    if not vm_match:
        raise ValueError("Module missing vermagic metadata: " + name)
    vermagic = vm_match.group(1).decode("ascii", "strict")
    if vermagic != expected_vermagic:
        raise ValueError(f"Module vermagic mismatch in {name}: {vermagic!r}")
    dep_match = re.search(rb"(?:^|\x00)depends=([^\x00]*)\x00", data)
    depends = tuple(p for p in (dep_match.group(1).decode("ascii", "strict").split(",")
                                if dep_match else []) if p)
    return vermagic, depends


def _normalize_modules_dep(text):
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        lhs, rhs = line.split(":", 1)
        target = PurePosixPath(lhs.strip()).name
        deps = [PurePosixPath(tok).name for tok in rhs.split() if tok.strip()]
        lines.append(target + ":" + (" " + " ".join(deps) if deps else ""))
    return "\n".join(lines) + ("\n" if lines else "")


WIFI_IMPLIED_DEPS = {
    "wifi_comm.ko": (),
    "uwe5621_bsp_sdio.ko": ("wifi_comm.ko",),
    "sprdbt_tty.ko": ("uwe5621_bsp_sdio.ko", "wifi_comm.ko"),
    "sprdwl_ng.ko": ("uwe5621_bsp_sdio.ko", "wifi_comm.ko"),
}


def _verify_module_order(order_list, ko_depends_by_stem, modules_dep_text, label="eth0"):
    seen_stems = set()
    seen_files = set()
    dep_map = {}
    for line in modules_dep_text.splitlines():
        if ":" not in line:
            continue
        lhs, rhs = line.split(":", 1)
        dep_map[lhs.strip()] = tuple(rhs.split())
    for filename in order_list:
        stem = filename[:-3].replace("-", "_")
        if stem not in ko_depends_by_stem:
            raise ValueError(f"Missing required W152D {label} module: {filename}")
        for dep in ko_depends_by_stem[stem]:
            dep_norm = dep.replace("-", "_")
            if dep_norm not in seen_stems:
                raise ValueError(f"Module {filename} precedes dependency {dep}")
        for dep_file in dep_map.get(filename, ()):
            if dep_file not in seen_files:
                raise ValueError(f"modules.dep order violation: {filename} precedes {dep_file}")
        seen_stems.add(stem)
        seen_files.add(filename)


def _read_extra_bundle(bundle_path, expected_sha256, release, expected_vermagic):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256 or ""):
        raise ValueError("Extra driver bundle requires a 64-hex SHA-256")
    src = workspace.checked_input(bundle_path, max_bytes=MAX_EXTRA_BUNDLE_BYTES)
    raw = src.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha256.lower():
        raise ValueError("Extra driver bundle SHA-256 mismatch")
    extra_modules = {}
    extra_deps = {}
    firmware = {}
    mod_prefix = f"usr/lib/modules/{release}/"
    fw_prefix = "usr/lib/firmware/"
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for member in tf:
            if "\\" in member.name or "\x00" in member.name:
                raise ValueError("Unsafe extra bundle member path")
            posix = PurePosixPath(member.name)
            if posix.is_absolute() or ".." in posix.parts:
                raise ValueError("Extra bundle member escapes root")
            clean = "/".join(p for p in posix.parts if p not in ("", "."))
            if not clean or member.isdir():
                continue
            # Ignore runtime /vendor compatibility symlinks archived during extraction;
            # driver overlays must contain only regular files under usr/lib/{modules,firmware}.
            if clean.startswith("vendor/") and member.issym():
                continue
            if not member.isfile():
                raise ValueError("Extra bundle contains unsupported non-regular entry: " + clean)
            if member.size < 0 or total + member.size > MAX_EXTRA_BUNDLE_BYTES:
                raise ValueError("Extra bundle expanded payload exceeds limit")
            total += member.size
            stream = tf.extractfile(member)
            if stream is None:
                raise ValueError("Missing payload in extra bundle: " + clean)
            payload = stream.read()
            if clean.startswith(mod_prefix):
                rel = clean[len(mod_prefix):]
                if "/" in rel or not rel.endswith(".ko"):
                    raise ValueError("Unexpected extra module path: " + clean)
                _, deps = inspect_ko(rel, payload, expected_vermagic=expected_vermagic)
                extra_modules[rel] = payload
                extra_deps[rel[:-3].replace("-", "_")] = deps
            elif clean.startswith(fw_prefix):
                rel = clean[len(fw_prefix):]
                if "/" in rel or not SAFE_FW_NAME.fullmatch(rel):
                    raise ValueError("Unsafe extra firmware filename: " + clean)
                firmware[rel] = payload
            else:
                raise ValueError("Extra bundle member outside modules/firmware: " + clean)
    return {
        "source": str(src.relative_to(workspace.project_root())),
        "sha256": actual_sha,
        "bytes": len(raw),
        "modules": extra_modules,
        "depends_by_stem": extra_deps,
        "firmware": firmware,
    }


def build_overlay(source_path, overlay_output, report_output,
                  release=EXPECTED_RELEASE, expected_vermagic=EXPECTED_VERMAGIC,
                  extra_bundle=None, extra_bundle_sha256=None):
    """Build deterministic driver overlay tar.gz and provenance report under outputs."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9_.-]*\Z", release):
        raise ValueError("Invalid kernel release identifier")
    if bool(extra_bundle) != bool(extra_bundle_sha256):
        raise ValueError("Extra bundle path and SHA-256 must be supplied together")
    src = workspace.checked_input(source_path, max_bytes=MAX_VENDOR_BOOT_BYTES)
    out_tar = workspace.checked_output(overlay_output)
    out_report = workspace.checked_output(report_output)
    if out_tar.exists() or out_tar.is_symlink() or out_report.exists() or out_report.is_symlink():
        raise ValueError("Overlay and report paths must be new files under outputs")

    extra = (_read_extra_bundle(extra_bundle, extra_bundle_sha256, release, expected_vermagic)
             if extra_bundle is not None else None)

    blob = src.read_bytes()
    source_sha = hashlib.sha256(blob).hexdigest()
    ramdisk = extract_vendor_ramdisk(blob)
    cpio_entries = parse_newc_cpio(ramdisk)

    modules = {}
    depends_by_stem = {}
    meta_files = {}
    for path, (mode, payload) in sorted(cpio_entries.items()):
        if not path.startswith("lib/modules/"):
            continue
        # S_IFREG is 0o100000; reject symlinks, device nodes, or nested subdirs.
        if (mode & 0o170000) != 0o100000:
            raise ValueError("Unsupported non-regular file in lib/modules: " + path)
        rel = path[len("lib/modules/"):]
        if "/" in rel:
            raise ValueError("Unexpected nested path in vendor_boot modules: " + path)
        if rel.endswith(".ko"):
            _, deps = inspect_ko(rel, payload, expected_vermagic=expected_vermagic)
            modules[rel] = payload
            depends_by_stem[rel[:-3].replace("-", "_")] = deps
        elif rel in ("modules.dep", "modules.load", "modules.alias", "modules.softdep"):
            text = payload.decode("utf-8", "strict")
            meta_files[rel] = (_normalize_modules_dep(text).encode("utf-8")
                               if rel == "modules.dep" else text.encode("utf-8"))

    if not modules:
        raise ValueError("No verified kernel modules found in vendor_boot")

    firmware = {}
    wifi_load_order = []
    if extra is not None:
        for ko_name, ko_bytes in sorted(extra["modules"].items()):
            if ko_name in modules and modules[ko_name] != ko_bytes:
                raise ValueError("Conflicting module in extra bundle: " + ko_name)
            modules[ko_name] = ko_bytes
        depends_by_stem.update(extra["depends_by_stem"])
        firmware.update(extra["firmware"])

        file_for_stem = {name[:-3].replace("-", "_"): name for name in modules}
        dep_lines = [ln for ln in meta_files.get("modules.dep", b"").decode("utf-8").splitlines() if ln]
        existing_lhs = {ln.split(":", 1)[0].strip() for ln in dep_lines if ":" in ln}
        for ko_name in WIFI_MODULES:
            if ko_name not in extra["modules"]:
                raise ValueError("Missing required W152D Wi-Fi module in extra bundle: " + ko_name)
            stem = ko_name[:-3].replace("-", "_")
            explicit = [file_for_stem[d.replace("-", "_")]
                        for d in depends_by_stem.get(stem, ())
                        if d.replace("-", "_") in file_for_stem]
            combined_deps = list(dict.fromkeys(list(WIFI_IMPLIED_DEPS.get(ko_name, ())) + explicit))
            if ko_name not in existing_lhs:
                dep_lines.append(ko_name + ":" + (" " + " ".join(combined_deps) if combined_deps else ""))
        meta_files["modules.dep"] = ("\n".join(dep_lines) + ("\n" if dep_lines else "")).encode("utf-8")
        _verify_module_order(WIFI_MODULES, depends_by_stem,
                             meta_files["modules.dep"].decode("utf-8"), label="wifi")
        meta_files["w152d-wifi.load"] = ("\n".join(WIFI_MODULES) + "\n").encode("ascii")
        wifi_load_order = list(WIFI_MODULES)

    _verify_module_order(ETH0_MODULES, depends_by_stem,
                         meta_files.get("modules.dep", b"").decode("utf-8"), label="eth0")
    meta_files["w152d-eth0.load"] = ("\n".join(ETH0_MODULES) + "\n").encode("ascii")

    prefix = f"usr/lib/modules/{release}"
    dirs = ["usr", "usr/lib", "usr/lib/modules", prefix]
    if firmware:
        dirs.append("usr/lib/firmware")
    tar_buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=tar_buf, mtime=0) as gz:
        with tarfile.open(mode="w", fileobj=gz, format=tarfile.PAX_FORMAT) as tar:
            for dname in dirs:
                info = tarfile.TarInfo(dname)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info)
            for fname, payload in sorted({**modules, **meta_files}.items()):
                info = tarfile.TarInfo(f"{prefix}/{fname}")
                info.type = tarfile.REGTYPE
                info.size = len(payload)
                info.mode = 0o644
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(payload))
            for fname, payload in sorted(firmware.items()):
                info = tarfile.TarInfo(f"usr/lib/firmware/{fname}")
                info.type = tarfile.REGTYPE
                info.size = len(payload)
                info.mode = 0o644
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(payload))

    archive_bytes = tar_buf.getvalue()
    overlay_sha = hashlib.sha256(archive_bytes).hexdigest()
    out_tar.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    out_report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with out_tar.open("xb") as f:
        f.write(archive_bytes)
    out_tar.chmod(0o600)

    report = {
        "schema_version": 1,
        "type": "ubuntu-customizer/w152d-driver-overlay",
        "source_vendor_boot": str(src.relative_to(workspace.project_root())),
        "source_vendor_boot_sha256": source_sha,
        "extra_bundle": ({"file": extra["source"], "sha256": extra["sha256"],
                          "bytes": extra["bytes"]} if extra is not None else None),
        "overlay": str(out_tar.relative_to(workspace.project_root())),
        "overlay_sha256": overlay_sha,
        "overlay_bytes": len(archive_bytes),
        "kernel_release": release,
        "verified_vermagic": expected_vermagic,
        "module_count": len(modules),
        "firmware_count": len(firmware),
        "eth0_load_order": list(ETH0_MODULES),
        "wifi_load_order": wifi_load_order,
        "modules": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(modules.items())
        },
        "firmware": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(firmware.items())
        },
    }
    with out_report.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    out_report.chmod(0o600)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="outputs/w152d-uboot-capture-01/vendor-boot-a.bin")
    parser.add_argument("--extra-bundle", help="Optional verified tar.gz of out-of-ramdisk modules/firmware")
    parser.add_argument("--extra-bundle-sha256", help="Trusted SHA-256 for --extra-bundle")
    parser.add_argument("--output", required=True, help="New outputs/.../*.tar.gz overlay archive")
    parser.add_argument("--report", required=True, help="New outputs/.../*.json provenance manifest")
    parser.add_argument("--release", default=EXPECTED_RELEASE)
    parser.add_argument("--vermagic", default=EXPECTED_VERMAGIC)
    args = parser.parse_args(argv)
    try:
        report = build_overlay(args.source, args.output, args.report,
                               release=args.release, expected_vermagic=args.vermagic,
                               extra_bundle=args.extra_bundle,
                               extra_bundle_sha256=args.extra_bundle_sha256)
        print(json.dumps({
            "overlay": report["overlay"],
            "overlay_sha256": report["overlay_sha256"],
            "overlay_bytes": report["overlay_bytes"],
            "module_count": report["module_count"],
            "firmware_count": report["firmware_count"],
            "verified_vermagic": report["verified_vermagic"],
            "eth0_load_order": report["eth0_load_order"],
            "wifi_load_order": report["wifi_load_order"],
        }, indent=2))
        return 0
    except (OSError, ValueError, EOFError, tarfile.TarError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
