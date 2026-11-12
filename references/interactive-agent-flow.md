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

## User experience

The four mandatory phases are **connection choice → plan review/confirmation
→ start verified live monitor and collect → stepwise customization**.

1. **Start** — The user says “开始定制系统”. Agent observes only local
   host capabilities it can really access, then automatically prepares
   `.venv` and `outputs` in the current directory. Reuse the known
   purpose/target.
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
   pauses all device activity. This plan approval is read-only R0 scope
   and includes launching a localhost viewer; it never authorizes
   reboot/shutdown, network changes, disk writes or flashing.
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

- The first step is a read-only `host_capabilities.inspect` observation,
  immediately followed by a project-local `project_workspace.prepare`
  action (before transport selection), requiring actual host execution access
  but no additional *user conversation* prompt.
- Then select `transport` and `interface_ready`, strictly before
  requesting `plan_confirm`. The Agent stores concrete ports, IPs,
  addresses and baud separately in its private runtime, not the policy state.
- `plan_confirm=True` authorizes the displayed read-only session and
  local observer; a `collect` result is otherwise out of sequence.
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
