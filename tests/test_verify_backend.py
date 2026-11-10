"""Verifiers are selected explicitly; QEMU is never a universal prerequisite."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uc_verify_backend_test",
                                            ROOT / "scripts/workflow/verify_backend.py")
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)

def args(*argv):
    p = verify.main.__globals__  # Make argparse inputs as ordinary namespace.
    from argparse import Namespace
    d = dict(backend="arm-boot-log", host_backend=None, lima_instance="default",
             log=None, session=None, source=None, sha256=None, bundle=None,
             output=None, report=None, approved=False, timeout=300,
             ovmf_code=None, ovmf_vars=None)
    d.update(dict(argv))
    return Namespace(**d)

class BackendTests(unittest.TestCase):
    def test_arm_log_adapter_never_calls_qemu(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "log.txt"
            log.write_text("Linux version 6.6\nsystemd[1]: boot\n")
            output = Path(d) / "evidence.json"
            with patch.object(verify, "module", wraps=verify.module) as lookup:
                result = verify.execute(args(("backend","arm-boot-log"), ("log",str(log)),
                                             ("output",str(output))))
            self.assertFalse(result["boot_confirmed"])
            self.assertTrue(output.exists())
            self.assertTrue(all(call.args[0] != "single_host" for call in lookup.call_args_list))

    def test_qemu_requires_explicit_approval(self):
        with self.assertRaises(ValueError):
            verify.execute(args(("backend","qemu-health"), ("bundle","/unused"),
                                ("report","/unused.json")))
    def test_static_backend_reports_inspected_never_booted(self):
        class Dispatcher:
            @staticmethod
            def parser():
                import argparse
                p=argparse.ArgumentParser()
                p.add_argument("action")
                p.add_argument("--source")
                p.add_argument("--sha256")
                p.add_argument("--output")
                p.add_argument("--lima-instance")
                return p
            @staticmethod
            def execute(*a):
                return {"status":"completed"}
        with patch.object(verify, "module", return_value=Dispatcher):
            result=verify.execute(args(("backend","static-image"),
                                       ("source","disk.img"),("sha256","a"*64),
                                       ("output","scan.json")))
        self.assertFalse(result["boot_confirmed"])
        self.assertEqual(result["status"],"inspected")

    def test_qemu_nonzero_or_false_checks_not_accepted(self):
        class Dispatcher:
            @staticmethod
            def parser():
                import argparse
                p=argparse.ArgumentParser()
                p.add_argument("action")
                for name in ("bundle","report","timeout","approved","lima-instance",
                             "ovmf-code","ovmf-vars"):
                    p.add_argument("--"+name, nargs="?", const=True)
                return p
            @staticmethod
            def execute(*a):
                return {"status":"completed"}
        class Reader:
            @staticmethod
            def read_json_regular(path):
                return {"type":"ubuntu-customizer/first-boot-health",
                        "boot_confirmed":True,"first_boot_confirmed":True,
                        "status":"passed","checks":{"network":False}}
        class Required:
            REQUIRED=("linux_boot", "network")
        def mocked_module(name):
            return {"single_host":Dispatcher, "rootfs_builder":Reader,
                    "verify_first_boot":Required}[name]
        with patch.object(verify,"module",side_effect=mocked_module):
            result=verify.execute(args(("backend","qemu-health"),
                                       ("bundle","bundle"),("report","report.json"),
                                       ("approved",True)))
        self.assertFalse(result["boot_confirmed"])
        self.assertEqual(result["status"],"unverified")

if __name__=="__main__":
    unittest.main()
