"""Conversation-first, resumable *decision policy* for the AI Agent Skill.

This is NOT a user-facing CLI or an execution daemon. The conversational
Agent calls next_step() after each tool result and asks only at meaningful
decision/approval boundaries. No machine access, process execution, network,
filesystem write or implicit consent occurs in this module.

The real execution safety gates in adaptive.py, image_plan.py,
rootfs_builder.py and verify_first_boot.py remain independently mandatory.
"""
from copy import deepcopy

GOALS = ("inspect", "diagnose", "image", "maintain")
TARGETS = ("virtual-machine", "physical-device")
STATES = ("complete", "blocked", "failed")
GUEST_CHECKS = (
    "linux_boot", "system_state", "cloud_init", "instance_id",
    "hostname", "machine_id", "ssh_host_keys", "ssh_service", "network"
)
# Each action is a fixed Skill helper, never a synthesized shell command.
ACTIONS = {
    "host": ("host_capabilities.inspect", "R0", "检查本机能力"),
    "collect": ("adaptive.run", "R0", "读取目标设备信息"),
    "analyze": ("dossier.verify_session", "R0", "验证并分析采集证据"),
    "physical_evidence": ("physical_verify.evaluate", "R0", "检查 ARM 启动日志及静态证据"),
    "image_inspect": ("image_inspect.inspect", "R0", "检查基础系统镜像"),
    "image_plan": ("image_plan.plan", "R0", "生成兼容性与安全阻断清单"),
    "recipe_preview": ("rootfs_builder.dry_run", "R0", "预览离线定制方案"),
    "rootfs_build": ("rootfs_builder.assemble", "R1", "构建离线镜像副本"),
    "bundle_verify": ("rootfs_builder.verify_bundle", "R0", "校验镜像和构建清单"),
    "qemu_verify": ("verify_first_boot.verify_first_boot", "R1", "隔离启动来宾健康验证"),
}

def start(goal=None, target=None):
    """Start only a conversational state, not a program/VM/device operation."""
    if goal is not None and goal not in GOALS:
        raise ValueError("Unsupported intent")
    if target is not None and target not in TARGETS:
        raise ValueError("Unsupported target")
    return {
        "schema_version": 1, "goal": goal, "target": target,
        "choices": {"preview": None, "source_ready": None, "run_boot": None},
        "consent": {"read_device": None, "offline_build": None, "isolated_vm_boot": None},
        "steps": {}, "boot_confirmed": False,
    }

def _ask(name, prompt, options, default=None):
    return {"kind": "ask", "field": name, "question": prompt,
            "options": list(options), "default": default,
            "automatic": False}

def _action(name, state):
    helper, risk, description = ACTIONS[name]
    result = {"kind": "run", "step": name, "helper": helper, "risk": risk,
              "description": description, "automatic": True}
    if name == "collect":
        result["preview_approved"] = state["choices"]["preview"] is True
    if name == "rootfs_build":
        result["approval_required"] = "offline_build"
    if name == "qemu_verify":
        result["approval_required"] = "isolated_vm_boot"
    return result

def _stage(state, name):
    value = state["steps"].get(name)
    if value in ("blocked", "failed"):
        return {"kind": "halt", "step": name, "reason": "Tool reported " + value,
                "automatic": False, "can_retry": True,
                "boot_confirmed": False}
    return None if value == "complete" else _action(name, state)

def next_step(state):
    """Return exactly ONE actionable next task or ONE short interaction."""
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("Invalid Agent Skill workflow state")
    for field in ("choices", "consent", "steps"):
        if not isinstance(state.get(field), dict):
            raise ValueError("Missing workflow state: " + field)
    current = _stage(state, "host")
    if current:
        return current
    if state["goal"] is None:
        return _ask("goal", "这次要做什么？", GOALS)
    if state["goal"] == "image" and state["target"] is None:
        return _ask("target", "要为虚拟机还是实际硬件制作系统？", TARGETS)
    if state["choices"]["preview"] is None:
        return _ask("preview", "要开启可选的本地实时预览页面吗？", (True, False), False)
    if state["consent"]["read_device"] is None:
        return _ask("read_device", "允许 Agent 连接所选设备，仅执行只读信息采集吗？",
                    (True, False), False)
    if state["consent"]["read_device"] is False:
        return {"kind": "pause", "reason": "Read-only device access not approved",
                "boot_confirmed": False}
    for name in ("collect", "analyze"):
        current = _stage(state, name)
        if current:
            return current
    if state["goal"] != "image":
        return {"kind": "done", "result": "device_evidence_only",
                "boot_confirmed": False, "automatic": False}
    if state["target"] == "physical-device":
        current = _stage(state, "physical_evidence")
        if current:
            return current
        return {"kind": "done", "result": "physical_evidence_only",
                "physical_deployment_allowed": False,
                "missing_gates": ("board_BSP", "bootloader", "DTB", "recovery",
                                  "authenticated_boot_health"),
                "boot_confirmed": False, "automatic": False}
    if state["choices"]["source_ready"] is None:
        return _ask("source_ready",
                    "请提供已有镜像，或选择由 Agent 获取并校验可信镜像。",
                    ("local-verified", "trusted-download"))
    for name in ("image_inspect", "image_plan", "recipe_preview"):
        current = _stage(state, name)
        if current:
            return current
    if state["consent"]["offline_build"] is None:
        return _ask("offline_build",
                    "兼容性检查已通过。是否允许生成新的离线镜像副本？",
                    (True, False), False)
    if state["consent"]["offline_build"] is False:
        return {"kind": "done", "result": "plan_only",
                "boot_confirmed": False, "automatic": False}
    for name in ("rootfs_build", "bundle_verify"):
        current = _stage(state, name)
        if current:
            return current
    if state["choices"]["run_boot"] is None:
        return _ask("run_boot", "要使用隔离 QEMU 验证首次启动吗？可跳过。",
                    (True, False), False)
    if state["choices"]["run_boot"] is False:
        return {"kind": "done", "result": "artifact_verified_only",
                "boot_confirmed": False, "automatic": False}
    if state["consent"]["isolated_vm_boot"] is not True:
        return _ask("isolated_vm_boot",
                    "允许启动一次隔离的临时虚拟机进行健康验证吗？",
                    (True, False), False)
    current = _stage(state, "qemu_verify")
    if current:
        return current
    return {"kind": "done", "result": (
        "guest_health_verified" if state["boot_confirmed"] else "boot_unverified"),
        "boot_confirmed": state["boot_confirmed"], "automatic": False}

def _guest_verified(report):
    """Never accept a partial checker report or a QEMU exit code as boot proof."""
    return (isinstance(report, dict) and
            report.get("type") == "ubuntu-customizer/first-boot-health" and
            report.get("status") == "passed" and
            report.get("boot_confirmed") is True and
            report.get("first_boot_confirmed") is True and
            isinstance(report.get("checks"), dict) and
            set(report["checks"]) == set(GUEST_CHECKS) and
            all(value is True for value in report["checks"].values()))

def transition(state, event):
    """Apply a user answer or an observed tool outcome; return new state.

    This does not perform any work. A result must match the requested stage.
    A failed/blocked stage cannot be bypassed by reporting later success
    without an explicit retry event.
    """
    if not isinstance(event, dict):
        raise ValueError("Event must be an object")
    current = next_step(state)
    updated = deepcopy(state)
    typ = event.get("type")
    if typ == "answer":
        field, value = event.get("field"), event.get("value")
        if current["kind"] != "ask" or field != current["field"]:
            raise ValueError("Answer does not match the current question")
        if value not in current["options"] or (type(value) is bool) != (
                type(current["options"][0]) is bool):
            raise ValueError("Invalid choice for current question")
        if field in ("goal", "target"):
            updated[field] = value
        elif field in updated["choices"]:
            updated["choices"][field] = value
        elif field in updated["consent"]:
            updated["consent"][field] = value
        else:
            raise ValueError("Unexpected decision")
    elif typ == "result":
        step = event.get("step")
        result = event.get("state")
        if current["kind"] != "run" or current["step"] != step or result not in STATES:
            raise ValueError("Tool result is out of sequence or invalid")
        if step == "rootfs_build" and updated["consent"]["offline_build"] is not True:
            raise ValueError("Missing offline build approval")
        if step == "qemu_verify" and updated["consent"]["isolated_vm_boot"] is not True:
            raise ValueError("Missing virtual machine approval")
        if step == "qemu_verify" and result == "complete":
            updated["boot_confirmed"] = _guest_verified(event.get("health_report"))
        updated["steps"][step] = result
    elif typ == "retry":
        step = event.get("step")
        if current["kind"] != "halt" or current["step"] != step:
            raise ValueError("Only the current blocked/failed step may be retried")
        updated["steps"].pop(step)
        updated["boot_confirmed"] = False
    elif typ == "skip_boot":
        if current["kind"] != "halt" or current["step"] != "qemu_verify":
            raise ValueError("Only a blocked optional QEMU test can be skipped")
        updated["steps"].pop("qemu_verify")
        updated["choices"]["run_boot"] = False
        updated["boot_confirmed"] = False
    else:
        raise ValueError("Unsupported workflow event")
    return updated
