"""CLI-only output confinement regression coverage; no device/network operations."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "scripts" / "workflow"

WRITER_CLIS = (
    "adaptive.py", "collect.py", "device_session.py", "manage.py",
    "image_inspect.py", "image_plan.py", "build_image.py", "rootfs_builder.py",
    "cloud_image_e2e.py", "nocloud.py", "verify_vm.py", "verify_first_boot.py",
    "physical_verify.py", "dossier.py", "capabilities.py", "topology.py",
    "device_tree.py", "link_graph.py", "compare.py", "explore.py",
    "export_html.py", "single_host.py", "status.py", "preview_control.py",
)


def module(name):
    path = WORKFLOW / name
    spec = importlib.util.spec_from_file_location("uc_policy_test_" + name[:-3], path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class OutputContractTests(unittest.TestCase):
    def test_every_writer_has_a_compilable_cli_and_workspace_guard(self):
        for name in WRITER_CLIS:
            with self.subTest(script=name):
                source = (WORKFLOW / name).read_text(encoding="utf-8")
                compile(source, str(WORKFLOW / name), "exec")
                self.assertIn("workspace.checked_output(", source)

    def test_standalone_device_session_cannot_escape_outputs(self):
        session = module("device_session.py")
        with patch.object(session, "run_collection") as run:
            code = session.main([
                "--transport", "ttl", "--target", "/dev/cu.test",
                "--output", "/tmp/not-an-output-session",
                "--approved-readonly"
            ])
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_cloud_image_e2e_rejects_external_workdir_before_preflight(self):
        cloud = module("cloud_image_e2e.py")
        with patch.object(cloud, "host_preflight") as preflight:
            rc = cloud.main([
                "--preflight", "--workdir", "/tmp/external-cloud-build"
            ])
        self.assertEqual(rc, 2)
        preflight.assert_not_called()

    def test_single_host_rejects_external_report_without_starting_vm(self):
        single = module("single_host.py")
        with patch.object(single, "execute") as execute:
            rc = single.main([
                "verify-boot", "--report", "/tmp/not-a-valid-report"
            ])
        self.assertEqual(rc, 2)
        execute.assert_not_called()

    def test_first_boot_bad_report_does_not_start_qemu_or_write_failure_file(self):
        verify = module("verify_first_boot.py")
        with patch.object(verify, "verify_first_boot") as run, \
             patch.object(verify, "save_report") as save:
            rc = verify.main([
                "--bundle", "/tmp/missing-bundle",
                "--report", "/tmp/not-a-valid-health-report", "--approved"
            ])
        self.assertEqual(rc, 2)
        run.assert_not_called()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
