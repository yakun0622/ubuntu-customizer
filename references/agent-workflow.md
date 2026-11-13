# Agent-led workflow contract


## Single-sentence startup and conversational orchestration

**Primary entrypoint: the user's phrase “开始定制系统” / “开始检查设备”.**
The Agent first asks the user to grant **local host** and **target device**
permissions independently (`none`, `read`, `read-write`) for this
specific task. **Nothing is inspected, downloaded or executed before
these decisions.** Local read permits project-local host inspection; only
local read-write permits creating/reusing `./.venv`, `./outputs`, editing
project files and constructing NEW outputs-only offline images. Target
read permits verified diagnostics; target read-write additionally covers
only supported reviewed reversible ordinary changes, never arbitrary
Shell commands or hazardous device writes. After these two grants,
the Agent selects/validates the target connection, confirms the overall
plan once and continues inside that scope without per-command prompts.
Host/tool sandbox prompts cannot be waived.
The Agent then follows the pure next-step policy. Do
not dump a CLI tutorial, display a multi-field form or require the user to
choose Lima, libguestfs, QEMU or a device transport command.

The Agent asks for only one missing decision at a time. A newly requested
device session follows a fixed order: **local read/write grant → target
read/write grant → approved host/workspace setup → connection method →
corresponding interface → complete reviewed plan and confirmation →
private session/live URL → evidence collection → requirement gathering →
supported customization actions**. An approved plan authorizes both a
localhost-only preview and one scoped read-only device connection. It does
NOT authorize offline image construction, QEMU boot, target power control,
network changes or physical device writes; those remain separate consents.

For a single Mac, an already-running local Lima Linux VM may be used as a
backend when host tools and file shares are available. If no local computer
execution bridge exists, say so plainly and offer a single setup option.
Do not silently provision, start VMs, install packages or perform a physical
flash. For physical ARM boards, use authorized guarded interactive sessions or
passive UART/static evidence as appropriate; keep BSP/bootloader/DTB/recovery
checks blocked regardless of shell availability.

See `references/interactive-agent-flow.md` for the resumable states,
tool-result handling, pause/retry behavior, evidence claims and the
sample user experience. CLI snippets elsewhere are **internal tools**,
not the user's workflow.

The repository implements an **AI Agent Skill**, not a standalone control panel.
The conversational Agent owns workflow state, chooses scripts only when needed,
interprets evidence and pauses for user decisions. Scripts are disposable helpers;
their CLI prompts are not the primary user interface.

## Device diagnostics: standing authorization after one confirmed plan

The exact connection/endpoint and overall diagnostics plan are confirmed
**once**. After that the Agent must automatically execute project-local
Python device helpers and supported read-only commands inside the verified
device shell, without asking the user to authorize every Python invocation
or every device-internal shell command. Continue analysis/probing in the
same session. Existing fixed allowlists, prompt checks and evidence
boundaries still apply. Do not execute untrusted command strings.
Reboot/shutdown, lockout-risk network changes, privilege escalation,
eMMC/partition writes, firmware/U-Boot changes and other destructive
effects require independent review and risk-specific consent. Host-level
permission checks cannot be waived.

## Implemented scope and validation

The pure `agent_journey.py` policy does not execute tools or persist sessions.
Its inspect / diagnose / maintain goals currently finish with evidence analysis;
separate task/profile planners do not apply changes. Recovery and rollback
execution are unsupported. The VM image path includes inspection, conversion,
limited RootFS customization and optional AMD64 guest-health verification.
Python tests passed on macOS; real device collection, image builds, guest
boots, Lima execution and full Agent handoffs remain unverified. See the
[capability matrix and validation record](roadmap.md).

## Stages and required handoffs

### 0. First ask permissions, then prepare the workspace
- Before running any host or target command, ask for this task's
  **local `none/read/read-write`** and **target `none/read/read-write`**
  scopes. Neither is inferred from OS login privileges or a previous task.
- If local read is denied, do not even inspect host capabilities. Local
  read allows host inspection; local read-write permits creating `.venv`,
  `outputs`, editing project code and NEW offline image outputs. With
  read-only, pause before the writer/collector rather than escalating.
- With local RW granted, work from the current repository and run
  `python3 -B scripts/workflow/project_workspace.py` without another
  user prompt.
- Use `./.venv/bin/python -B` for Python helpers without project-root bytecode cache (on Windows,
  `./.venv/Scripts/python.exe`). The helper does not install packages.
- Keep all persistent runtime artifacts under `./outputs/`, with private
  device sessions and logs. Use the workspace path validator; do not
  override output destinations outside the project.
- Safe local inspection, tracked source edits, local tests and creating
  new files under outputs are already approved as routine workspace work.
  Do not repeat approvals for each command. Host/OS policy still applies.

### 1. Goal, connection method and exact interface
- Infer the user's goal and physical/VM target from the conversation.
- If no connection mode is known, offer SSH, ADB, TTL (managed picocom) or local.
- After selecting the mode, discover or ask for its matching actual interface:
  trusted SSH Host alias; authorized ADB serial/address; observed /dev serial
  port with baud rate; or the authorized local control machine.
- Reuse already-known choices; never silently invent a port/address.
- Populate the reviewed plan with the **actual endpoint**, not a generic
  readiness assertion. TTL plans display the chosen `/dev/` port and baud;
  plan approval is blocked until that summary is present.
- Existing picocom and the managed adapter must not own the same serial port concurrently.
- Recovery can be assessed and planned, but has no execution backend or
  dedicated goal in the pure policy.

### 2. Explain scope and request plan approval
- Show the exact connection, hardware/OS/boot/storage/network probes,
  local-only live dashboard, evidence privacy, staged workflow and limits.
- Wait for explicit confirmation before opening any device connection.
- The startup grants cover local and device access for this task. The
  later plan confirmation binds the target grant to the exact endpoint,
  enabling the scoped diagnostic session/monitor and safe Python/remote
  shell commands without per-command approval. Existing host RW plus
  confirmed plan permits new outputs-only offline builds, without a
  duplicate `offline_build` question.
- No generic permission authorizes reboot/shutdown, target writes or
  flashing. Running a command *from* the project directory does not
  authorize its external or destructive side effects.

### 3. Launch viewer before interactive discovery
- After approval, create the private session then start preview on loopback.
- For managed TTL/ADB/SSH use `adaptive.py --interactive-shell-approved
  --preview-approved --yes` (Agent supplies confirmed inputs). The old
  `manage.py collect` CLI shows the combined plan only once; monitor is
  included unless `--no-preview` is explicitly selected.
- The backend outputs a `preview_ready` line after readiness check and
  before probes; report ONLY the actual URL. If unavailable, say so.
- Use a persistent verified shell for interactive TTL/ADB/SSH; the old
  passive TTL recorder remains separate and sends no commands.
- Gather OS, architecture, firmware, boot mode, storage and hardware facts.
- Use `manifest.json` as the source of truth; retain errors/skips.

### 4. Evidence normalization
- Verify hashes before interpreting recorded evidence.
- Use `dossier.py`, `capabilities.py`, `topology.py`,
  `device_tree.py` and `link_graph.py` **only when the input evidence supports them**.
- The output is observed software topology, not guaranteed physical wiring.
- Show a short summary and explicit unknowns; ask user what to investigate or build.
- Offline HTML is optional presentation only, never the workflow coordinator.

### 5. Requirement gathering and image portability decision
- Based on validated facts, ask only for missing target OS/version, packages,
  functions, boot medium, storage and network expectations. This is an
  Agent-owned conversation stage, not executable device code.
- Select a target class before choosing image format:
  virtual machine/cloud image, installer ISO, or physical board image.
- See `references/image-building.md` for backend and safety constraints.
- Demand trusted input source, independent checksum, license and source architecture.
- Check firmware/bootloader, storage layout, kernel, drivers, DT/ACPI and recovery.
- Use `image_plan.py` to **propose**, never to certify boot compatibility.
- Installer ISO creation and physical IMG/BSP assembly have no implemented
  backend; the choices above do not imply those operations are available.
- For VM only, `build_image.py` can convert an existing image offline when
  the plan permits it. This does not migrate a running system or build a generic OS.
- For physical hardware, do not invoke a generic flashing or image builder:
  require a verified target adapter and explicit approval.
- Optional `nocloud.py` can make a first-boot seed for images already supporting
  cloud-init; it does not clean machine-specific state from the disk image.
- Optional `verify_vm.py` can check file metadata and run an explicitly
  requested isolated x86_64 QEMU smoke attempt. QEMU exit/timeout is not
  a successful guest boot assertion.

### 6. Approval, execution, verification
- Show planned operations, exact files, impact, recoverability and test criteria.
- Separate read-only inspection consent from image conversion, system changes,
  disk installation and flashing permissions. Routine project-local commands
  within the user's standing authorization do not need repeated dialogue
  prompts, but external host-tool safety prompts still apply.
- Never execute a blocked plan; do not bypass blockers by modifying plan JSON.
- Verify results from actual tool output, retain evidence and rollback details.
- Label untested code as untested. If execution access is missing, provide the
  exact script and explain what needs to be run on the user's host.

## Risk levels

- R0: passive read-only inspection and local interpretation
- R1: offline plans, data transforms, generated manifests
- R2: packages and ordinary service configuration (explicit approval)
- R3: SSH/network, kernel, firmware/DT changes (explicit recovery)
- R4: partitioning, device writes, flashing or installation (exact target and recovery)

## Prohibited shortcuts

- Do not infer physical pinout from DT nodes alone.
- Do not assume ARM64 Linux userspace implies firmware/board compatibility.
- Do not present raw-to-qcow2 conversion as successful image portability.
- Do not store credentials or automatically upload captured device data.
- The monitor is part of the approved workflow but remains an observational
  helper, not a required standalone product or remote command console.


### Portable RootFS customization (opt-in)

After evidence and `image-plan.json` are validated, prefer
`rootfs_builder.py --dry-run` to show the user fixed operations and missing
offline tools. The Agent must request separate consent for `--approved`,
and must not infer approval from read-only device collection or optional
preview consent. Only Linux VM/cloud images with cloud-init configuration
and matching guest/target evidence qualify. Physical device images are still
blocked pending independent BSP/bootloader/DTB/firmware/recovery validation.
Keep source images shut down and immutable; the builder operates exclusively
on a temporary clone and provides a new hash-verified artifact bundle.
Run `--verify-bundle`. Offer QEMU verification as a separate optional step;
if declined or unavailable, finish with artifact integrity only and guest
boot unverified. Do not suggest deployment readiness without the relevant
boot evidence. Document remaining identity/privacy limitations and any
undemonstrated cloud-init first boot.

### Live QEMU first-boot evidence (explicit approval)

After verifying the RootFS build bundle, offer an optional isolated
`verify_first_boot.py` run. Ask separately for permission to start the
local VM (do not reuse permission to collect device information, build
the disk image, or open a status preview). The verifier uses a snapshot,
restricted user-mode guest DHCP without host/Internet routing, a private
UNIX QEMU Guest Agent channel, and fixed read-only checks. Accept
`boot_confirmed=true` only when all per-check results pass and are
bound to a new challenge nonce. No QGA/UEFI support, unverified first
boot, timeouts or failures must remain blocked/failed. Consult
`references/first-boot-verification.md`.
