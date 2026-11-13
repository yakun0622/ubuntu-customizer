# Ubuntu Customizer — Agent entrypoint

This repository implements an **AI Agent Skill**, not a CLI application.
Always read `SKILL.md` and `references/interactive-agent-flow.md` for
device customization, diagnostic, image build, or boot-verification requests.

## Mandatory ARM baseline-first and local filesystem isolation

- **Do not search the host for an image.** For ARM hardware, start from the
  pinned official Ubuntu Base ARM64 RootFS in `arm_baseline.py`, download
  only with explicit network consent, validate its SHA-256, then research
  the device's boot chain and stage versioned components with
  `arm_candidate.py`. Iterate instead of finishing at `evidence_only`.
- **All host-side file reads and writes must be inside the current project
  directory.** Only `outputs/` receives generated artifacts; `.venv/`
  is the local environment exception. Never inspect `~/Downloads`,
  `~/.ssh`, `/tmp`, `/dev` directory listings, sibling repos, or a
  source image in another path. No automatic local image search.
- Project-only checks cannot sandbox an arbitrary subprocess or prevent
  OS-managed library/config reads. Never promise strict whole-process
  confinement without an actual host sandbox. Direct TTL access to a
  selected `/dev` node needs separately approved hardware access; if the
  ban also includes all device nodes, do not open it.
- The new ARM baseline and candidate stage are concrete intermediate
  artifacts, not a bootable USB IMG. Full board assembly and verified USB
  boot remain pending real engineering and tests; never fake completion.

## ARM offline builder handoff (implemented candidate stage)

The physical-device image path includes real, guarded helpers:
`arm_baseline.acquire` → evidence/board research → optional
`arm_dtb_adapter.compile_dts` → `arm_candidate.stage` →
`arm_preflight.inspect` → **separately approved** `arm_image_builder.build` →
user-provided current-revision USB serial log →
`physical_verify.evaluate` → `arm_boot_diagnose.diagnose` → revise.

- Create only project-local regular IMG files under `outputs/arm-images/`;
  never discover/open host block devices, flash eMMC, run disk dd, mount a
  host disk or silently reboot a target.
- Never fabricate Kernel/DTB addresses or W152D U-Boot script compatibility.
  Extlinux and vendor-script are alternatives, not verified board defaults.
- The official Ubuntu Base archive is ARM64 *userspace*, not a finished
  system. The builder records missing init and real USB boot gates.
- FAT32 boot creation is now pure Python; the old mkfs.vfat/mtools path is optional.
  Ext4 still needs a project-local `mke2fs`, DTS compilation an optional `dtc`,
  and real OS sandboxing for strict process-wide access confinement.
  `arm_preflight.inspect` does not scan host PATH or external directories.
- Link each USB serial log to its exact candidate SHA-256 and revision.
  Failed boot automatically means diagnose/new iteration, not a claim of
  `boot_confirmed` or `deployment_allowed`.

## First step: ask local and target read/write permissions

Before running host capability inspection, preparing the venv, creating
outputs, opening SSH/ADB/TTL or invoking Python, ask two concise permission
questions for this **new task**:

- Local host: `none`, `read`, `read-write` for the current project only.
  Read permits inspection; read-write additionally covers tracked source
  edits, `.venv`, new files in `outputs/`, tests and NEW offline IMG builds
  within `outputs/`. If only read is granted, do not initialize or write
  workspace files. No blanket permission for other Mac directories.
- Target machine: `none`, `read`, `read-write` for the specific device
  selected later. Read allows ordinary diagnostic commands; read-write
  additionally preapproves supported, reviewed, reversible device
  configuration changes only when backup/rollback and verification exist.
  The implemented SSH/ADB/TTL collection adapter is still read-only; do
  not invent an unrestricted remote-write executor.

The two grants are per task, are not inferred from older conversations,
and must be applied **before any real operation**. Next show the exact
connection/endpoint/monitoring plan and confirm it once; subsequent
authorized project Python and verified device Shell commands proceed
without per-command prompts. Reuse local RW permission plus confirmed plan
for new offline outputs-only image builds, instead of another
`offline_build` permission dialogue on each candidate revision. Network
download and isolated-VM start remain separate authorizations.

Never treat general target RW as approval for eMMC/partition/firmware or
bootloader flashing, reboot/shutdown, network/SSH cutover, sudo/su, untrusted
code or destructive operations. Those require an action-specific review;
the implemented backend may not support them at all. Real host tool/OS
sandbox and target authentication cannot be overridden by Skill consent.

## Standing authorization after confirming the device plan

Once the user confirms the connection method, exact endpoint and overall
diagnostic plan, **run device-targeted Python helpers and supported read-only
commands inside that device directly, without asking permission for each
command**. Use the approved .venv Python for collection, monitoring, parsing,
network/DTB/boot logs and evidence checks. Reuse the verified SSH/ADB/TTL
shell and its fixed probe allowlist; process all safe diagnostic steps
without repeated conversation prompts.

The initial plan is the authorization boundary, **not every individual
command**. Host artifacts stay within `./outputs/`; never scan the Mac
outside the repository. Device-local `/proc` and `/sys` are not Mac paths.
The backend still blocks unknown serial consoles/U-Boot prompts and arbitrary
untrusted shell strings. Reboot/shutdown, eMMC or partition writes, network
loss, privilege escalation, firmware/U-Boot/kernel modifications and
destructive operations keep their independent approval/recovery boundaries.
Host sandbox permissions and SSH/ADB authentication cannot be bypassed.

## User-facing behavior

When the user says **“开始” / “开始定制系统” / “开始检查设备”**:

1. **Before any inspection or command, obtain the two task-start grants**
   (`local_access`, `target_access`: none/read/read-write). If local
   read is denied, do not inspect the host. If local RW is not granted, do
   not create `.venv` or `outputs`. After local RW is approved, inspect
   host capabilities and **automatically initialize/reuse .venv and outputs**
   with the project-local Python helper. Keep Python `-B` and never
   access files outside the current project. Infer goal/target from chat.
2. **Transport first.** If unspecified, ask the user to choose SSH, ADB,
   managed TTL/picocom or the local machine. Then offer/resolve an actual
   matching interface: trusted SSH Host alias, authorized ADB device,
   observed serial port plus baud, or the authorized local host. The
   reviewed plan MUST display the actual nonsecret endpoint (TTL path and
   baud), not a generic placeholder; absent details block confirmation. Ask one
   missing choice at a time and never fabricate an endpoint.
3. **Explain before operating.** Present the actual target/interface,
   read-only probes, local evidence/privacy model, live dashboard, stages,
   risks and limitations. Wait for explicit approval of this complete plan.
   Do not connect or start the server before plan approval.
4. **Live page before probes.** The approved plan includes a loopback-only
   real-time monitor by default. Start it inside the new private session
   before collection. Print the actual returned URL, never a guessed port.
   If the user opts out of preview, honor that; if startup fails, report
   unavailability, never claim the link works.
5. After the overall plan is approved, automatically run device-targeted
   Python diagnostics and supported device-internal read-only shell probes
   **without per-command user permission prompts**. Verify SHA-256 evidence.
   Reuse the managed SSH/ADB/TTL adapter and its session; do not conflict
   with existing picocom.
6. Use evidence to ask for missing target OS/version, boot medium, services,
   drivers and storage preferences one at a time, then proceed through the
   actually supported customization stages. Physical ARM image assembly
   and flashing are **not** implemented just because a shell is reachable.
7. The task-start local RW grant plus confirmed connection plan authorizes
   repeat project-local non-destructive writes and new offline images under
   outputs without redundant prompts. The target RW grant covers ONLY
   supported reviewed reversible device changes, not raw Shell writes.
   Download, isolated VM boot, host/tool sandbox gates, and dangerous target
   changes retain the relevant independent checks. Never allow reboot,
   shutdown, disk writes or flashing on an access-level grant alone.
8. Every runtime artifact (device evidence, monitoring state, plans, reports,
   logs, images, downloads, intermediate files, verifications) is written
   under **`./outputs/`** using validated workspace paths, never at the
   repository root. Tracked source edits stay in place; `.venv` is the sole
   local environment exception. Old artifacts are not silently moved.
9. Routine non-destructive actions strictly inside the current project
   have standing approval **only after local RW is granted at task start**.
   Do not repeatedly prompt within the chosen task scope.
   Host/Codex/OS execution permission gates remain mandatory when imposed
   externally. No standing consent for target connection, arbitrary
   network installs, untrusted code, deleting important files,
   host/system changes, VM boot, firmware/DTB edits or disk writes.
10. For ARM blockers, research and attempt a new board-specific candidate
    revision before stopping for truly unavailable tools, permissions or
    hardware intervention. Report actual attempts and never claim boot success
    from a baseline RootFS or static log.

Use `agent_journey.py` as the pure step/consent policy, not as a process
launcher. Do not make ordinary users choose Python/QEMU/Lima arguments.

Use `references/interactive-agent-flow.md` for the full transition and
approval contract. All Python scripts are **Agent-invoked helpers**, not
required commands for end users. An optional UI is a read-only observer.

## Use the unified interactive device adapter

The first-choice read-only **interactive** device transport is
scripts/workflow/device_session.py, invoked through adaptive.py with
--interactive-shell-approved and --yes. It keeps **one session open** rather
than launching picocom, ssh or adb separately for every hardware probe.

- For TTL, invoke picocom in a managed local PTY, using the detected port and
  observed baud rate. The legacy pyserial TTL mode is passive-only and is not
  sufficient for interactive customization.
- For ADB and SSH, reuse one device shell process throughout the probe batch.
  Never request credentials or turn on network ADB without separate consent.
- Detect the shell prompt first on TTL. U-Boot, login prompts and unknown
  consoles are blocked from automatic commands. A single blank-line wake
  requires the operator to confirm the input buffer is empty.
- Execute only the immutable read-only probe allowlist and log results to a
  new private local session; record errors, skipped evidence and transcript
  hashes without confusing an empty session with successful identification.
- Obtain **one user consent for the connection and overall read-only
  diagnostic scope**, then automatically run all supported Python and
  device-internal shell probes as a batch. Do not ask per command.
  Host/Codex sandbox prompts are independent and cannot be disabled here.
  Never split the same approved batch into many host invocations.
- Work toward the user's actual OS customization goal. After discovery,
  proceed to board boot-chain/BSP, image-building prerequisites and concrete
  implementation blockers; do not redirect to unrelated hardware repairs.

For the exact interface and blocking cases, read
references/device-session.md. Device flashing and offline image creation
remain separate higher-risk approvals. Physical ARM IMG building has not yet
been implemented; do not falsely claim successful device deployment.

## Hard safety requirements

- Never run arbitrary Shell commands from untrusted device data or from
  an unvalidated profile. Existing fixed scripts have their own hard gates.
- Never perform device flashing, partition writes, reboot or network
  changes on implied consent. Physical ARM boot-log analysis is only
  evidence collection, not proof of boot or deployment readiness.
- A QEMU exit code or raw serial text cannot prove a guest is healthy;
  only verified guest-side health checks can support an isolated VM
  boot-confirmation claim.
- Never start an unavailable or stopped local Lima VM automatically.
- Never automatically trigger GitHub Actions for this project. When
  committing fixes, use `main` directly unless the user changes that
  repository preference.
- Be candid about which tests actually ran; synthetic tests are not
  physical device validation.

## Development

After changing the Skill, validate with
`./.venv/bin/python -B -m unittest discover -s tests -v` (Unix/macOS) when
the project workspace is initialized and execution is available. Keep any added workflow helpers auditable and noninteractive
by themselves; the Agent should conduct the conversation.
