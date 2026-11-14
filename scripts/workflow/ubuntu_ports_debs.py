#!/usr/bin/env python3
"""Resolve and bundle SHA-256-verified official Ubuntu Ports ARM64 .deb packages.

Reads var/lib/dpkg/status from the pinned Ubuntu Base 24.04 ARM64 archive,
resolves transitive Pre-Depends + Depends from official ports.ubuntu.com
Packages.xz indexes, verifies every .deb Size + SHA-256 + ar header, and packs
a deterministic var/cache/uc-debs/*.deb archive under ./outputs/.
Never accesses host paths outside the active project or downloads without
explicit --network-approved consent.
"""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent


def _sibling(name):
    spec = importlib.util.spec_from_file_location("uc_ports_debs_" + name, HERE / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


workspace = _sibling("project_workspace")
baseline = _sibling("arm_baseline")

OFFICIAL_MIRROR = "https://ports.ubuntu.com/ubuntu-ports"
SUITES = ("noble", "noble-updates", "noble-security")
COMPONENTS = ("main", "universe")
ARCH = "arm64"
DEB_MAGIC = b"!<arch>\n"
MAX_INDEX_COMPRESSED_BYTES = 32 * 1024 * 1024
MAX_INDEX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_DEB_BYTES = 128 * 1024 * 1024
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
PKG_NAME_RE = re.compile(r"[a-z0-9][a-z0-9+.-]*\Z")
SAFE_DEB_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_~%-]*\.deb\Z")
DEP_ATOM_RE = re.compile(
    r"\A([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9-]+)?(?:\s*\(\s*(<<|<=|=|>=|>>|<|>)\s*([^\s)]+)\s*\))?\Z"
)

DEFAULT_PACKAGES = (
    "kmod",
    "iproute2",
    "iputils-ping",
    "net-tools",
    "isc-dhcp-client",
    "ethtool",
    "ca-certificates",
    "curl",
    "wget",
    "less",
    "nano",
    "vim-tiny",
    "file",
    "usbutils",
    "lsof",
    "psmisc",
    "bsdextrautils",
    "openssh-server",
    "wpasupplicant",
    "iw",
    "rfkill",
    "wireless-regdb",
)


def _char_order(ch):
    if ch == "~":
        return -1
    if ch is None:
        return 0
    if ch.isalpha():
        return ord(ch)
    return ord(ch) + 256


def _cmp_deb_part(a, b):
    ia = ib = 0
    na, nb = len(a), len(b)
    while ia < na or ib < nb:
        while (ia < na and not a[ia].isdigit()) or (ib < nb and not b[ib].isdigit()):
            ca = a[ia] if (ia < na and not a[ia].isdigit()) else None
            cb = b[ib] if (ib < nb and not b[ib].isdigit()) else None
            oa, ob = _char_order(ca), _char_order(cb)
            if oa != ob:
                return -1 if oa < ob else 1
            if ca is not None:
                ia += 1
            if cb is not None:
                ib += 1
        sa = ia
        while ia < na and a[ia].isdigit():
            ia += 1
        sb = ib
        while ib < nb and b[ib].isdigit():
            ib += 1
        va = int(a[sa:ia]) if ia > sa else 0
        vb = int(b[sb:ib]) if ib > sb else 0
        if va != vb:
            return -1 if va < vb else 1
    return 0


def _split_deb_version(ver):
    v = ver.strip()
    if ":" in v:
        ep_str, rest = v.split(":", 1)
        epoch = int(ep_str)
    else:
        epoch, rest = 0, v
    if "-" in rest:
        upstream, revision = rest.rsplit("-", 1)
    else:
        upstream, revision = rest, ""
    return epoch, upstream, revision


def compare_deb_versions(a, b):
    """Compare two Debian version strings; returns -1, 0, or +1."""
    ea, ua, ra = _split_deb_version(a)
    eb, ub, rb = _split_deb_version(b)
    if ea != eb:
        return -1 if ea < eb else 1
    c = _cmp_deb_part(ua, ub)
    if c != 0:
        return c
    return _cmp_deb_part(ra, rb)


def version_satisfies(candidate_version, op, required_version):
    if op is None:
        return True
    if candidate_version is None:
        return False
    c = compare_deb_versions(candidate_version, required_version)
    if op in ("<<", "<"):
        return c < 0
    if op == "<=":
        return c <= 0
    if op == "=":
        return c == 0
    if op == ">=":
        return c >= 0
    if op in (">>", ">"):
        return c > 0
    raise ValueError("Unsupported version operator: " + str(op))


def parse_control_stanzas(text):
    """Parse Debian RFC822-like control file into list of dict[str, str]."""
    stanzas = []
    cur = {}
    last_key = None
    for raw_line in text.splitlines():
        if not raw_line.strip():
            if cur:
                stanzas.append(cur)
                cur = {}
                last_key = None
            continue
        if raw_line[0] in (" ", "\t"):
            if last_key is not None:
                cur[last_key] += "\n" + raw_line.strip()
            continue
        if ":" not in raw_line:
            continue
        key, val = raw_line.split(":", 1)
        last_key = key.strip()
        cur[last_key] = val.strip()
    if cur:
        stanzas.append(cur)
    return stanzas


def parse_dep_clauses(field_value):
    """Parse Depends/Pre-Depends string into list of OR-clauses [(pkg, op, ver), ...]."""
    if not field_value:
        return []
    clauses = []
    for raw_clause in field_value.replace("\n", " ").split(","):
        clause = raw_clause.strip()
        if not clause:
            continue
        alts = []
        for raw_alt in clause.split("|"):
            alt = raw_alt.strip()
            if not alt:
                continue
            # Strip optional build/arch restriction brackets if present (none expected in binary Packages).
            if "[" in alt:
                alt = alt.split("[", 1)[0].strip()
            m = DEP_ATOM_RE.fullmatch(alt)
            if not m:
                raise ValueError("Unrecognized Debian dependency expression: " + alt)
            alts.append((m.group(1), m.group(2), m.group(3)))
        if alts:
            clauses.append(tuple(alts))
    return clauses


def parse_provides(field_value):
    """Parse Provides header into list of (virtual_name, provided_version_or_None)."""
    if not field_value:
        return []
    out = []
    for raw_item in field_value.replace("\n", " ").split(","):
        item = raw_item.strip()
        if not item:
            continue
        m = DEP_ATOM_RE.fullmatch(item)
        if not m:
            continue
        name, op, ver = m.group(1), m.group(2), m.group(3)
        out.append((name, ver if op == "=" else None))
    return out


def read_base_dpkg_status(base_archive_path, verify_pinned_sha=True):
    """Return (installed_versions, installed_provides) from Ubuntu Base archive."""
    archive = workspace.checked_input(base_archive_path, max_bytes=baseline.MAX_BYTES)
    if verify_pinned_sha and baseline.sha256_file(archive) != baseline.BASELINE["sha256"]:
        raise ValueError("Base archive does not match pinned official Ubuntu Base SHA-256")
    status_text = None
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            clean = member.name.lstrip("./")
            if clean == "var/lib/dpkg/status" and member.isfile():
                stream = tf.extractfile(member)
                if stream is not None:
                    status_text = stream.read(16 * 1024 * 1024).decode("utf-8", "strict")
                break
    if status_text is None:
        raise ValueError("var/lib/dpkg/status not found in Ubuntu Base archive")
    installed = {}
    provides = {}
    for st in parse_control_stanzas(status_text):
        pkg = st.get("Package", "")
        ver = st.get("Version", "")
        status = st.get("Status", "")
        if not pkg or not ver or "installed" not in status.split():
            continue
        installed[pkg] = ver
        for virt_name, virt_ver in parse_provides(st.get("Provides", "")):
            provides.setdefault(virt_name, []).append((pkg, virt_ver))
    return installed, provides


def _decompress_lzma_bounded(data, limit=MAX_INDEX_EXPANDED_BYTES):
    dec = lzma.LZMADecompressor()
    out = bytearray()
    mv = memoryview(data)
    offset = 0
    while offset < len(mv):
        chunk = dec.decompress(mv[offset:offset + 65536], max_length=1024 * 1024)
        out.extend(chunk)
        if len(out) > limit:
            raise ValueError("Packages.xz expanded size exceeds safety limit")
        if dec.needs_input:
            offset += 65536
        elif dec.eof:
            offset += 65536 - len(dec.unused_data)
            dec = lzma.LZMADecompressor()
    return bytes(out)


def _http_get_bounded(url, max_bytes, opener=urllib.request.urlopen, ca_bundle=None):
    if not url.startswith(OFFICIAL_MIRROR + "/"):
        raise ValueError("Refusing non-official Ubuntu Ports URL: " + url)
    req = urllib.request.Request(url, headers={"User-Agent": "ubuntu-customizer/1.0"})
    out = bytearray()
    kwargs = {"timeout": 60}
    if opener is urllib.request.urlopen:
        kwargs["context"] = baseline._tls_context(ca_bundle)
    with opener(req, **kwargs) as resp:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > max_bytes:
                raise ValueError("Downloaded payload exceeds safety limit: " + url)
    return bytes(out)


def load_package_index(cache_dir, suites=SUITES, components=COMPONENTS,
                       network_approved=False, refresh_indexes=False,
                       opener=urllib.request.urlopen, ca_bundle=None):
    """Load and merge Packages.xz stanzas, keeping the newest candidate per package."""
    index_dir = cache_dir / "indexes"
    index_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    available = {}
    provides = {}
    index_records = []
    for suite in suites:
        for comp in components:
            fname = f"{suite}_{comp}_{ARCH}_Packages.xz"
            local_xz = index_dir / fname
            url = f"{OFFICIAL_MIRROR}/dists/{suite}/{comp}/binary-{ARCH}/Packages.xz"
            if refresh_indexes or not local_xz.is_file():
                if not network_approved:
                    raise ValueError("Network download approval required (--network-approved)")
                raw_xz = _http_get_bounded(url, MAX_INDEX_COMPRESSED_BYTES,
                                           opener=opener, ca_bundle=ca_bundle)
                tmp = index_dir / (fname + ".part")
                tmp.write_bytes(raw_xz)
                tmp.chmod(0o600)
                tmp.replace(local_xz)
            else:
                raw_xz = workspace.checked_input(local_xz, max_bytes=MAX_INDEX_COMPRESSED_BYTES).read_bytes()
            index_records.append({
                "suite": suite,
                "component": comp,
                "url": url,
                "sha256": hashlib.sha256(raw_xz).hexdigest(),
                "bytes": len(raw_xz),
            })
            text = _decompress_lzma_bounded(raw_xz).decode("utf-8", "replace")
            for st in parse_control_stanzas(text):
                pkg = st.get("Package", "")
                ver = st.get("Version", "")
                rel_file = st.get("Filename", "")
                sha = st.get("SHA256", "").lower()
                size_str = st.get("Size", "")
                arch = st.get("Architecture", "")
                if (not PKG_NAME_RE.fullmatch(pkg) or not ver or arch not in (ARCH, "all")
                        or not re.fullmatch(r"[0-9a-f]{64}", sha) or not size_str.isdigit()):
                    continue
                posix_rel = PurePosixPath(rel_file)
                if (posix_rel.is_absolute() or ".." in posix_rel.parts
                        or not rel_file.startswith("pool/")
                        or not SAFE_DEB_FILENAME_RE.fullmatch(posix_rel.name)):
                    continue
                prev = available.get(pkg)
                if prev is not None and compare_deb_versions(prev["version"], ver) >= 0:
                    continue
                available[pkg] = {
                    "name": pkg,
                    "version": ver,
                    "architecture": arch,
                    "suite": suite,
                    "component": comp,
                    "filename": rel_file,
                    "deb_basename": posix_rel.name,
                    "size": int(size_str),
                    "sha256": sha,
                    "pre_depends": st.get("Pre-Depends", ""),
                    "depends": st.get("Depends", ""),
                    "provides": st.get("Provides", ""),
                }
    for pkg_name, meta in sorted(available.items()):
        for virt_name, virt_ver in parse_provides(meta["provides"]):
            provides.setdefault(virt_name, []).append((pkg_name, virt_ver))
    return available, provides, index_records


def _satisfied_by(pkg_name, op, req_ver, versions_map, provides_map):
    if pkg_name in versions_map and version_satisfies(versions_map[pkg_name], op, req_ver):
        return True
    for _, virt_ver in provides_map.get(pkg_name, ()):
        if op is None or (virt_ver is not None and version_satisfies(virt_ver, op, req_ver)):
            return True
    return False


def resolve_closure(requested_packages, installed, installed_provides, available, available_provides):
    """Resolve deterministic transitive Pre-Depends + Depends closure."""
    selected = {}
    selected_versions = {}
    selected_provides = {}
    queue = []

    def select_pkg(pkg_name):
        if pkg_name in selected:
            return
        meta = available[pkg_name]
        selected[pkg_name] = meta
        selected_versions[pkg_name] = meta["version"]
        for virt_name, virt_ver in parse_provides(meta["provides"]):
            selected_provides.setdefault(virt_name, []).append((pkg_name, virt_ver))
        for field in (meta["pre_depends"], meta["depends"]):
            queue.extend(parse_dep_clauses(field))

    for root_pkg in requested_packages:
        if not PKG_NAME_RE.fullmatch(root_pkg):
            raise ValueError("Invalid package name: " + repr(root_pkg))
        if root_pkg not in available:
            if root_pkg in installed:
                continue
            raise ValueError("Requested package not found in Ubuntu Ports index: " + root_pkg)
        select_pkg(root_pkg)

    while queue:
        clause = queue.pop(0)
        # Note: if a package is being upgraded in selected_versions, prefer selected_versions
        # over an older base installed version; otherwise check installed_versions too.
        effective_installed = {k: v for k, v in installed.items() if k not in selected_versions}
        if any(
            _satisfied_by(name, op, ver, selected_versions, selected_provides)
            or _satisfied_by(name, op, ver, effective_installed, installed_provides)
            for name, op, ver in clause
        ):
            continue
        chosen = None
        for name, op, ver in clause:
            cand = available.get(name)
            if cand is not None and version_satisfies(cand["version"], op, ver):
                chosen = name
                break
            for prov_pkg, virt_ver in available_provides.get(name, ()):
                if op is None or (virt_ver is not None and version_satisfies(virt_ver, op, ver)):
                    chosen = prov_pkg
                    break
            if chosen is not None:
                break
        if chosen is None:
            expr = " | ".join(
                f"{n} ({o} {v})" if o else n for n, o, v in clause
            )
            raise ValueError("Unsatisfied Debian dependency clause: " + expr)
        select_pkg(chosen)

    return [selected[k] for k in sorted(selected)]


def build_deb_bundle(bundle_output, report_output, *,
                     packages=DEFAULT_PACKAGES,
                     base_archive="outputs/baselines/ubuntu-base-24.04.5-base-arm64.tar.gz",
                     cache_dir="outputs/ubuntu-ports-cache/noble-arm64",
                     verify_pinned_base=True,
                     network_approved=False,
                     refresh_indexes=False,
                     opener=urllib.request.urlopen,
                     ca_bundle=None):
    """Resolve, verify/fetch .debs, and write deterministic var/cache/uc-debs tar.gz."""
    out_tar = workspace.checked_output(bundle_output)
    out_report = workspace.checked_output(report_output)
    if out_tar.exists() or out_tar.is_symlink() or out_report.exists() or out_report.is_symlink():
        raise ValueError("Bundle and report paths must be new files under outputs")
    cache_root = workspace.checked_output(cache_dir)
    pool_dir = cache_root / "pool"
    pool_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    installed, installed_provides = read_base_dpkg_status(
        base_archive, verify_pinned_sha=verify_pinned_base)
    available, available_provides, index_records = load_package_index(
        cache_root, network_approved=network_approved,
        refresh_indexes=refresh_indexes, opener=opener, ca_bundle=ca_bundle)
    resolved = resolve_closure(
        packages, installed, installed_provides, available, available_provides)
    if not resolved:
        raise ValueError("Resolved package set is empty")

    # Guard against duplicate .deb basenames across packages.
    seen_basenames = set()
    deb_blobs = []
    total_expanded = 0
    for meta in resolved:
        bname = meta["deb_basename"]
        if bname in seen_basenames:
            raise ValueError("Duplicate .deb basename in closure: " + bname)
        seen_basenames.add(bname)
        if meta["size"] <= 0 or meta["size"] > MAX_DEB_BYTES:
            raise ValueError("Package size outside safety bounds: " + bname)
        total_expanded += meta["size"]
        if total_expanded > MAX_BUNDLE_BYTES:
            raise ValueError("Total .deb closure size exceeds bundle limit")

        cached_deb = pool_dir / bname
        data = None
        if cached_deb.is_file() and not cached_deb.is_symlink():
            candidate_bytes = cached_deb.read_bytes()
            if (len(candidate_bytes) == meta["size"]
                    and hashlib.sha256(candidate_bytes).hexdigest() == meta["sha256"]
                    and candidate_bytes[:8] == DEB_MAGIC):
                data = candidate_bytes
        if data is None:
            if not network_approved:
                raise ValueError("Network download approval required for missing .deb: " + bname)
            url = f"{OFFICIAL_MIRROR}/{meta['filename']}"
            fetched = _http_get_bounded(url, meta["size"] + 1024,
                                        opener=opener, ca_bundle=ca_bundle)
            if len(fetched) != meta["size"]:
                raise ValueError(f"Downloaded size mismatch for {bname}: {len(fetched)} != {meta['size']}")
            actual_sha = hashlib.sha256(fetched).hexdigest()
            if actual_sha != meta["sha256"]:
                raise ValueError(f"Downloaded SHA-256 mismatch for {bname}: {actual_sha} != {meta['sha256']}")
            if fetched[:8] != DEB_MAGIC:
                raise ValueError("Downloaded file is not a valid Debian ar archive: " + bname)
            part = pool_dir / (bname + ".part")
            part.write_bytes(fetched)
            part.chmod(0o600)
            part.replace(cached_deb)
            data = fetched
        deb_blobs.append((meta, data))

    tar_buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=tar_buf, mtime=0) as gz:
        with tarfile.open(mode="w", fileobj=gz, format=tarfile.PAX_FORMAT) as tar:
            for dname in ("var", "var/cache", "var/cache/uc-debs"):
                info = tarfile.TarInfo(dname)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info)
            for meta, payload in deb_blobs:
                info = tarfile.TarInfo("var/cache/uc-debs/" + meta["deb_basename"])
                info.type = tarfile.REGTYPE
                info.size = len(payload)
                info.mode = 0o644
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(payload))

    bundle_bytes = tar_buf.getvalue()
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    out_tar.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    out_report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with out_tar.open("xb") as f:
        f.write(bundle_bytes)
    out_tar.chmod(0o600)

    report = {
        "schema_version": 1,
        "type": "ubuntu-customizer/ubuntu-ports-deb-bundle",
        "mirror": OFFICIAL_MIRROR,
        "architecture": ARCH,
        "suites": list(suites_used := sorted({m["suite"] for m, _ in deb_blobs})),
        "requested_packages": list(packages),
        "resolved_package_count": len(deb_blobs),
        "expanded_deb_bytes": total_expanded,
        "bundle": str(out_tar.relative_to(workspace.project_root())),
        "bundle_sha256": bundle_sha,
        "bundle_bytes": len(bundle_bytes),
        "indexes": index_records,
        "packages": [
            {
                "name": m["name"],
                "version": m["version"],
                "architecture": m["architecture"],
                "suite": m["suite"],
                "component": m["component"],
                "deb_basename": m["deb_basename"],
                "url": f"{OFFICIAL_MIRROR}/{m['filename']}",
                "size": m["size"],
                "sha256": m["sha256"],
            }
            for m, _ in deb_blobs
        ],
    }
    with out_report.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    out_report.chmod(0o600)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New outputs/.../*.tar.gz .deb bundle")
    parser.add_argument("--report", required=True, help="New outputs/.../*.json provenance manifest")
    parser.add_argument("--base-archive", default="outputs/baselines/ubuntu-base-24.04.5-base-arm64.tar.gz")
    parser.add_argument("--cache-dir", default="outputs/ubuntu-ports-cache/noble-arm64")
    parser.add_argument("--packages", nargs="+", default=list(DEFAULT_PACKAGES))
    parser.add_argument("--network-approved", action="store_true")
    parser.add_argument("--refresh-indexes", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_deb_bundle(
            args.output,
            args.report,
            packages=tuple(args.packages),
            base_archive=args.base_archive,
            cache_dir=args.cache_dir,
            network_approved=args.network_approved,
            refresh_indexes=args.refresh_indexes,
        )
        print(json.dumps({
            "bundle": report["bundle"],
            "bundle_sha256": report["bundle_sha256"],
            "bundle_bytes": report["bundle_bytes"],
            "resolved_package_count": report["resolved_package_count"],
            "expanded_deb_bytes": report["expanded_deb_bytes"],
            "suites": report["suites"],
        }, indent=2))
        return 0
    except (OSError, ValueError, lzma.LZMAError, tarfile.TarError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
