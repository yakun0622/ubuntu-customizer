"""Agent-first conversational orchestration policy, without CLI or side effects."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uc_agent_journey_test", ROOT / "scripts/workflow/agent_journey.py")
journey = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(journey)

def answer(state, field, value):
    return journey.transition(state, {"type": "answer", "field": field, "value": value})

def finish(state, step, status="complete", **kw):
    return journey.transition(state, {"type": "result", "step": step,
                                       "state": status, **kw})

class AgentJourneyTests(unittest.TestCase):
    def ready(self, target="virtual-machine"):
        transport = "ttl" if target == "physical-device" else "local"
        state = journey.start("image", target, transport, True,
                              "/dev/cu.wchusbserial1140 921600" if transport == "ttl" else None)
        state = finish(state, "host")
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        state = answer(state, "plan_confirm", True)
        state = finish(state, "collect")
        state = finish(state, "analyze")
        self.assertEqual(journey.next_step(state)["step"], "requirements")
        self.assertEqual(journey.next_step(state)["helper"], "agent.conversation")
        state = finish(state, "requirements")
        return state

    def prepared_vm(self):
        state = self.ready()
        state = answer(state, "source_ready", "trusted-download")
        for step in ("image_inspect", "image_plan", "recipe_preview"):
            self.assertEqual(journey.next_step(state)["step"], step)
            state = finish(state, step)
        return state

    def test_one_phrase_start_immediately_inspects_host_without_questionnaire(self):
        state = journey.start()
        task = journey.next_step(state)
        self.assertEqual(task["kind"], "run")
        self.assertEqual(task["step"], "host")
        self.assertEqual(task["helper"], "host_capabilities.inspect")
        self.assertEqual(task["risk"], "R0")
        state = finish(state, "host")
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "goal")

    def test_workspace_is_automatic_before_device_choices(self):
        state = journey.start("inspect", transport="ttl", interface_ready=True,
                              interface_display="/dev/cu.wchusbserial1140 921600")
        state = finish(state, "host")
        step = journey.next_step(state)
        self.assertEqual(step["kind"], "run")
        self.assertEqual(step["step"], "workspace")
        self.assertEqual(step["helper"], "project_workspace.prepare")
        self.assertEqual(step["risk"], "R1")
        with self.assertRaises(ValueError):
            answer(state, "plan_confirm", True)
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")

    def test_only_one_question_at_each_missing_choice(self):
        state = journey.start()
        state = finish(state, "host")
        state = finish(state, "workspace")
        state = answer(state, "goal", "image")
        self.assertEqual(journey.next_step(state)["field"], "target")
        state = answer(state, "target", "virtual-machine")
        self.assertEqual(journey.next_step(state)["field"], "transport")
        state = answer(state, "transport", "ttl")
        self.assertEqual(journey.next_step(state)["field"], "interface_ready")
        state = answer(state, "interface_ready", True)
        self.assertEqual(journey.next_step(state)["field"], "interface_display")
        state = answer(state, "interface_display", "/dev/cu.wchusbserial1140 921600")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        plan = journey.next_step(state)["plan"]
        self.assertEqual(plan["transport"], "ttl")
        self.assertEqual(plan["connection"], "/dev/cu.wchusbserial1140 921600")
        self.assertIn("127.0.0.1", plan["preview"])
        state = answer(state, "plan_confirm", True)
        task = journey.next_step(state)
        self.assertEqual(task["step"], "collect")
        self.assertTrue(task["preview_approved"])
        self.assertTrue(task["start_preview_before_probes"])

    def test_decline_device_access_halts_without_collection(self):
        state = journey.start("inspect", transport="local")
        state = finish(state, "host")
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        state = answer(state, "plan_confirm", False)
        self.assertEqual(journey.next_step(state)["kind"], "pause")
        with self.assertRaises(ValueError):
            finish(state, "collect")

    def test_vm_build_has_separate_confirmation_and_declining_stops_before_writes(self):
        state = self.prepared_vm()
        self.assertEqual(journey.next_step(state)["field"], "offline_build")
        state = answer(state, "offline_build", False)
        self.assertEqual(journey.next_step(state)["result"], "plan_only")
        self.assertNotIn("rootfs_build", state["steps"])
        self.assertFalse(state["boot_confirmed"])

    def test_approved_build_still_needs_separate_boot_choice(self):
        state = answer(self.prepared_vm(), "offline_build", True)
        task = journey.next_step(state)
        self.assertEqual(task["step"], "rootfs_build")
        self.assertEqual(task["approval_required"], "offline_build")
        state = finish(state, "rootfs_build")
        state = finish(state, "bundle_verify")
        self.assertEqual(journey.next_step(state)["field"], "run_boot")
        state = answer(state, "run_boot", False)
        task = journey.next_step(state)
        self.assertEqual(task["kind"], "done")
        self.assertEqual(task["result"], "artifact_verified_only")
        self.assertFalse(task["boot_confirmed"])

    def test_vm_boot_needs_independent_explicit_approval(self):
        state = answer(self.prepared_vm(), "offline_build", True)
        state = finish(state, "rootfs_build")
        state = finish(state, "bundle_verify")
        state = answer(state, "run_boot", True)
        self.assertEqual(journey.next_step(state)["field"], "isolated_vm_boot")
        state = answer(state, "isolated_vm_boot", True)
        self.assertEqual(journey.next_step(state)["step"], "qemu_verify")
        with self.assertRaises(ValueError):
            finish(state, "image_inspect")

    def test_declined_optional_guest_test_keeps_artifact_only(self):
        state = answer(self.prepared_vm(), "offline_build", True)
        state = finish(state, "rootfs_build")
        state = finish(state, "bundle_verify")
        state = answer(state, "run_boot", True)
        state = answer(state, "isolated_vm_boot", False)
        result = journey.next_step(state)
        self.assertEqual(result["kind"], "done")
        self.assertEqual(result["result"], "artifact_verified_only")
        self.assertFalse(result["boot_confirmed"])
    def test_skippable_blocked_guest_verification(self):
        state = answer(self.prepared_vm(), "offline_build", True)
        state = finish(state, "rootfs_build")
        state = finish(state, "bundle_verify")
        state = answer(state, "run_boot", True)
        state = answer(state, "isolated_vm_boot", True)
        state = finish(state, "qemu_verify", "blocked")
        self.assertEqual(journey.next_step(state)["kind"], "halt")
        state = journey.transition(state, {"type": "skip_boot"})
        self.assertEqual(journey.next_step(state)["result"], "artifact_verified_only")
        self.assertFalse(journey.next_step(state)["boot_confirmed"])
    def test_incomplete_guest_health_is_not_boot_confirmation(self):
        state = answer(self.prepared_vm(), "offline_build", True)
        state = finish(state, "rootfs_build")
        state = finish(state, "bundle_verify")
        state = answer(state, "run_boot", True)
        state = answer(state, "isolated_vm_boot", True)
        bad = {"type":"ubuntu-customizer/first-boot-health", "status":"passed",
               "boot_confirmed": True, "first_boot_confirmed": True,
               "checks": {"linux_boot": True}}
        state = finish(state, "qemu_verify", health_report=bad)
        self.assertFalse(journey.next_step(state)["boot_confirmed"])
        self.assertEqual(journey.next_step(state)["result"], "boot_unverified")

    def test_complete_guest_health_is_only_path_to_boot_confirmed(self):
        state = answer(self.prepared_vm(), "offline_build", True)
        state = finish(state, "rootfs_build")
        state = finish(state, "bundle_verify")
        state = answer(state, "run_boot", True)
        state = answer(state, "isolated_vm_boot", True)
        report = {"type":"ubuntu-customizer/first-boot-health", "status":"passed",
                  "boot_confirmed": True, "first_boot_confirmed": True,
                  "checks": {name: True for name in journey.GUEST_CHECKS}}
        state = finish(state, "qemu_verify", health_report=report)
        self.assertEqual(journey.next_step(state)["result"], "guest_health_verified")
        self.assertTrue(journey.next_step(state)["boot_confirmed"])

    def test_physical_arm_builds_then_requires_current_usb_log_for_diagnosis(self):
        state = self.ready("physical-device")
        state = answer(state, "baseline_download", True)
        for step in ("arm_baseline", "arm_research", "arm_candidate", "arm_preflight"):
            self.assertEqual(journey.next_step(state)["step"], step)
            state = finish(state, step)
        self.assertEqual(journey.next_step(state)["field"], "offline_build")
        state = answer(state, "offline_build", True)
        task = journey.next_step(state)
        self.assertEqual(task["step"], "arm_build")
        self.assertTrue(task["no_block_devices"])
        self.assertTrue(task["no_emmc_write"])
        self.assertEqual(task["approval_required"], "offline_build")
        state = finish(state, "arm_build")
        self.assertEqual(journey.next_step(state)["field"], "usb_log_ready")
        state = answer(state, "usb_log_ready", False)
        self.assertEqual(journey.next_step(state)["result"], "usb_boot_log_required")
        self.assertFalse(journey.next_step(state)["boot_confirmed"])
        state = journey.transition(state, {"type": "usb_boot_log_available"})
        self.assertEqual(journey.next_step(state)["step"], "physical_evidence")
        state = finish(state, "physical_evidence")
        self.assertEqual(journey.next_step(state)["step"], "arm_diagnose")
        state = finish(state, "arm_diagnose")
        next_task = journey.next_step(state)
        self.assertEqual(next_task["result"], "arm_iteration_required")
        self.assertFalse(next_task["physical_deployment_allowed"])
        state = journey.transition(state, {"type": "iterate_arm"})
        self.assertEqual(journey.next_step(state)["step"], "arm_research")
        self.assertEqual(state["choices"]["arm_revision"], 2)
        self.assertIsNone(state["consent"]["offline_build"])
        self.assertIsNone(state["choices"]["usb_log_ready"])
        state = finish(state, "arm_research")
        self.assertEqual(journey.next_step(state)["revision"], 2)

    def test_arm_build_needs_separate_approval_and_failed_build_can_iterate(self):
        state = answer(self.ready("physical-device"), "baseline_download", True)
        for step in ("arm_baseline", "arm_research", "arm_candidate", "arm_preflight"):
            state = finish(state, step)
        with self.assertRaises(ValueError):
            finish(state, "arm_build")
        state = answer(state, "offline_build", True)
        state = finish(state, "arm_build", "blocked")
        self.assertEqual(journey.next_step(state)["kind"], "halt")
        state = journey.transition(state, {"type": "iterate_arm"})
        self.assertEqual(journey.next_step(state)["step"], "arm_research")
        self.assertIsNone(state["consent"]["offline_build"])

    def test_arm_preflight_blocks_missing_tools_before_build(self):
        state = answer(self.ready("physical-device"), "baseline_download", True)
        for step in ("arm_baseline", "arm_research", "arm_candidate"):
            state = finish(state, step)
        task = journey.next_step(state)
        self.assertEqual(task["step"], "arm_preflight")
        self.assertTrue(task["no_host_path_scan"])
        state = finish(state, "arm_preflight", "blocked")
        self.assertEqual(journey.next_step(state)["kind"], "halt")
        state = journey.transition(state, {"type": "iterate_arm"})
        self.assertEqual(journey.next_step(state)["step"], "arm_research")
        self.assertNotIn("arm_preflight", state["steps"])

    def test_declined_baseline_does_not_search_local_files(self):
        state = self.ready("physical-device")
        state = answer(state, "baseline_download", False)
        task = journey.next_step(state)
        self.assertEqual(task["result"], "baseline_download_declined")
        self.assertNotIn("arm_baseline", state["steps"])

    def test_arm_recovery_iteration_after_evidence_block(self):
        state = answer(self.ready("physical-device"), "baseline_download", True)
        for step in ("arm_baseline", "arm_research", "arm_candidate", "arm_preflight"):
            state = finish(state, step)
        state = answer(state, "offline_build", True)
        state = finish(state, "arm_build")
        state = answer(state, "usb_log_ready", True)
        state = finish(state, "physical_evidence", "blocked")
        self.assertEqual(journey.next_step(state)["kind"], "halt")
        recovered = journey.transition(state, {"type": "iterate_arm"})
        self.assertEqual(recovered["choices"]["arm_revision"], 2)
        self.assertEqual(journey.next_step(recovered)["step"], "arm_research")
        with self.assertRaises(ValueError):
            journey.transition(recovered, {"type": "iterate_arm"})

    def test_blocked_stage_must_be_explicitly_retried_or_optional_boot_skipped(self):
        state = self.ready()
        state = answer(state, "source_ready", "local-verified")
        state = finish(state, "image_inspect", "blocked")
        self.assertEqual(journey.next_step(state)["kind"], "halt")
        with self.assertRaises(ValueError):
            finish(state, "image_plan")
        state = journey.transition(state, {"type": "retry", "step": "image_inspect"})
        self.assertEqual(journey.next_step(state)["step"], "image_inspect")

    def test_device_plan_cannot_be_confirmed_without_actual_endpoint(self):
        state = journey.start("inspect", transport="ttl", interface_ready=True)
        state = finish(state, "host")
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "interface_display")
        with self.assertRaises(ValueError):
            answer(state, "plan_confirm", True)
        with self.assertRaisesRegex(ValueError, "baud"):
            answer(state, "interface_display", "/dev/cu.wchusbserial1140")
        state = answer(state, "interface_display", "/dev/cu.wchusbserial1140 921600")
        self.assertEqual(journey.next_step(state)["plan"]["connection"],
                         "/dev/cu.wchusbserial1140 921600")
        state = answer(state, "plan_confirm", True)
        self.assertEqual(journey.next_step(state)["interface_display"],
                         "/dev/cu.wchusbserial1140 921600")

    def test_interface_switch_clears_old_endpoint(self):
        state = journey.start("inspect", transport="ttl", interface_ready=True,
                              interface_display="/dev/cu.wchusbserial1140 921600")
        state = finish(state, "host")
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        with self.assertRaises(ValueError):
            journey.start("inspect", transport="ttl", interface_ready=True,
                          interface_display="tty")
        with self.assertRaises(ValueError):
            journey.start("inspect", transport="ssh", interface_ready=False,
                          interface_display="Host server")

    def test_missing_connection_is_not_silently_assumed(self):
        state = journey.start("inspect")
        state = finish(state, "host")
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "transport")
        state = answer(state, "transport", "adb")
        self.assertEqual(journey.next_step(state)["field"], "interface_ready")
        with self.assertRaises(ValueError):
            answer(state, "plan_confirm", True)
        state = answer(state, "interface_ready", False)
        self.assertEqual(journey.next_step(state)["kind"], "pause")

    def test_known_ttl_target_skips_repeated_connection_questions(self):
        state = journey.start("image", "physical-device", "ttl", True,
                              "/dev/cu.wchusbserial1140 921600")
        state = finish(state, "host")
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        with self.assertRaises(ValueError):
            finish(state, "collect")
        state = answer(state, "plan_confirm", True)
        self.assertEqual(journey.next_step(state)["transport"], "ttl")
        self.assertTrue(journey.next_step(state)["preview_approved"])

    def test_local_interface_is_implicit_and_monitor_uses_plan_consent(self):
        state = journey.start("inspect", transport="local")
        state = finish(state, "host")
        state = finish(state, "workspace")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        state = answer(state, "plan_confirm", True)
        self.assertTrue(journey.next_step(state)["preview_approved"])

    def test_explicit_monitor_opt_out_keeps_readonly_collection(self):
        state = journey.start("inspect", transport="local")
        state = finish(state, "host")
        state = finish(state, "workspace")
        state = journey.transition(state, {"type": "preview_preference", "enabled": False})
        self.assertIn("关闭监控", journey.next_step(state)["plan"]["preview"])
        state = answer(state, "plan_confirm", True)
        task = journey.next_step(state)
        self.assertEqual(task["step"], "collect")
        self.assertFalse(task["preview_approved"])

    def test_preview_preference_cannot_change_after_plan_approved(self):
        state = journey.start("inspect", transport="local")
        state = finish(state, "host")
        state = finish(state, "workspace")
        state = answer(state, "plan_confirm", True)
        with self.assertRaises(ValueError):
            journey.transition(state, {"type": "preview_preference", "enabled": False})

    def test_answer_must_match_current_question(self):
        state = journey.start()
        with self.assertRaises(ValueError):
            answer(state, "read_device", True)
        with self.assertRaises(ValueError):
            journey.transition(state, {"type": "result", "step": "rootfs_build",
                                       "state": "complete"})
        state = finish(state, "host")
        state = finish(state, "workspace")
        with self.assertRaises(ValueError):
            answer(state, "goal", "unsupported")

    def test_state_transition_has_no_in_place_mutation(self):
        original = journey.start("image", "virtual-machine")
        changed = finish(original, "host")
        self.assertEqual(original["steps"], {})
        self.assertEqual(changed["steps"], {"host": "complete"})

if __name__ == "__main__":
    unittest.main()
