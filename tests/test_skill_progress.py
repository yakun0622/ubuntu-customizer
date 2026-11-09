"""Cross-stage Skill status tests; no GitHub Actions or external services."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

ROOT = Path(__file__).resolve().parents[1] / "scripts" / "workflow"

def load(name):
    spec = importlib.util.spec_from_file_location("uc_status_test_" + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

progress = load("progress")
planner = load("image_plan")
builder = load("build_image")
nocloud = load("nocloud")
verifier = load("verify_vm")

def read_state(folder):
    return json.loads((folder / "skill-status.json").read_text(encoding="utf-8"))

def make_session(base):
    session = base / "session"
    (session / "identity").mkdir(parents=True)
    raw = session / "identity" / "kernel.txt"
    raw.write_text("Linux build-target 6.8.0 x86_64 GNU/Linux\n")
    (session / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "state": "complete", "transport": "local",
        "target": "test-machine", "items": [{
            "category": "identity", "name": "kernel", "status": "ok",
            "file": "identity/kernel.txt",
            "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()
        }]
    }))
    return session

def make_source(base):
    source = base / "source.img"
    source.write_bytes(b"mock-disk-source")
    return source, hashlib.sha256(source.read_bytes()).hexdigest()

class SkillProgressTests(unittest.TestCase):
    def test_disabled_preview_never_writes_extra_files(self):
        with tempfile.TemporaryDirectory() as d:
            session = Path(d)
            with progress.tracking(session, "image-plan", 3) as state:
                state.advance(1)
                state.advance(2)
            self.assertFalse((session / "skill-status.json").exists())

    def test_closed_preview_stops_status_writes(self):
        with tempfile.TemporaryDirectory() as d:
            session = Path(d)
            with patch.object(progress, "preview_is_live", side_effect=[True, True, False]):
                with progress.tracking(session, "image-build", 3) as state:
                    state.advance(1)
                    state.advance(2)
            report = read_state(session)
            self.assertEqual(report["state"], "running")
            self.assertEqual(report["completed"], 0)

    def test_planner_reports_blocked_and_failed(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            session = make_session(base)
            source, sha = make_source(base)
            with patch.object(planner.progress, "preview_is_live", return_value=True):
                result = planner.plan(session, "physical-device", "raw", source, sha, "amd64")
                self.assertTrue(result["blockers"])
                self.assertEqual(read_state(session)["state"], "blocked")
                self.assertEqual(read_state(session)["stage"], "image-plan")
                with self.assertRaises(ValueError):
                    planner.plan(session, "virtual-machine", "qcow2", source, "0" * 64, "amd64")
                self.assertEqual(read_state(session)["state"], "failed")

    def test_builder_reports_milestones_and_propagates_session(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            session = make_session(base)
            source, sha = make_source(base)
            plan = {
                "schema_version": 1, "type": "ubuntu-customizer/image-plan",
                "target": "virtual-machine", "format": "qcow2",
                "backend": "qemu-img-offline-convert", "build_allowed": True,
                "blockers": [], "architecture": "amd64",
                "discovery": {"session": str(session)},
                "source": {"path": str(source), "sha256": sha, "bytes": source.stat().st_size}
            }
            def info(path):
                return {"format": "qcow2" if str(path).endswith(".tmp") else "raw",
                        "virtual-size": 16384}
            def convert(args, **kwargs):
                Path(args[-1]).write_bytes(b"converted")
                return subprocess.CompletedProcess(args, 0, "", "")
            with patch.object(builder.progress, "preview_is_live", return_value=True), \
                 patch.object(builder, "inspect_image", side_effect=info), \
                 patch.object(builder.subprocess, "run", side_effect=convert):
                result = builder.build(plan, base / "out.qcow2")
            self.assertEqual(result["discovery_session"], str(session))
            self.assertEqual(read_state(session)["stage"], "image-build")
            self.assertEqual(read_state(session)["state"], "complete")
            self.assertEqual(read_state(session)["completed"], 5)
            with patch.object(builder.progress, "preview_is_live", return_value=True):
                blocked = {**plan, "build_allowed": False, "blockers": ["not compatible"]}
                with self.assertRaises(ValueError):
                    builder.build(blocked, base / "blocked.qcow2")
            self.assertEqual(read_state(session)["state"], "blocked")

    def test_nocloud_cli_reports_complete_and_invalid_plan_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            session = make_session(root)
            plan = {
                "schema_version": 1, "type": "ubuntu-customizer/image-plan",
                "target": "virtual-machine", "backend": "qemu-img-offline-convert",
                "build_allowed": True, "blockers": [],
                "discovery": {"session": str(session)}
            }
            planfile = root / "image-plan.json"
            planfile.write_text(json.dumps(plan))
            key = root / "id.pub"
            key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKJJp8za9kyuUsv1phC3wXXPzbYwdxmikbn10QECz9OA test\n")
            args = [str(planfile), "--hostname", "guest-one",
                    "--username", "ubuntu", "--ssh-public-key", str(key),
                    "--instance-id", "id-001", "--output-dir", str(root / "seed")]
            with patch.object(nocloud.progress, "preview_is_live", return_value=True):
                self.assertEqual(nocloud.main(args), 0)
                self.assertEqual(read_state(session)["stage"], "first-boot")
                self.assertEqual(read_state(session)["state"], "complete")
                planfile.write_text(json.dumps({**plan, "build_allowed": False,
                                                "blockers": ["unsupported"]}))
                args[-1] = str(root / "seed-blocked")
                self.assertEqual(nocloud.main(args), 2)
            self.assertEqual(read_state(session)["state"], "blocked")

    def test_verify_static_complete_but_unconfirmed_boot_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            session = make_session(base)
            source = base / "out.qcow2"
            source.write_bytes(b"converted disk")
            result = {
                "schema_version": 1, "type": "ubuntu-customizer/image-build-result",
                "discovery_session": str(session),
                "output_path": str(source), "output_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "output_bytes": source.stat().st_size,
                "format": "qcow2", "virtual_size": 8192, "architecture": "amd64"
            }
            with patch.object(verifier.progress, "preview_is_live", return_value=True), \
                 patch.object(verifier, "qemu_info", return_value={"format": "qcow2", "virtual-size": 8192}):
                report = verifier.verify(result)
                self.assertFalse(report["boot_confirmed"])
                self.assertEqual(read_state(session)["state"], "complete")
                with patch.object(verifier.shutil, "which", return_value="/usr/bin/qemu-system-x86_64"), \
                     patch.object(verifier.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "", "")):
                    report = verifier.verify(result, boot=True, serial_log=str(base / "serial.log"))
                self.assertFalse(report["boot_confirmed"])
                self.assertEqual(read_state(session)["state"], "blocked")

if __name__ == "__main__":
    unittest.main()
