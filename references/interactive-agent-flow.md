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

## User experience

1. **Start** — User says “开始” or chooses a “开始设备定制” follow-up.
   The Agent examines available current-host tools without changing anything.
2. **Narrow choice** — Only ask for intent/target if not established by the
   conversation. For example: “要检查设备，还是制作系统镜像？”
3. **Optional preview** — Ask once whether to show a live local progress page.
   Default is **off**. No preview is necessary for the Skill to function.
4. **Read-only consent** — Before SSH/ADB/serial access, show the target and
   request read-only collection permission. Never silently connect.
5. **Automatic work** — Collect/verify device evidence, select the best
   available single-host backend, inspect the source image, and produce
   compatibility decisions without making the user select CLI commands.
   Present short factual checkpoints; if a tool is absent, propose the single
   least disruptive next option and ask whether to proceed.
6. **Offline build consent** — Present input hash, output location, concrete
   file changes, compatibility blockers and reversibility; obtain distinct
   explicit approval for a new image build.
7. **Optional boot verification** — Ask whether to run an isolated VM test.
   The default is **no**. QEMU is an adapter, not a mandatory Skill stage.
8. **Deliver** — Report artifact paths, verified checksums, real test status,
   known risks, missing BSP/boot details, and one specific follow-up button.

Never ask for all decisions in one form. One question at a time, only when
a decision is needed. If evidence is already in the conversation, do not
ask for it again. “开始” is NOT consent to connect, install packages,
create disk images, boot a VM, change a system or flash a device.

## Supported choices behind the scenes

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

The small pure planning module \`scripts/workflow/agent_journey.py\` offers
\`start(goal=None, target=None)\`, \`next_step(state)\` and
\`transition(state, event)\`. These return structured descriptions of the
next **one** action or question. They do not execute operations, create
files, connect to devices or grant permissions. The host Agent may keep this
minimal state in its session to resume a multi-turn conversation.

- The first step is a read-only \`host_capabilities.inspect\` observation.
- The Agent may perform a \`kind=run\` step when it has an appropriate
  real execution tool and the needed approved inputs.
- For \`kind=ask\`, the Agent asks one conversational question; the user's
  explicit answer sets only that named choice/consent.
- \`kind=halt\` preserves the actual failure/blocker and asks the user
  whether to retry or choose a supported alternate path. Never fabricate
  success to advance.
- \`kind=pause\` means permission was denied; no device probe is run.
- \`kind=done\` means the current scope is complete. Physical evidence
  and static-image results never imply a verified device boot.

The helper's state carries *only* stages, choices, consents and a verified
guest-boot boolean. Do not store SSH aliases, captured serial text, paths,
tokens, passwords, keys, IP or MAC identifiers in the planning state.
Concrete evidence lives in the existing private session manifest files.

Example of conceptual transition (not something a user must run):

~~~text
“开始定制系统”
  → Agent: [checks host locally, if execution is permitted]
  → Agent: “要制作虚拟机镜像，还是给实体设备使用？” [only if unknown]
  → User: “实体设备”
  → Agent: “允许只读连接设备采集信息吗？”
  → User: “允许”
  → Agent: [collect → verify hashes → diagnose → passive boot log review]
  → Agent: “已有启动日志证据。板级固件/DTB 未验证，暂不刷写。”
  → Agent: [summarize + one specific next-step button]
~~~

For a VM workflow, after automatic image inspection/plan and recipe
preview, the Agent separately asks **“是否允许离线生成镜像副本？”**.
Only after that consent may it invoke the rootfs backend with the actual
\`--approved\` safeguard. After the new image is checksum-verified it asks
**“是否启动一次隔离虚拟机验证？”**; a no skips QEMU, and a yes
requires the separate boot approval and supported Guest Agent/firmware
requirements. A QEMU process exit is never itself boot evidence.

## Verification backends

\`verify_backend.py\` exposes \`static-image\`, \`arm-boot-log\` and
\`qemu-health\` as **Agent-owned** choices. The ARM adapter never writes
the device or infers a successful boot from UART logs; it can record
kernel/userspace/link and panic evidence for human interpretation.
Only a complete challenge-bound QEMU Guest Agent health report can label
an AMD64 virtual guest boot confirmed. Neither result approves a physical
firmware flash or skips BSP/DTB/recovery checks.

## Failure/stop handling

On interruption, preserve the current stage and consent decisions in
the conversation; do not retry high-impact steps without renewed review
of source and output. Do not run later steps when an earlier stage is
\`blocked\` or \`failed\`. An explicit \`retry\` resets only that stage,
not the risk boundary. A user may skip an optional failed QEMU test and
finish with \`boot_confirmed=false\`. A blocked physical BSP remains
blocked regardless of workflow completion.

## Agent developer test (not a user prerequisite)

~~~bash
python3 -m unittest discover -s tests -p 'test_agent_journey.py' -v
python3 -m unittest discover -s tests -v
~~~

The first command checks the pure conversational policy, not actual
hardware access. The second checks available Python unit tests. A real
single-host Linux/QEMU build is a separate test requiring a prepared
local execution environment and explicit user approval.
