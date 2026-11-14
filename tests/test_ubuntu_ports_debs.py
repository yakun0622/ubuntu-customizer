"""Offline unit tests for Ubuntu Ports ARM64 .deb closure and SHA-256 bundler."""
import hashlib
import importlib.util
import io
import json
import lzma
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ubuntu_ports_debs", ROOT / "scripts/workflow/ubuntu_ports_debs.py")
debs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(debs)


def _fake_deb_bytes(label):
    return b"!<arch>\n" + f"fake-deb-{label}\n".encode("ascii")


def _fake_base_tar(path, status_text):
    with tarfile.open(path, "w:gz") as tf:
        raw = status_text.encode("utf-8")
        ti = tarfile.TarInfo("var/lib/dpkg/status")
        ti.size = len(raw)
        tf.addfile(ti, io.BytesIO(raw))


class _BytesResp:
    def __init__(self, payload):
        self._buf = io.BytesIO(payload)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class UbuntuPortsDebsTests(unittest.TestCase):
    def test_debian_version_comparison_handles_epochs_tildes_and_revisions(self):
        self.assertEqual(debs.compare_deb_versions("1.0~beta1", "1.0"), -1)
        self.assertEqual(debs.compare_deb_versions("1.0", "1.0-0ubuntu1"), -1)
        self.assertEqual(debs.compare_deb_versions("1:1.0-1", "2.9-9"), 1)
        self.assertEqual(debs.compare_deb_versions("3.0.13-0ubuntu3.4", "3.0.13-0ubuntu3.1"), 1)
        self.assertTrue(debs.version_satisfies("2:9.6p1-3ubuntu13.5", ">=", "1:9.0"))
        self.assertFalse(debs.version_satisfies("1.2-1", ">>", "1.2-1"))

    def test_resolves_closure_verifies_sha256_and_enforces_network_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "outputs").mkdir()
            base_tar = proj / "outputs/ubuntu-base-24.04.5-base-arm64.tar.gz"
            _fake_base_tar(
                base_tar,
                (
                    "Package: libc6\n"
                    "Status: install ok installed\n"
                    "Version: 2.39-0ubuntu8.3\n\n"
                    "Package: debconf\n"
                    "Status: install ok installed\n"
                    "Version: 1.5.86ubuntu1\n"
                    "Provides: debconf-2.0\n\n"
                ),
            )

            kmod_deb = _fake_deb_bytes("kmod")
            libkmod_deb = _fake_deb_bytes("libkmod2")
            kmod_sha = hashlib.sha256(kmod_deb).hexdigest()
            libkmod_sha = hashlib.sha256(libkmod_deb).hexdigest()

            noble_main = (
                f"Package: kmod\n"
                f"Version: 31+20240202-2ubuntu7\n"
                f"Architecture: arm64\n"
                f"Depends: libc6 (>= 2.38), libkmod2 (= 31+20240202-2ubuntu7), debconf (>= 0.5) | debconf-2.0\n"
                f"Filename: pool/main/k/kmod/kmod_31+20240202-2ubuntu7_arm64.deb\n"
                f"Size: {len(kmod_deb)}\n"
                f"SHA256: {kmod_sha}\n\n"
                f"Package: libkmod2\n"
                f"Version: 31+20240202-2ubuntu7\n"
                f"Architecture: arm64\n"
                f"Depends: libc6 (>= 2.38)\n"
                f"Filename: pool/main/k/kmod/libkmod2_31+20240202-2ubuntu7_arm64.deb\n"
                f"Size: {len(libkmod_deb)}\n"
                f"SHA256: {libkmod_sha}\n\n"
            ).encode("utf-8")

            url_map = {}
            for suite in debs.SUITES:
                for comp in debs.COMPONENTS:
                    body = noble_main if (suite == "noble" and comp == "main") else b""
                    url_map[f"{debs.OFFICIAL_MIRROR}/dists/{suite}/{comp}/binary-arm64/Packages.xz"] = lzma.compress(body)
            url_map[f"{debs.OFFICIAL_MIRROR}/pool/main/k/kmod/kmod_31+20240202-2ubuntu7_arm64.deb"] = kmod_deb
            url_map[f"{debs.OFFICIAL_MIRROR}/pool/main/k/kmod/libkmod2_31+20240202-2ubuntu7_arm64.deb"] = libkmod_deb

            def fake_opener(req, timeout=60):
                url = req.full_url if hasattr(req, "full_url") else str(req)
                if url not in url_map:
                    raise AssertionError("Unexpected URL requested: " + url)
                return _BytesResp(url_map[url])

            with mock.patch.object(debs.workspace, "project_root", return_value=proj.resolve()):
                # Without --network-approved and empty cache, must refuse immediately.
                with self.assertRaisesRegex(ValueError, "Network download approval required"):
                    debs.build_deb_bundle(
                        "outputs/b0.tar.gz",
                        "outputs/b0.json",
                        packages=("kmod",),
                        base_archive="outputs/ubuntu-base-24.04.5-base-arm64.tar.gz",
                        cache_dir="outputs/cache",
                        verify_pinned_base=False,
                        network_approved=False,
                        opener=fake_opener,
                    )

                # Approved fetch builds deterministic bundle and caches .debs.
                rep1 = debs.build_deb_bundle(
                    "outputs/b1.tar.gz",
                    "outputs/b1.json",
                    packages=("kmod",),
                    base_archive="outputs/ubuntu-base-24.04.5-base-arm64.tar.gz",
                    cache_dir="outputs/cache",
                    verify_pinned_base=False,
                    network_approved=True,
                    opener=fake_opener,
                )
                # Subsequent offline build succeeds purely from verified local cache!
                rep2 = debs.build_deb_bundle(
                    "outputs/b2.tar.gz",
                    "outputs/b2.json",
                    packages=("kmod",),
                    base_archive="outputs/ubuntu-base-24.04.5-base-arm64.tar.gz",
                    cache_dir="outputs/cache",
                    verify_pinned_base=False,
                    network_approved=False,
                    opener=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not fetch")),
                )

            self.assertEqual(rep1["bundle_sha256"], rep2["bundle_sha256"])
            self.assertEqual(rep1["resolved_package_count"], 2)
            self.assertEqual([p["name"] for p in rep1["packages"]], ["kmod", "libkmod2"])
            with tarfile.open(proj / "outputs/b1.tar.gz", "r:gz") as tf:
                self.assertIn("var/cache/uc-debs/kmod_31+20240202-2ubuntu7_arm64.deb", tf.getnames())
                self.assertIn("var/cache/uc-debs/libkmod2_31+20240202-2ubuntu7_arm64.deb", tf.getnames())

            # Tampered remote payload fails closed on SHA-256 mismatch.
            url_map[f"{debs.OFFICIAL_MIRROR}/pool/main/k/kmod/kmod_31+20240202-2ubuntu7_arm64.deb"] = (
                b"!<arch>\n" + b"X" * (len(kmod_deb) - 8)
            )
            with mock.patch.object(debs.workspace, "project_root", return_value=proj.resolve()):
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    debs.build_deb_bundle(
                        "outputs/bad.tar.gz",
                        "outputs/bad.json",
                        packages=("kmod",),
                        base_archive="outputs/ubuntu-base-24.04.5-base-arm64.tar.gz",
                        cache_dir="outputs/cache-tampered",
                        verify_pinned_base=False,
                        network_approved=True,
                        opener=fake_opener,
                    )


if __name__ == "__main__":
    unittest.main()
