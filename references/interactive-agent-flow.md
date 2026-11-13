# Conversation-first Agent workflow (one-start, guided execution)

**The user starts by saying “开始定制系统” / “开始检查设备”.** They do not
need to know Python, SSH syntax, qemu-img, Lima, or a series of CLI commands.
This repository is an **AI Agent Skill**. The host Agent is the interface;
Python helpers are its trusted, scoped backend tools, not a second UI.

The Agent can only perform steps it actually has permission and execution
access to perform. A plain chat session without computer access must not
pretend that it connected to the user's Mac or ran an image builder. In that
case it explains the single missing prerequisite or uses an authorized
computer/remote connector. It does not dump a long manual command checklist.

## ARM source-first workflow and scope

Physical ARM journeys do **not** request the user to find an existing host
image. After device evidence and requirements they ask once for permission to
fetch the pinned official Ubuntu Base ARM64 rootfs, then run:
`arm_baseline` → `arm_research` (Agent source/driver research) →
`arm_candidate` (numbered local component staging) →
`physical_evidence` (serial/static boot evidence). The result remains
`arm_iteration_required` until a real board build/verification implementation
exists. The `iterate_arm` event creates another revision without repeating
the baseline download or initial device session. Never imply that a staged
RootFS tarball is bootable.

For local file inputs, accept only files inside the present project. No
implicit `~/Downloads`, `~/.ssh`, `/dev` enumeration, `/tmp` or
other-directory search. All new artifacts belong in `outputs`. A host
sandbox is required for an absolute, whole-process access guarantee.

## Physical ARM build/diagnose revisions (new executable handoffs)

The physical ARM stage continues after versioned component staging:
`arm_preflight` (project-local source/component/ext4 readiness) →
`offline_build` consent → `arm_build` using `arm_image_builder.build`
→ `usb_log_ready` choice → verified local physical boot evidence →
`arm_diagnose` linked to the exact candidate manifest/image SHA-256 →
`arm_iteration_required` (never deployment-ready by default).
When no current USB log exists, pause at `usb_boot_log_required`, not
`evidence_only`. On an `iterate_arm` event, increment revision, clear
prior board component / image / evidence / diagnosis completion, and request
offline-build authorization again. Reuse the pinned official RootFS.
There is no code path here that writes to an attached disk or eMMC.

The Agent may optionally compile a revisioned DTS/DTB with
`arm_dtb_adapter.py` during board research. All local inputs must be in
the current project; outputs in `outputs`. Distinguish `IMG built` from
`W152D USB boot successfully verified`. A serial screenshot or UART
marker alone does not prove authenticated live boot.

## Current-directory bootstrap and artifact rule

When an authorized local host execution bridge exists, **before asking for a
device connection** the Agent invokes
`python3 -B scripts/workflow/project_workspace.py` from the current repository
directory. It creates/reuses `.venv/`, creates private `outputs/` and
returns the interpreter path. All remaining Python helpers run in `.venv`.
No downloads, global installs or target contact are part of this step.

Every runtime output is a child of `./outputs/` (evidence sessions,
status/preview files, plans, artifacts, checksums, images, intermediate
downloads and test reports). Use `project_workspace.output_path` and
`checked_output` for untrusted path inputs. Source/document edits remain in
the tracked project; `.venv` is the sole environment directory exception.

**Local standing consent:** The Agent may inspect/edit source, create a
virtual environment, write new outputs and run safe project-local test
commands without individually asking the user. A project-relative working
directory does not make dangerous commands safe: device I/O, power cycling,
destructive deletes, package downloads/untrusted scripts, host networking,
privileged changes, VM boot and disk/image writes keep their specific
permission requirements. Host sandbox or OS prompts still apply; the Skill
cannot waive them.

## Task-start access declaration (before host or target commands)

At the start of every new Skill task, ask TWO separate permission levels,
in this order: **local host access** `none/read/read-write` (restricted
to the current repository) and **target device access**
`none/read/read-write` (restricted to the device/interface selected
for this task). These are not inferred from earlier user interactions.
No capability probe, Python script or device connection is executed before
the questions are answered.

A local `read` permits project inspection but not workspace creation,
`.venv` changes, evidence output or images; the workflow pauses before
`workspace` until local `read-write` is explicitly granted. A target
`read` permits diagnostics; target `read-write` preauthorizes only
supported reviewed reversible changes (with backup and verification).
The current device adapter remains fixed read-only. If either scope is
`none`, operations requiring that resource are blocked. A local RW
grant plus confirmed overall plan covers NEW outputs-only image builds;
do not ask for an additional `offline_build` dialogue every revision.

After collecting these two grants, resolve the connection method and
actual endpoint, show the planned operations and monitoring viewer, and
confirm the plan once. Continue within that scope without per-command
questions. Network downloads, VM boots and high-risk physical operations
keep their separate approvals. OS sandbox and device login/trust controls
remain independently enforced. The pure policy state is schema version 2
with `access.local` and `access.target`.

## Approved device session: automatic device Python and shell commands

Once the user confirms the exact connection and overall diagnostic plan
**once**, run project-local Python device scripts and successive supported
read-only commands **inside the verified SSH/ADB/TTL device** directly. Do
not ask for per-command permission or stop to make the user choose Python
flags. Continue collecting and interpreting evidence automatically until
the next real blocker. The consent covers the stated diagnostic scope,
not a different machine or destructive/disruptive operations.

The collection state advertises `device_python_auto_run=true`,
`device_shell_auto_run=true`, and
`per_command_user_confirmation=false`. The verified prompt and fixed
safe-probe allowlist remain mandatory; the user authorization does not
bypass host tool sandbox gates or permit reboot, network cutover,
privilege escalation, eMMC/partition/firmware writes or untrusted code.

## User experience

The mandatory phases are **local/target permission questions → approved
host/workspace setup → connection choice → reviewed plan confirmation →
verified live monitor and collection → stepwise customization**.

1. **Start with permission questions** — The user says “开始定制系统”.
   Ask local and target read/write levels *before inspecting the host*.
   With local read, host inspection may run; with local RW, prepare
   `.venv` and `outputs` in the current project. No actual device
   command before the target read grant and confirmed connection plan.
2. **Connection choice** — If no transport was named, ask one concise
   question offering SSH / ADB / TTL / local. After that choice, discover
   observed matching endpoints and let the user select the appropriate
   interface. SSH means a trusted Host alias; ADB an authorized serial or
   connected address; TTL an exact /dev path plus verified baud (only one
   owner at a time); local means the Agent's approved execution host.
   Reuse an already supplied interface instead of asking again. Store a
   nonsecret `interface_display` in the decision state; for TTL it must
   include an actual `/dev/` path and selected baud rate. Until supplied,
   `plan_confirm` cannot be offered.
3. **Explain and confirm** — Before any device connection, display the
   intended target and interface, connection details, fixed read-only probe
   scope, evidence retention, privacy, stage sequence, local live monitor
   and limitations. Ask once whether to approve this plan. Rejecting it
   pauses all device activity. This plan approval covers the whole R0 read-only device diagnostic
   session (Python and device shell, with no per-command prompts) plus
   the localhost viewer; it never authorizes reboot/shutdown, network
   changes, disk writes or flashing.
4. **Start monitor, then work** — After confirmation, create a private
   evidence session, start the loopback live viewer BEFORE shell probes,
   and provide the **actual** confirmed `http://127.0.0.1:<dynamic-port>/`
   URL. Do not invent URLs. The monitored SSH/ADB/TTL persistent collector
   emits a `preview_ready` event before probing. Browser reachability
   requires opening the address on the controlling host. If the server
   fails to start, explicitly report the blocker and use text progress.
   If preview was specifically declined, skip only that optional observer.
5. **Read-only discovery** — Run the permitted probe batch, inspect the
   session's SHA-256 evidence, and identify OS/kernel, architecture,
   storage, bootloader/BSP/DTB, drivers and real uncertainties.
6. **Gather customization requirements** — Ask about missing OS/version,
   boot media, services/packages, network behavior and validation only
   as they become relevant. Already provided details are not re-requested.
   This is the Agent's conversation stage, not a shell script.
7. **Stepwise implementation** — Present a feasible compatibility plan and
   carry out safe supported steps. A new image build, VM boot test or
   system/firmware write each needs separate appropriate consent. Physical
   ARM image production/flash remains blocked without a verified board
   adapter, source, backups and a recovery path.
8. **Deliver** — Report actual evidence/results, session and artifact
   references, real test outcomes, unknowns and one concrete next task.

Never use an all-at-once form. A plain chat without an execution bridge
must not pretend to connect to the user's Mac or launch a preview.
Likewise, a localhost link is NOT a public/remote URL.

## Supported choices behind the scenes

The choices below describe implemented adapters, not real-environment
validation. Python policy/adapter tests passed on macOS; actual device
collection, image builds, guest boots, Lima and full Agent handoffs remain
unverified. See the [validation record](roadmap.md#validation-record).

| Situation | Agent selects | What user sees |
| --- | --- | --- |
| Linux host with installed libguestfs/qemu-img | Native Linux image helpers | “正在检查本机环境与镜像” |
| Apple Silicon Mac with *already-running*, mounted, compatible Lima Linux VM | Local Lima adapter (same physical Mac) | “将在本机的 Linux 环境中处理镜像” |
| Mac lacking a usable local Linux environment | Pause, give single setup choice or use existing static evidence | “需要在本机准备镜像构建环境，是否配置？” |
| ARM physical board/TV box | Read-only session and physical boot-log adapter | “已获得启动证据；实体适配仍缺少 BSP 验证” |
| AMD64 virtual-machine image with explicit boot approval and guest support | Isolated QEMU Guest Agent verifier | “正在进行可选的首次启动检查” |
| Boot test unavailable or declined | Static verification only; mark guest boot unknown | “镜像文件已验证，启动尚未验证” |

Lima, qemu-img, SSH, and serial devices are not necessarily available in
the Agent runtime. The Agent must check real capabilities first; it may
propose installing dependencies only after separate approval. It must
**never** silently install, start a stopped Lima VM or create a container,
or assert local execution when the execution tool has not run.

## Implementation contract (Agent-side, no application frontend)

The small pure planning module `scripts/workflow/agent_journey.py` offers
`start(goal=None, target=None, transport=None, interface_ready=None, interface_display=None)`, `next_step(state)` and
`transition(state, event)`. These return structured descriptions of the
next **one** action or question. They do not execute operations, create
files, connect to devices or grant permissions. The host Agent may keep this
minimal state in its session to resume a multi-turn conversation.

This is not a persistent session store or executor. Its inspect / diagnose /
maintain paths currently end after collection and evidence analysis. Separate
task planners produce execution-disabled plans; maintenance, recovery and
rollback execution remain unsupported. The VM-image path alone continues
through recipe/build/optional guest-health stages. Physical-device image
requests end with evidence and blockers, without building or flashing.

- The first two steps are `local_access` then `target_access`
  (`none/read/read-write`) conversational grants with NO host/device I/O.
  After local read, `host_capabilities.inspect` may run; after local RW,
  `project_workspace.prepare` may create/reuse the project-local
  environment. No per-command repeats once granted.
- Then select `transport` and `interface_ready`, strictly before
  requesting `plan_confirm`. The Agent stores concrete ports, IPs,
  addresses and baud separately in its private runtime, not the policy state.
- `plan_confirm=True` authorizes the read-only device session,
  local observer and all supported Python/shell diagnostic commands with
  no per-command consent; a `collect` result is otherwise out of sequence.
- The `collect` action carries `preview_approved=True` so the
  backend starts the observer before running fixed probes.
- The Agent-owned `requirements` action is conversational: gather missing
  OS/version, boot medium and service needs, then record it complete.
- The Agent may perform a `kind=run` step only with real host execution
  tools and approved inputs. A `kind=ask` asks just one question.
- `kind=halt` preserves the actual failure/blocker and asks the user
  whether to retry or choose a supported alternate path. Never fabricate
  success to advance.
- `kind=pause` means permission was denied; no device probe is run.
- `kind=done` means the current scope is complete. Physical evidence
  and static-image results never imply a verified device boot.

The helper's state carries *only* stages, choices, consents and a verified
guest-boot boolean. Do not store SSH aliases, captured serial text, paths,
tokens, passwords, keys, IP or MAC identifiers in the planning state.
Concrete evidence lives in the existing private session manifest files.

Example of conceptual transition (not something a user must run):

~~~text
“开始定制系统”
  → Agent: [checks accessible host capabilities, read-only]
  → Agent: [creates/reuses .venv and outputs in the current project]
  → Agent: “设备怎么连接？SSH / ADB / TTL / 本机” [only if unknown]
  → User: “TTL”
  → Agent: “检测到 /dev/cu.wchusbserial1140，波特率 921600，使用它吗？”
  → User: “是”
  → Agent: [explains planned fixed probes, localhost viewer and safety]
  → Agent: “确认该只读连接和监控方案吗？”
  → User: “确认”
  → Agent: [creates private session → starts loopback observer]
  → Agent: “监控地址：http://127.0.0.1:<actual-port>/”
  → Agent: [collects read-only evidence → hashes/analysis]
  → Agent: [asks only for missing system/version/functions]
  → Agent: [compatibility plan → separately approved safe build steps]
~~~

For a VM workflow, after automatic image inspection/plan and recipe
preview, the Agent separately asks **“是否允许离线生成镜像副本？”**.
Only after that consent may it invoke the rootfs backend with the actual
`--approved` safeguard. After the new image is checksum-verified it asks
**“是否启动一次隔离虚拟机验证？”**; a no skips QEMU, and a yes
requires the separate boot approval and supported Guest Agent/firmware
requirements. A QEMU process exit is never itself boot evidence.

## Verification backends

`verify_backend.py` exposes `static-image`, `arm-boot-log` and
`qemu-health` as **Agent-owned** choices. The ARM adapter never writes
the device or infers a successful boot from UART logs; it can record
kernel/userspace/link and panic evidence for human interpretation.
Only a complete challenge-bound QEMU Guest Agent health report can label
an AMD64 virtual guest boot confirmed. Neither result approves a physical
firmware flash or skips BSP/DTB/recovery checks.

## Failure/stop handling

On interruption, preserve the current stage and consent decisions in
the conversation; do not retry high-impact steps without renewed review
of source and output. Do not run later steps when an earlier stage is
`blocked` or `failed`. An explicit `retry` resets only that stage,
not the risk boundary. A user may skip an optional failed QEMU test and
finish with `boot_confirmed=false`. A blocked physical BSP remains
blocked regardless of workflow completion.

## Agent developer test (not a user prerequisite)

~~~bash
./.venv/bin/python -B -m unittest discover -s tests -p 'test_agent_journey.py' -v
./.venv/bin/python -B -m unittest discover -s tests -v
~~~

The first command checks the pure conversational policy, not actual
hardware access. The second checks available Python unit tests. A real
single-host Linux/QEMU build is a separate test requiring a prepared
local execution environment and explicit user approval.
