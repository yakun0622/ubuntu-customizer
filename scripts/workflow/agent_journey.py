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

def _validate_interface_display(value, transport):
    """A human-readable, nonsecret summary; never a shell command."""
    if (not isinstance(value, str) or not value.strip()
            or len(value) > 180 or any(ord(ch) < 32 for ch in value)
            or "://" in value or "@" in value.split(":")[0]):
        raise ValueError("Provide a short interface label, not credentials or a URL")
    if transport == "ttl" and "/dev/" not in value:
        raise ValueError("TTL plan must show an actual serial /dev/ interface")
    if transport == "ttl" and not any(len(t) >= 4 and t.isdecimal()
                                       for t in value.replace("(", " ").replace(")", " ")
                                       .replace("（", " ").replace("）", " ").split()):
        raise ValueError("TTL plan must show the selected serial baud rate")
    return value.strip()

TARGETS = ("virtual-machine", "physical-device")
TRANSPORTS = ("ssh", "adb", "ttl", "local")
INTERFACE_PROMPTS = {
    "ssh": "请选择已配置且可信任的 SSH Host 别名（由 Agent 在本机检查）",
    "adb": "请选择 adb devices 中已授权的设备序列号或已连接地址",
    "ttl": "请选择检测到的串口设备并确认波特率；串口须由 Agent 独占",
    "local": "确认在当前授权执行主机上采集本机信息",
}

STATES = ("complete", "blocked", "failed")
GUEST_CHECKS = (
    "linux_boot", "system_state", "cloud_init", "instance_id",
    "hostname", "machine_id", "ssh_host_keys", "ssh_service", "network"
)
# Each action is a fixed Skill helper, never a synthesized shell command.
ACTIONS = {
    "host": ("host_capabilities.inspect", "R0", "检查本机能力"),
    "workspace": ("project_workspace.prepare", "R1", "在当前项目创建 .venv 和私有 outputs 目录"),
    "collect": ("adaptive.run", "R0", "读取目标设备信息"),
    "analyze": ("dossier.verify_session", "R0", "验证并分析采集证据"),
    # Agent-owned conversation stage: ask missing OS/version/boot media/features one by one.
    # This is NOT a shell command or an implemented board image builder.
    "requirements": ("agent.conversation", "R0", "逐项确认目标系统、版本、启动介质和所需功能"),
    "physical_evidence": ("physical_verify.evaluate", "R0", "检查 ARM 启动日志及静态证据"),
    "arm_baseline": ("arm_baseline.acquire", "R1", "在项目 outputs 中下载并校验官方 ARM64 最小系统"),
    "arm_research": ("agent.research_board_sources", "R0", "从官方或可信上游研究启动组件与驱动，不扫描宿主机文件"),
    "arm_candidate": ("arm_candidate.stage", "R1", "创建包含基础 RootFS 和已验证板级组件的版本化候选目录"),
    "arm_preflight": ("arm_preflight.inspect", "R0", "在当前项目内核对基础系统、板级组件和 ext4 工具，不扫描宿主机"),
    "arm_build": ("arm_image_builder.build", "R1", "离线创建 USB FAT32/ext4 ARM 镜像并校验分区/哈希"),
    "arm_diagnose": ("arm_boot_diagnose.diagnose", "R0", "将串口启动证据关联到本轮 USB 镜像并提出下一版修复方向"),
    "image_inspect": ("image_inspect.inspect", "R0", "检查基础系统镜像"),
    "image_plan": ("image_plan.plan", "R0", "生成兼容性与安全阻断清单"),
    "recipe_preview": ("rootfs_builder.dry_run", "R0", "预览离线定制方案"),
    "rootfs_build": ("rootfs_builder.assemble", "R1", "构建离线镜像副本"),
    "bundle_verify": ("rootfs_builder.verify_bundle", "R0", "校验镜像和构建清单"),
    "qemu_verify": ("verify_first_boot.verify_first_boot", "R1", "隔离启动来宾健康验证"),
}

def start(goal=None, target=None, transport=None, interface_ready=None,
          interface_display=None):
    """Start only a conversational state, not a program/VM/device operation."""
    if goal is not None and goal not in GOALS:
        raise ValueError("Unsupported intent")
    if target is not None and target not in TARGETS:
        raise ValueError("Unsupported target")
    if transport is not None and transport not in TRANSPORTS:
        raise ValueError("Unsupported connection method")
    if interface_ready is not None and type(interface_ready) is not bool:
        raise ValueError("Invalid interface readiness")
    if transport is None and interface_ready is not None:
        raise ValueError("Connection method required before selecting interface")
    if interface_display is not None:
        if interface_ready is not True and transport != "local":
            raise ValueError("Interface must be ready before supplying its details")
        _validate_interface_display(interface_display, transport)
    return {
        "schema_version": 1, "goal": goal, "target": target,
        # A local-only observer is included in the approved execution plan.
        # The boolean never authorizes connection or starts a server by itself.
        "choices": {"transport": transport,
                    "interface_ready": True if transport == "local" else interface_ready,
                    "interface_display": ("本机" if transport == "local" else interface_display),
                    "preview": True, "source_ready": None, "run_boot": None,
                    "arm_revision": 1, "usb_log_ready": None},
        "consent": {"plan_confirm": None, "offline_build": None,
                    "isolated_vm_boot": None, "baseline_download": None},
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
        result["preview_approved"] = (state["choices"]["preview"] is True
                                      and state["consent"]["plan_confirm"] is True)
        result["transport"] = state["choices"]["transport"]
        result["interface_display"] = state["choices"]["interface_display"]
        result["output_root"] = "outputs"
        result["python_env"] = ".venv"
        result["start_preview_before_probes"] = result["preview_approved"]
        # Initial plan approval is standing consent for routine scoped device
        # diagnostics (host Python helpers and fixed remote read-only probes).
        # Do not ask again for each Python invocation or each device command.
        result["device_python_auto_run"] = state["consent"]["plan_confirm"] is True
        result["device_shell_auto_run"] = state["consent"]["plan_confirm"] is True
        result["per_command_user_confirmation"] = False
        result["device_command_scope"] = "verified-shell/read-only-diagnostics"
        result["separate_consent_still_required"] = [
            "flash_or_erase", "emmc_or_partition_write", "bootloader_or_firmware_write",
            "reboot_or_poweroff", "network_or_ssh_lockout", "privilege_escalation",
            "untrusted_or_destructive_command",
        ]
    if name == "arm_baseline":
        result["approval_required"] = "baseline_download"
        result["default_source"] = "ubuntu-base-24.04.5-arm64"
        result["no_local_source_search"] = True
        result["output_root"] = "outputs"
    if name in ("arm_candidate", "arm_build", "arm_diagnose"):
        result["revision"] = state["choices"]["arm_revision"]
        result["output_root"] = "outputs"
        result["boot_confirmed"] = False
    if name == "arm_preflight":
        result["output_root"] = "outputs"
        result["no_host_path_scan"] = True
    if name == "arm_build":
        result["approval_required"] = "offline_build"
        result["no_block_devices"] = True
        result["no_emmc_write"] = True
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
    for initial in ("host", "workspace"):
        current = _stage(state, initial)
        if current:
            return current
    if state["goal"] is None:
        return _ask("goal", "这次要做什么？", GOALS)
    if state["goal"] == "image" and state["target"] is None:
        return _ask("target", "要为虚拟机还是实际硬件制作系统？", TARGETS)
    if state["choices"]["transport"] is None:
        return _ask("transport", "请选择连接设备的方式：", TRANSPORTS)
    if state["choices"]["interface_ready"] is None:
        return _ask("interface_ready",
                    INTERFACE_PROMPTS[state["choices"]["transport"]],
                    (True, False), False)
    if state["choices"]["interface_ready"] is False:
        return {"kind": "pause", "reason": "Device interface is unavailable",
                "boot_confirmed": False}
    if state["choices"]["interface_display"] is None:
        return _ask("interface_display", "请提供实际连接接口（TTL 须包含串口路径及波特率），以便在执行方案中明确展示。", ())
    if state["consent"]["plan_confirm"] is None:
        result = _ask("plan_confirm",
                      "确认执行以下方案吗？确认后"
                      + ("启动本地监控页面，再" if state["choices"]["preview"] else "")
                      + "经所选接口建立已验证设备会话；确认一次后自动执行"
                      "设备诊断 Python 脚本和设备内只读 shell 命令，"
                      "不逐条请求授权。采集硬件/系统/启动证据后规划定制；"
                      "不会重启、改网、写盘或刷机。",
                      (True, False), False)
        result["plan"] = {
            "workspace": ".venv / outputs (初始化不连接目标设备)",
            "transport": state["choices"]["transport"],
            "connection": state["choices"]["interface_display"],
            "preview": ("127.0.0.1 动态端口（启动成功后提供实际 URL）"
                        if state["choices"]["preview"] else "用户选择关闭监控"),
            "steps": (("建立私有会话",)
                      + (("启动本地实时监控",) if state["choices"]["preview"] else ())
                      + ("只读采集", "校验证据", "评估系统定制需求及阻断")),
            "consent_scope": ("一次已验证设备连接及该会话内连续的只读诊断 Python / shell 命令"
                              + ("和本机回环监控" if state["choices"]["preview"] else "")
                              + "；不逐条询问命令授权；危险写入/重启/改网/刷机仍另行确认"),
            "standing_device_python_commands": True,
            "standing_device_shell_commands": True,
            "per_command_user_confirmation": False,
        }
        return result
    if state["consent"]["plan_confirm"] is False:
        return {"kind": "pause", "reason": "Execution plan not approved",
                "boot_confirmed": False}
    for name in ("collect", "analyze"):
        current = _stage(state, name)
        if current:
            return current
    if state["goal"] != "image":
        return {"kind": "done", "result": "device_evidence_only",
                "boot_confirmed": False, "automatic": False}
    current = _stage(state, "requirements")
    if current:
        return current
    if state["target"] == "physical-device":
        # A physical ARM build starts from a pinned official minimal userspace,
        # not from scanning the user's disks for an unknown ready-made image.
        if state["consent"]["baseline_download"] is None:
            return _ask("baseline_download",
                        "允许仅从 Ubuntu 官方地址下载经固定 SHA-256 校验的 ARM64 最小 RootFS 到 ./outputs 吗？",
                        (True, False), False)
        if state["consent"]["baseline_download"] is False:
            return {"kind": "pause", "result": "baseline_download_declined",
                    "reason": "No automatic local image search or fallback",
                    "boot_confirmed": False}
        for name in ("arm_baseline", "arm_research", "arm_candidate", "arm_preflight"):
            current = _stage(state, name)
            if current:
                return current
        if state["consent"]["offline_build"] is None:
            return _ask("offline_build",
                        "允许在 ./outputs 内离线创建新的 FAT32/ext4 USB 镜像候选版本吗？不触碰实体磁盘。",
                        (True, False), False)
        if state["consent"]["offline_build"] is False:
            return {"kind": "pause", "result": "arm_offline_build_declined",
                    "boot_confirmed": False}
        current = _stage(state, "arm_build")
        if current:
            return current
        if state["choices"]["usb_log_ready"] is None:
            return _ask("usb_log_ready",
                        "当前版本 USB 启动测试完成、串口日志已保存在项目 outputs 内了吗？",
                        (True, False), False)
        if state["choices"]["usb_log_ready"] is False:
            return {"kind": "pause", "result": "usb_boot_log_required",
                    "next_action": "capture_usb_boot_log_without_writing_emmc",
                    "boot_confirmed": False}
        for name in ("physical_evidence", "arm_diagnose"):
            current = _stage(state, name)
            if current:
                return current
        return {"kind": "pause", "result": "arm_iteration_required",
                "next_action": "review_diagnosis_and_adapt_board_components",
                "revision": state["choices"]["arm_revision"],
                "physical_deployment_allowed": False,
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
    if state["consent"]["isolated_vm_boot"] is False:
        return {"kind": "done", "result": "artifact_verified_only",
                "boot_confirmed": False, "automatic": False}
    if state["consent"]["isolated_vm_boot"] is None:
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
        if field == "interface_display":
            updated["choices"]["interface_display"] = _validate_interface_display(
                value, state["choices"]["transport"])
            return updated
        if value not in current["options"] or (type(value) is bool) != (
                type(current["options"][0]) is bool):
            raise ValueError("Invalid choice for current question")
        if field in ("goal", "target"):
            updated[field] = value
        elif field == "transport":
            updated["choices"]["transport"] = value
            updated["choices"]["interface_ready"] = True if value == "local" else None
            updated["choices"]["interface_display"] = "本机" if value == "local" else None
        elif field in updated["choices"]:
            updated["choices"][field] = value
        elif field in updated["consent"]:
            updated["consent"][field] = value
        else:
            raise ValueError("Unexpected decision")
    elif typ == "preview_preference":
        if current["kind"] != "ask" or current["field"] != "plan_confirm":
            raise ValueError("Preview preference can only change at plan review")
        if type(event.get("enabled")) is not bool:
            raise ValueError("Preview preference must be a boolean")
        updated["choices"]["preview"] = event["enabled"]
    elif typ == "result":
        step = event.get("step")
        result = event.get("state")
        if current["kind"] != "run" or current["step"] != step or result not in STATES:
            raise ValueError("Tool result is out of sequence or invalid")
        if step == "arm_baseline" and updated["consent"]["baseline_download"] is not True:
            raise ValueError("Missing pinned baseline download consent")
        if step == "arm_build" and updated["consent"]["offline_build"] is not True:
            raise ValueError("Missing offline ARM image approval")
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
    elif typ == "usb_boot_log_available":
        if (current["kind"] != "pause" or current.get("result") != "usb_boot_log_required"):
            raise ValueError("USB log update is allowed only after an ARM candidate is built")
        updated["choices"]["usb_log_ready"] = True
    elif typ == "iterate_arm":
        if (state.get("target") != "physical-device" or
                not (current["kind"] == "pause" and current.get("result") == "arm_iteration_required"
                     or current["kind"] == "halt"
                     and current.get("step") in ("arm_research", "arm_candidate", "arm_preflight",
                                                 "arm_build", "physical_evidence", "arm_diagnose"))):
            raise ValueError("ARM iteration requires a completed or blocked ARM stage")
        if updated["choices"]["arm_revision"] >= 9999:
            raise ValueError("ARM revision limit reached")
        updated["choices"]["arm_revision"] += 1
        for stage in ("arm_research", "arm_candidate", "arm_preflight",
                      "arm_build", "physical_evidence", "arm_diagnose"):
            updated["steps"].pop(stage, None)
        updated["consent"]["offline_build"] = None
        updated["choices"]["usb_log_ready"] = None
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
