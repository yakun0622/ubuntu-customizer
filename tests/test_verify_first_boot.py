"""Isolated first-boot health protocol, safety gates and launcher unit tests.

The positive health test uses a fake local QGA responder; it does not claim
to have booted a real Linux guest. No CI, external services or disk writes.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from image_fixtures import plan as verified_plan

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_verify_first_boot", ROOT / "scripts/workflow/verify_first_boot.py")
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)

class FirstBootHealthTests(unittest.TestCase):
    def response(self, nonce, failures=()):
        checks = {name: name not in failures for name in health.REQUIRED}
        return json.dumps({
            "schema_version": 1, "nonce": nonce, "boot_id_valid": True,
            "machine_id": "a"*32, "checks": checks
        }, separators=(",", ":"))

    def synthetic_bundle(self, root, mode="bios"):
        bundle = root / "bundle"
        bundle.mkdir()
        image = bundle / "image.qcow2"
        image.write_bytes(b"synthetic disk")
        seed = bundle / "seed"
        seed.mkdir()
        for name in ("user-data","meta-data","manifest.json"):
            (seed / name).write_text("{}")
        recipe = {
            "schema_version": 1,
            "hostname": "portable-guest",
            "first_boot": {"mode": "nocloud", "instance_id": "instance-200"}
        }
        (bundle / "build-config.json").write_text(json.dumps(recipe))
        report = {
            "schema_version": 1, "type": "ubuntu-customizer/rootfs-build-result",
            "boot_tested": False,
            "source_plan_architecture": "amd64",
            "discovery_session": None,
            "image_plan_sha256": "f"*64,
            "output": {"file":"image.qcow2", "format":"qcow2",
                       "sha256": hashlib.sha256(image.read_bytes()).hexdigest()},
            "guest_evidence":{"observations":{"boot_mode":mode}}
        }
        (bundle / "build-manifest.json").write_text(json.dumps(report))
        return bundle, image, report, recipe

    def test_health_requires_challenge_and_all_checks(self):
        nonce = "d"*48
        checks = health.evaluate_probe(self.response(nonce), nonce)
        self.assertTrue(all(checks.values()))
        with self.assertRaises(ValueError):
            health.evaluate_probe(self.response("old"), nonce)
        with self.assertRaises(ValueError):
            health.evaluate_probe(json.dumps({"schema_version":1, "nonce":nonce,
                                              "boot_id_valid":True, "machine_id":"a"*32,
                                              "checks":{"linux_boot":True}}), nonce)
        with self.assertRaises(ValueError):
            health.evaluate_probe(self.response(nonce).replace('"machine_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
                                                              '"machine_id":"00000000000000000000000000000000"'), nonce)

    def test_health_failed_check_is_not_healthy(self):
        checks = health.evaluate_probe(self.response("x", {"cloud_init","network","ssh_host_keys"}), "x")
        self.assertFalse(all(checks.values()))
        self.assertFalse(checks["cloud_init"])
        self.assertFalse(checks["network"])

    def test_guest_probe_cannot_read_credentials_or_change_guest(self):
        fixed = health.GUEST_PROBE
        for marker in ("cloud-init", "instance-data.json", "machine-id",
                       "ssh_host_", "is-system-running", "ip", "nonce"):
            self.assertIn(marker, fixed)
        self.assertNotIn("shell=True", fixed)
        self.assertNotIn("apt install", fixed)
        self.assertNotIn("ssh-keygen", fixed)
        self.assertNotIn("os.system", fixed)

    def test_snapshot_and_restricted_network_with_guest_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "image.qcow2"
            seed = root / "seed.iso"
            image.write_bytes(b"test")
            seed.write_bytes(b"iso")
            args = health.build_cmd(image,"qcow2",root/"qga.sock",seed,"bios")
            self.assertIn("-snapshot", args)
            self.assertIn("user,id=isolated,restrict=on", args)
            self.assertTrue(any("org.qemu.guest_agent.0" in x for x in args))
            self.assertFalse(any("hostfwd" in x or "tap," in x or "bridge," in x for x in args))
            self.assertEqual(args[args.index("-accel")+1],"tcg")
            # The verifier intentionally resolves macOS /var -> /private/var.
            self.assertIn("file="+str(image.resolve())+",format=qcow2,if=virtio", args)

    def test_uefi_requires_explicit_trusted_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image, seed = root/"a.qcow2", root/"seed.iso"
            image.write_bytes(b"disk")
            seed.write_bytes(b"seed")
            with self.assertRaises(ValueError):
                health.build_cmd(image,"qcow2",root/"qga.sock",seed,"uefi")
            code, variables = root/"OVMF_CODE.fd", root/"OVMF_VARS.fd"
            code.write_bytes(b"code")
            variables.write_bytes(b"vars")
            args = health.build_cmd(image,"qcow2",root/"qga.sock",seed,"uefi",code,variables)
            self.assertTrue(any("if=pflash" in x for x in args))
            with self.assertRaises(ValueError):
                health.build_cmd(image,"qcow2",root/"qga.sock",seed,"unsupported")

    def test_local_qga_json_rpc_and_guest_exec(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/"guest.sock")
            ready = threading.Event()
            handled = []
            def server():
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
                    s.bind(path)
                    s.listen(1)
                    ready.set()
                    with s.accept()[0] as channel:
                        file = channel.makefile("rb")
                        for _ in range(3):
                            request = json.loads(file.readline())
                            handled.append(request)
                            name = request["execute"]
                            if name == "guest-ping":
                                reply = {}
                            elif name == "guest-exec":
                                reply = {"pid":21}
                            elif name == "guest-exec-status":
                                reply = {"exited":True, "exitcode":0,
                                         "out-data":base64.b64encode(
                                             self.response("nonce").encode()).decode()}
                            channel.sendall(json.dumps({"return":reply}).encode()+b"\n")
            task = threading.Thread(target=server,daemon=True)
            task.start()
            self.assertTrue(ready.wait(3))
            with health.GuestAgent(path) as client:
                self.assertEqual(client.call("guest-ping"),{})
                response = client.exec("nonce","portable-guest","instance-200",
                                       health.time.monotonic()+10)
                checks = health.evaluate_probe(response,"nonce")
            task.join(timeout=3)
            self.assertTrue(all(checks.values()))
            self.assertEqual([x["execute"] for x in handled],
                             ["guest-ping", "guest-exec", "guest-exec-status"])
            self.assertEqual(handled[1]["arguments"]["path"],"/usr/bin/python3")

    def test_build_manifest_architecture_and_snapshot_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle, image, data, recipe = self.synthetic_bundle(Path(tmp))
            with patch.object(health.rootfs,"verify_bundle",return_value={"hash_verified":True}):
                folder, path, result, config, mode = health.validate_bundle(bundle)
                self.assertEqual(path, image.resolve())
                self.assertEqual(mode,"bios")
                data["source_plan_architecture"]="arm64"
                (bundle/"build-manifest.json").write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    health.validate_bundle(bundle)

    def test_mocked_full_boot_requires_all_guest_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, image, data, recipe = self.synthetic_bundle(root)
            class Process:
                def __init__(self):
                    self.stopped = False
                def poll(self):
                    return 0 if self.stopped else None
                def terminate(self):
                    self.stopped = True
                def wait(self,timeout=None):
                    return 0
                def kill(self):
                    self.stopped = True
            started = []
            def fake_start(args, **kwargs):
                started.append(args)
                channel = args[args.index("-chardev")+1]
                socket_path = next(x[5:] for x in channel.split(",") if x.startswith("path="))
                Path(socket_path).touch()
                return Process()
            class Agent:
                def __init__(self, address):
                    self.address = address
                def __enter__(self):
                    return self
                def __exit__(self,*args):
                    pass
                def call(self, name):
                    self_outer.assertEqual(name, "guest-ping")
                    return {}
                def exec(self, nonce, hostname, instance_id, deadline):
                    self_outer.assertEqual(hostname, "portable-guest")
                    self_outer.assertEqual(instance_id, "instance-200")
                    return self_outer.response(nonce)
            self_outer = self
            def fake_iso(folder, target):
                Path(target).write_bytes(b"mock-seed-iso")
                return {"path": str(target), "sha256": "a"*64, "bytes": 13}
            with patch.object(health.rootfs, "verify_bundle", return_value={"hash_verified":True}), \
                 patch.object(health.nocloud, "make_iso", side_effect=fake_iso), \
                 patch.object(health.shutil, "which", return_value="/usr/bin/qemu-system-x86_64"), \
                 patch.object(health.subprocess, "Popen", side_effect=fake_start), \
                 patch.object(health, "GuestAgent", Agent):
                report = health.verify_first_boot(bundle, timeout=30)
            self.assertTrue(report["boot_confirmed"])
            self.assertTrue(report["first_boot_confirmed"])
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["qga_connected"])
            self.assertTrue(started)
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),
                             data["output"]["sha256"])
            self.assertNotIn("machine_id", report)
            self.assertNotIn("nonce", report)

    def test_qemu_exits_before_health_is_never_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, image, data, recipe = self.synthetic_bundle(root)
            class DeadProcess:
                def poll(self):
                    return 1
                def terminate(self):
                    raise AssertionError("Already exited QEMU must not be terminated")
            def fake_iso(folder, target):
                Path(target).write_bytes(b"seed")
                return {"path":str(target), "sha256":"1"*64, "bytes":4}
            with patch.object(health.rootfs, "verify_bundle",return_value={"hash_verified":True}), \
                 patch.object(health.nocloud,"make_iso",side_effect=fake_iso), \
                 patch.object(health.shutil,"which",return_value="/usr/bin/qemu-system-x86_64"), \
                 patch.object(health.subprocess,"Popen",return_value=DeadProcess()):
                report = health.verify_first_boot(bundle,timeout=30)
            self.assertFalse(report["boot_confirmed"])
            self.assertEqual(report["status"],"failed")
            self.assertEqual(report["reason"],"qemu_exited_before_health")

    def test_guest_agent_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, image, data, recipe = self.synthetic_bundle(root)
            class RunningProcess:
                stopped = False
                def poll(self):
                    return 0 if self.stopped else None
                def terminate(self):
                    self.stopped = True
                def wait(self,timeout=None):
                    return 0
            def fake_iso(folder, target):
                Path(target).write_bytes(b"seed")
                return {"path":str(target), "sha256":"1"*64, "bytes":4}
            with patch.object(health.rootfs, "verify_bundle",return_value={"hash_verified":True}), \
                 patch.object(health.nocloud,"make_iso",side_effect=fake_iso), \
                 patch.object(health.shutil,"which",return_value="/usr/bin/qemu-system-x86_64"), \
                 patch.object(health.subprocess,"Popen",return_value=RunningProcess()), \
                 patch.object(health.time,"monotonic",side_effect=[100.0,131.0]):
                report = health.verify_first_boot(bundle,timeout=30)
            self.assertFalse(report["boot_confirmed"])
            self.assertFalse(report["qga_connected"])
            self.assertEqual(report["status"],"blocked")
            self.assertEqual(report["reason"],"guest_agent_or_health_timeout")

    def test_private_sanitized_failure_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root/"report.json"
            self.assertEqual(health.main(["--bundle",str(root/"missing"),
                                           "--approved","--report",str(report)]),2)
            failure = json.loads(report.read_text())
            self.assertFalse(failure["boot_confirmed"])
            self.assertIsNone(failure["boot_attempted"])  # Exception preempts reliable attempt accounting
            self.assertEqual(failure["status"],"failed")
            self.assertEqual(report.stat().st_mode & 0o077,0)
            self.assertNotIn(str(root),report.read_text())
            with self.assertRaises(ValueError):
                health.save_report(report, failure)

    def test_user_must_approve_boot_before_any_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp)/"report.json"
            self.assertEqual(health.main(["--bundle",tmp,"--report",str(report)]),2)
            self.assertFalse(report.exists())

if __name__ == "__main__":
    unittest.main()
