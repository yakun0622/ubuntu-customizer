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
        state = journey.start("image", target, transport, True)
        state = finish(state, "host")
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
        self.assertEqual(journey.next_step(state)["field"], "goal")

    def test_only_one_question_at_each_missing_choice(self):
        state = journey.start()
        state = finish(state, "host")
        state = answer(state, "goal", "image")
        self.assertEqual(journey.next_step(state)["field"], "target")
        state = answer(state, "target", "virtual-machine")
        self.assertEqual(journey.next_step(state)["field"], "transport")
        state = answer(state, "transport", "ttl")
        self.assertEqual(journey.next_step(state)["field"], "interface_ready")
        state = answer(state, "interface_ready", True)
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        plan = journey.next_step(state)["plan"]
        self.assertEqual(plan["transport"], "ttl")
        self.assertIn("127.0.0.1", plan["preview"])
        state = answer(state, "plan_confirm", True)
        task = journey.next_step(state)
        self.assertEqual(task["step"], "collect")
        self.assertTrue(task["preview_approved"])
        self.assertTrue(task["start_preview_before_probes"])

    def test_decline_device_access_halts_without_collection(self):
        state = journey.start("inspect", transport="local")
        state = finish(state, "host")
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

    def test_physical_arm_skips_qemu_and_build_even_with_evidence(self):
        state = self.ready("physical-device")
        self.assertEqual(journey.next_step(state)["step"], "physical_evidence")
        state = finish(state, "physical_evidence")
        next_task = journey.next_step(state)
        self.assertEqual(next_task["result"], "physical_evidence_only")
        self.assertFalse(next_task["physical_deployment_allowed"])
        self.assertFalse(next_task["boot_confirmed"])

    def test_blocked_stage_must_be_explicitly_retried_or_optional_boot_skipped(self):
        state = self.ready()
        state = answer(state, "source_ready", "local-verified")
        state = finish(state, "image_inspect", "blocked")
        self.assertEqual(journey.next_step(state)["kind"], "halt")
        with self.assertRaises(ValueError):
            finish(state, "image_plan")
        state = journey.transition(state, {"type": "retry", "step": "image_inspect"})
        self.assertEqual(journey.next_step(state)["step"], "image_inspect")

    def test_missing_connection_is_not_silently_assumed(self):
        state = journey.start("inspect")
        state = finish(state, "host")
        self.assertEqual(journey.next_step(state)["field"], "transport")
        state = answer(state, "transport", "adb")
        self.assertEqual(journey.next_step(state)["field"], "interface_ready")
        with self.assertRaises(ValueError):
            answer(state, "plan_confirm", True)
        state = answer(state, "interface_ready", False)
        self.assertEqual(journey.next_step(state)["kind"], "pause")

    def test_known_ttl_target_skips_repeated_connection_questions(self):
        state = journey.start("image", "physical-device", "ttl", True)
        state = finish(state, "host")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        with self.assertRaises(ValueError):
            finish(state, "collect")
        state = answer(state, "plan_confirm", True)
        self.assertEqual(journey.next_step(state)["transport"], "ttl")
        self.assertTrue(journey.next_step(state)["preview_approved"])

    def test_local_interface_is_implicit_and_monitor_uses_plan_consent(self):
        state = journey.start("inspect", transport="local")
        state = finish(state, "host")
        self.assertEqual(journey.next_step(state)["field"], "plan_confirm")
        state = answer(state, "plan_confirm", True)
        self.assertTrue(journey.next_step(state)["preview_approved"])

    def test_explicit_monitor_opt_out_keeps_readonly_collection(self):
        state = journey.start("inspect", transport="local")
        state = finish(state, "host")
        state = journey.transition(state, {"type": "preview_preference", "enabled": False})
        self.assertIn("关闭监控", journey.next_step(state)["plan"]["preview"])
        state = answer(state, "plan_confirm", True)
        task = journey.next_step(state)
        self.assertEqual(task["step"], "collect")
        self.assertFalse(task["preview_approved"])

    def test_preview_preference_cannot_change_after_plan_approved(self):
        state = journey.start("inspect", transport="local")
        state = finish(state, "host")
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
        with self.assertRaises(ValueError):
            answer(state, "goal", "unsupported")

    def test_state_transition_has_no_in_place_mutation(self):
        original = journey.start("image", "virtual-machine")
        changed = finish(original, "host")
        self.assertEqual(original["steps"], {})
        self.assertEqual(changed["steps"], {"host": "complete"})

if __name__ == "__main__":
    unittest.main()
