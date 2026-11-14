"""Unit tests for W152D vendor_boot module extraction and verification."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import struct
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MOD_SPEC = importlib.util.spec_from_file_location(
    "w152d_vendor_modules", ROOT / "scripts/workflow/w152d_vendor_modules.py")
vm = importlib.util.module_from_spec(MOD_SPEC)
MOD_SPEC.loader.exec_module(vm)

INIT_SPEC = importlib.util.spec_from_file_location(
    "w152d_serial_init", ROOT / "scripts/workflow/w152d_serial_init.py")
sinit = importlib.util.module_from_spec(INIT_SPEC)
INIT_SPEC.loader.exec_module(sinit)


def _fake_elf64_ko(vermagic=vm.EXPECTED_VERMAGIC, depends=""):
    # Minimal 64-byte ELF64 little-endian ET_REL (1), EM_AARCH64 (183) + modinfo.
    hdr = bytearray(64)
    hdr[0:6] = b"\x7fELF\x02\x01"
    hdr[6] = 1
    struct.pack_into("<HH", hdr, 16, 1, 183)
    modinfo = (
        b"\x00vermagic=" + vermagic.encode("ascii") + b"\x00"
        + b"depends=" + depends.encode("ascii") + b"\x00"
    )
    return bytes(hdr) + modinfo


def _cpio_entry(name, payload, mode=0o100644):
    raw_name = name.encode("utf-8") + b"\x00"
    header = (
        b"070701"
        + f"{0:08x}{mode:08x}{0:08x}{0:08x}{1:08x}{0:08x}"
        f"{len(payload):08x}{0:08x}{0:08x}{0:08x}{0:08x}"
        f"{len(raw_name):08x}{0:08x}".encode("ascii")
    )
    out = bytearray(header + raw_name)
    while len(out) % 4:
        out.append(0)
    out.extend(payload)
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def _fake_vendor_boot(entries):
    cpio = bytearray()
    for name, (mode, data) in entries.items():
        cpio.extend(_cpio_entry(name, data, mode=mode))
    cpio.extend(_cpio_entry("TRAILER!!!", b"", mode=0))
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(bytes(cpio))
    gz_bytes = buf.getvalue()
    page_sz = 2048
    header = bytearray(4096)
    header[0:8] = b"VNDRBOOT"
    struct.pack_into("<5I", header, 8, 3, page_sz, 0, 0, len(gz_bytes))
    return bytes(header) + gz_bytes


class VendorModulesTests(unittest.TestCase):
    def _complete_eth0_entries(self, bad_vermagic=None):
        deps_for = {
            "pps_core.ko": "",
            "ptp.ko": "pps_core",
            "phylink.ko": "",
            "mdio_mux.ko": "",
            "aml_mailbox.ko": "",
            "aml_mdio_g12a.ko": "mdio_mux",
            "meson-gxl.ko": "aml_mdio_g12a",
            "stmmac.ko": "ptp,phylink",
            "stmmac-platform.ko": "stmmac",
            "dwmac-meson8b.ko": "aml_mdio_g12a,stmmac,stmmac-platform,aml_mailbox",
            "dwmac-dwc-qos-eth.ko": "stmmac-platform,stmmac",
        }
        entries = {}
        dep_lines = []
        for ko, dep in deps_for.items():
            ver = bad_vermagic if (bad_vermagic and ko == "stmmac.ko") else vm.EXPECTED_VERMAGIC
            entries["lib/modules/" + ko] = (0o100644, _fake_elf64_ko(vermagic=ver, depends=dep))
            rhs = " ".join("/lib/modules/" + (d.replace("_", "-") if d + ".ko" not in deps_for else d) + ".ko"
                           for d in dep.split(",") if d)
            dep_lines.append(f"/lib/modules/{ko}: {rhs}".rstrip())
        entries["lib/modules/modules.dep"] = (0o100644, ("\n".join(dep_lines) + "\n").encode("utf-8"))
        return entries

    def test_extracts_verified_eth0_overlay_deterministically(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "outputs").mkdir()
            src = proj / "outputs/vendor_boot.img"
            src.write_bytes(_fake_vendor_boot(self._complete_eth0_entries()))
            with mock.patch.object(vm.workspace, "project_root", return_value=proj.resolve()):
                r1 = vm.build_overlay("outputs/vendor_boot.img",
                                      "outputs/ov1.tar.gz", "outputs/ov1.json")
                r2 = vm.build_overlay("outputs/vendor_boot.img",
                                      "outputs/ov2.tar.gz", "outputs/ov2.json")
            self.assertEqual(r1["overlay_sha256"], r2["overlay_sha256"])
            self.assertEqual(r1["module_count"], len(vm.ETH0_MODULES))
            with tarfile.open(proj / "outputs/ov1.tar.gz", "r:gz") as tf:
                names = set(tf.getnames())
                self.assertIn("usr/lib/modules/5.4.210/dwmac-meson8b.ko", names)
                self.assertIn("usr/lib/modules/5.4.210/w152d-eth0.load", names)
                dep_txt = tf.extractfile("usr/lib/modules/5.4.210/modules.dep").read().decode("utf-8")
                self.assertNotIn("/lib/modules/", dep_txt)
                load_txt = tf.extractfile("usr/lib/modules/5.4.210/w152d-eth0.load").read().decode("utf-8")
                self.assertEqual(load_txt.splitlines(), list(vm.ETH0_MODULES))
            saved = json.loads((proj / "outputs/ov1.json").read_text("utf-8"))
            self.assertEqual(saved["verified_vermagic"], vm.EXPECTED_VERMAGIC)

    def test_rejects_mismatched_vermagic_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "outputs").mkdir()
            src = proj / "outputs/bad.img"
            src.write_bytes(_fake_vendor_boot(
                self._complete_eth0_entries(bad_vermagic="6.1.0 SMP preempt aarch64")))
            with mock.patch.object(vm.workspace, "project_root", return_value=proj.resolve()):
                with self.assertRaisesRegex(ValueError, "vermagic mismatch"):
                    vm.build_overlay("outputs/bad.img", "outputs/out.tar.gz", "outputs/out.json")
            sym_entries = self._complete_eth0_entries()
            sym_entries["lib/modules/evil.ko"] = (0o120777, b"/etc/passwd")
            src2 = proj / "outputs/sym.img"
            src2.write_bytes(_fake_vendor_boot(sym_entries))
            with mock.patch.object(vm.workspace, "project_root", return_value=proj.resolve()):
                with self.assertRaisesRegex(ValueError, "non-regular file"):
                    vm.build_overlay("outputs/sym.img", "outputs/out2.tar.gz", "outputs/out2.json")

    def _fake_wifi_bundle(self, path, vermagic=vm.EXPECTED_VERMAGIC, include_vendor_symlink=True):
        with tarfile.open(path, "w:gz") as tf:
            for ko in vm.WIFI_MODULES:
                data = _fake_elf64_ko(vermagic=vermagic, depends="")
                ti = tarfile.TarInfo(f"usr/lib/modules/5.4.210/{ko}")
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            for fw, body in (("wcnmodem.bin", b"WCNMODEM"), ("wifi_board_config.ini", b"board=w152d\n")):
                ti = tarfile.TarInfo(f"usr/lib/firmware/{fw}")
                ti.size = len(body)
                tf.addfile(ti, io.BytesIO(body))
            if include_vendor_symlink:
                sym = tarfile.TarInfo("vendor/firmware/wcnmodem.bin")
                sym.type = tarfile.SYMTYPE
                sym.linkname = "/usr/lib/firmware/wcnmodem.bin"
                tf.addfile(sym)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_merges_verified_uwe5621_wifi_bundle_and_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "outputs").mkdir()
            src = proj / "outputs/vendor_boot.img"
            src.write_bytes(_fake_vendor_boot(self._complete_eth0_entries()))
            bundle = proj / "outputs/uwe5621.tar.gz"
            bundle_sha = self._fake_wifi_bundle(bundle)
            with mock.patch.object(vm.workspace, "project_root", return_value=proj.resolve()):
                report = vm.build_overlay(
                    "outputs/vendor_boot.img",
                    "outputs/full.tar.gz",
                    "outputs/full.json",
                    extra_bundle="outputs/uwe5621.tar.gz",
                    extra_bundle_sha256=bundle_sha,
                )
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    vm.build_overlay(
                        "outputs/vendor_boot.img",
                        "outputs/badsha.tar.gz",
                        "outputs/badsha.json",
                        extra_bundle="outputs/uwe5621.tar.gz",
                        extra_bundle_sha256="0" * 64,
                    )
            self.assertEqual(report["module_count"], len(vm.ETH0_MODULES) + len(vm.WIFI_MODULES))
            self.assertEqual(report["firmware_count"], 2)
            self.assertEqual(report["wifi_load_order"], list(vm.WIFI_MODULES))
            with tarfile.open(proj / "outputs/full.tar.gz", "r:gz") as tf:
                names = set(tf.getnames())
                self.assertIn("usr/lib/modules/5.4.210/sprdwl_ng.ko", names)
                self.assertIn("usr/lib/modules/5.4.210/w152d-wifi.load", names)
                self.assertIn("usr/lib/firmware/wcnmodem.bin", names)
                self.assertIn("usr/lib/firmware/wifi_board_config.ini", names)
                self.assertFalse(any(n.startswith("vendor/") for n in names))
                wifi_load = tf.extractfile("usr/lib/modules/5.4.210/w152d-wifi.load").read().decode("utf-8")
                self.assertEqual(wifi_load.splitlines(), list(vm.WIFI_MODULES))
                dep_txt = tf.extractfile("usr/lib/modules/5.4.210/modules.dep").read().decode("utf-8")
                self.assertIn("sprdwl_ng.ko: uwe5621_bsp_sdio.ko wifi_comm.ko", dep_txt)

    def test_extra_bundle_rejects_bad_vermagic(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "outputs").mkdir()
            src = proj / "outputs/vendor_boot.img"
            src.write_bytes(_fake_vendor_boot(self._complete_eth0_entries()))
            bundle = proj / "outputs/bad_wifi.tar.gz"
            bundle_sha = self._fake_wifi_bundle(bundle, vermagic="5.15.0 SMP preempt aarch64")
            with mock.patch.object(vm.workspace, "project_root", return_value=proj.resolve()):
                with self.assertRaisesRegex(ValueError, "vermagic mismatch"):
                    vm.build_overlay(
                        "outputs/vendor_boot.img",
                        "outputs/out.tar.gz",
                        "outputs/out.json",
                        extra_bundle="outputs/bad_wifi.tar.gz",
                        extra_bundle_sha256=bundle_sha,
                    )

    def test_serial_init_shell_syntax_valid(self):
        proc = subprocess.run(["/bin/sh", "-n"], input=sinit.SCRIPT,
                              capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
