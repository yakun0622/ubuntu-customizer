---
name: ubuntu-customizer
description: Agent-led read-only discovery and evidence analysis for Ubuntu, Debian, Armbian and compatible Linux systems over SSH, ADB, managed picocom TTL or local access, with legacy passive TTL capture; assess image compatibility, customize existing VM images with a fixed offline recipe, and optionally verify AMD64 guest health. Maintenance and recovery are planning only; offline physical ARM IMG candidate assembly is implemented, but verified W152D USB boot and flashing are not.
---

# Ubuntu Customizer — AI Agent Skill

**This is a Skill, not a standalone application.** Users start by saying
**“开始定制系统”** or **“开始检查设备”**. The AI Agent performs each
supported stage using the tools actually available to its runtime, asks one
short question only when a choice or permission is needed, and resumes
automatically after the answer. Users should never be made to select
Python commands, QEMU/Lima adapters, directories, or command-line flags
unless no authorized execution connection exists.

The Agent remains the sole workflow controller. The optional dashboard,
device manager, image scripts and CLI examples are implementation tools,
**not** separate products or required user entrypoints.

Read [One-start interactive Agent flow](references/interactive-agent-flow.md)
and [Agent workflow](references/agent-workflow.md) first. Then read
[Device discovery](references/device-discovery.md),
[Image building](references/image-building.md),
[Offline RootFS building](references/rootfs-building.md),
[QEMU first-boot verification](references/first-boot-verification.md),
[System management](references/system-management.md),
[ARM hardware](references/arm-hardware.md), or
[Safety](references/safety.md) *only for relevant stages*.

## Task-start authorization matrix (highest priority)

**Ask before any host inspection, virtualenv creation, device connection,
Python probe or Shell command.** At the beginning of each new task, confirm
**two independent permission levels**:

1. **Local host:** `none` / `read` / `read-write`, strictly for the
   **current ubuntu-customizer project**. Read allows project inspection and
   non-writing host capability checks. Read-write additionally permits
   `./.venv/`, creating files and tests under `./outputs/`, editing tracked
   project files and building **new offline images inside outputs**. Never
   infer unrestricted Mac filesystem access from this option. If read-only,
   pause before workspace initialization/output capture requiring writes.
2. **Target device:** `none` / `read` / `read-write`, for the **single
   device/interface selected later in this task**. Read allows verified
   SSH/ADB/TTL status, logs, DTB/network/driver diagnostics. Read-write
   additionally preauthorizes **supported, reviewed, reversible ordinary
   configuration changes** at that endpoint, only when pre-change evidence,
   backup/rollback and verification are actually available. It does **not**
   make `device_session.py` an arbitrary writable Shell: the implemented
   adapter is still fixed read-only probes.

Both grants are per-task, least-privilege, revocable, **never inherited**
silently from an earlier conversation or another device. A `none` blocks
operations requiring that resource. After the two grants, use any existing
known task goal/target, select the connection method + actual interface,
**show and confirm the complete connection/execution plan once**, then
execute all supported operations within the grants **without per-command
permission questions**. Do not re-ask just because another Python helper
or device-internal diagnostic command is required.

For a confirmed local `read-write` grant, NEW offline images created
only under `outputs/` are already covered: use the initial authorization
to satisfy `arm_image_builder` / `rootfs_builder` approved-output gates,
rather than asking `offline_build` again on each iteration. The independent
approval for network downloads, starting an isolated VM, and especially
physical device / block-device writes still applies. The permission
matrix never overrides host sandbox, login, SSH host-key or ADB trust gates.

**Always separately review and confirm:** eMMC/flash/partition writes and
erases, bootloader/U-Boot/firmware changes, reboot/shutdown, network/SSH
cutover and possible disconnection, elevation/sudo/su, executing untrusted
code or destructive deletes. Do not run unsupported hardware mutation
adapters even if the target grant says read-write. Treat permission
selection and plan confirmation as conversational events in
`agent_journey.py` (`schema_version=2`, `access.local`,
`access.target`), not as permission to bypass executable safety checks.

## HTTPS CA trust for official ARM baseline downloads

The ARM baseline downloader verifies HTTPS using a trusted PEM CA file
**inside the current project** rather than assuming Mac Python's global
certificate store is populated. By default it uses the Mozilla CA bundle
vendored by `pip` in the project's `.venv/`, after validating that its
path is within the project. For a separately trusted enterprise or proxy
CA, the operator can place a PEM bundle under `outputs/certs/` and
supply `arm_baseline.py --approved-download --ca-bundle
outputs/certs/roots.pem`. The CA bundle must be obtained and trusted
independently, not accepted just because the download endpoint returned it.

On a `CERTIFICATE_VERIFY_FAILED` error, do not disable TLS verification,
set an unverified SSL context, run curl with `-k`, or turn off hash checks.
Present the CA-bundle remedy, then retry. The baseline's pinned SHA-256
verification remains mandatory even after HTTPS succeeds.

## Physical ARM source-first iteration (highest priority)

For a physical ARM target, **never begin by searching the Mac, its home
directory, removable media, or other host directories for an existing image**.
After authorized device evidence collection and requirements, select the
smallest appropriate official ARM64 userspace baseline. The first implemented
default is the pinned Ubuntu Base 24.04.5 ARM64 rootfs tarball; inspect its
documented release URL/hash before downloading. It is not a bootable IMG and
does not include the W152D kernel, DTB or bootloader.

The active policy is **official baseline → board/SoC/boot-chain research →
versioned component staging → targeted serial verification → diagnosis and
next revision**. Missing DTB/kernel/BSP causes focused extraction/research
and another candidate iteration, NOT a final `physical_evidence_only`
result. `arm_baseline.py` implements an approved, fixed-hash download into
`outputs/baselines/`; `arm_candidate.py` stages project-local components
into new numbered revisions in `outputs/arm-candidates/`. These are the
first implemented pieces of the pipeline. Offline FAT32/ext4 IMG
assembly now exists; W152D-compatible boot-chain assembly, driver patch
compilation, physical USB boot testing and flashing remain UNVERIFIED
or unsupported. Never claim otherwise.

## Strict project-local file access (highest priority)

**The active project directory is the entire host-file scope for this Skill,
for both reading and writing.** Do not read local files elsewhere, even for
discovery or convenience. All runtime writes stay in `./outputs/`; the
self-contained Python environment stays in `./.venv/`; tracked project
sources may be edited only within the project. No `~/Downloads`,
`~/.ssh`, `/tmp`, `/var`, sibling repositories, other disks, external
input images or automatic local search. Do not recursively browse user
directories. `project_workspace.project_root` refuses CWD fallback;
`checked_input` rejects out-of-tree inputs and symlinks. Disable implicit
external host scans and Lima probing.

Explicitly authorized **remote target-device evidence reads** are logically
separate from accessing the Mac's local files. Serial TTL hardware access
necessarily opens a node under `/dev`; it cannot meet a literal ban on
*all* out-of-tree device-node reads. If the operator also forbids that
specific device-node access, do not open TTL, and report that limitation
before connecting. SSH/ADB transports may also use OS-managed external
credentials/configuration; avoid implicit access and require a host sandbox
with the requested confinement before claiming comprehensive enforcement.
Python path guards are not a substitute for an OS-enforced file sandbox.
Never claim whole-process filesystem confinement based only on these checks.

## Physical ARM USB IMG builder, DTB adaptation and diagnostic loop

The physical ARM lane now has **executable offline candidate builders** in
`scripts/workflow/arm_image_builder.py`, `arm_dtb_adapter.py` and
`arm_boot_diagnose.py`. Run them only through the approved Agent stages.
This does **not** prove boot on W152D or enable direct flashing.

After the official pinned Ubuntu Base ARM64 archive is available and board
evidence is collected, use `arm_dtb_adapter.py` (optional, when a DTS and a
project-local approved `dtc` executable exist) to compile and inspect a
new DTB revision. Stage verified project-local ARM64 Kernel, DTB, optional
initramfs and board-specific boot files in a new `arm_candidate.py` revision.
In particular, identify whether W152D/gxlx4 requires `boot.scr`,
`boot.ini`, `aml_autoscript` or another genuine vendor loader path;
**never infer that extlinux or a FAT32 partition alone will boot**.

Run `arm_preflight.py` after board component staging: it inspects
only project-local source, component hashes, and the project-local
ext4 writer. It never searches the Mac or executes host binaries.
A missing tool is a concrete remediation target, not a reason to search
outside the project. The Agent's `arm_preflight` stage must finish
before asking for offline-build consent.

With separate offline-build consent, `arm_image_builder.py` extracts the
checksum-pinned Ubuntu Base in a private output directory, optionally
applies a hash-pinned kernel modules/firmware overlay, creates a 1 MiB aligned
MBR with FAT32 (`UCBOOT`) and ext4 (`UCROOT`) partitions, stages board
boot assets, creates a RAW `.img` **ordinary file**, and publishes its hash
and an explicit list of unverified gates. The portable `arm_fat32.py` backend now creates the FAT32 boot volume
using only the Python standard library; `mkfs.vfat`, `mcopy` and
`mmd` are optional legacy alternatives. Ext4 still requires a
compatible, explicitly provided project-local `mke2fs` tool executed
under an OS-confining environment. No direct disk paths, `dd`, mounts, loop
devices, `/dev` writes or eMMC writes are permitted.

For each physically tested USB candidate, save that **revision's** UART log
inside `outputs/`. `arm_boot_diagnose.py` hashes the candidate IMG and
serial log, classifies U-Boot / kernel / FDT / rootfs / init / USB / Ethernet
faults and recommends a **new versioned revision**, without exposing raw
log text. In `agent_journey.py`, approved `arm_build` must precede log
availability, `physical_evidence` and `arm_diagnose`; `iterate_arm`
requires new offline-build consent and does not re-download the base.
No unauthenticated UART text may set `boot_confirmed=true`.

The board-specific Kernel/DTB driver fixes, U-Boot memory/load path, vendor
firmware, ext4 init compatibility and W152D USB power/reset behaviour are
still **unverified on real hardware**. A candidate IMG is not a validated
bootable W152D image. Never write eMMC or imply real USB testing from mocked
unit tests. All local inputs must pass project-only path checks. An
**OS-enforced filesystem sandbox** is required to guarantee that external
dynamic libraries/subprocesses do not read host directories outside the
project; Python checks alone cannot provide that guarantee.

## Capability and validation boundary

Use [Roadmap and acceptance](references/roadmap.md) as the maintained
capability matrix and validation record. Implemented helpers cover read-only
discovery (including guarded persistent device sessions), project workspace
bootstrap, evidence/software graphs, guest image inspection, VM RAW/QCOW2
conversion, limited private-copy RootFS customization and optional AMD64
QEMU Guest Agent health verification. The standard Python suite passed on
macOS; real device collection, libguestfs builds, guest boots and Lima
execution remain unverified. Synthetic tests do not establish those results.

`agent_journey.py` is a pure policy, not an executor or persistent session
store. Its inspect / diagnose / maintain paths currently finish with
evidence analysis. Separate task and profile planners do not apply changes
or provide automatic diagnosis, maintenance, recovery or rollback. Physical
IMG/BSP assembly, flashing, installer ISO creation, installed-system cloning
and arbitrary package/script customization are unsupported. A NoCloud seed
ISO does not constitute an OS installer.

## Default project workspace, outputs and local command authorization (highest priority)

When the user has selected **local read-write** for this task, the Agent
may perform the project-local bootstrap automatically **after the startup
permission matrix**, without a second permission prompt:

```bash
# Agent invocation from the current repository directory, not user onboarding.
python3 -B scripts/workflow/project_workspace.py
```

The helper invokes the current Python interpreter's standard-library
`venv` module to create **`./.venv/`**, or reuses a valid existing
virtual environment. It creates **`./outputs/`** with private mode 0700,
and performs no package download, `pip install`, device connection, reboot,
or host configuration change. The Agent must then use
`./.venv/bin/python` (Windows: `./.venv/Scripts/python.exe`) for Python
helpers and tests with `-B` (disable project-root Python bytecode cache); do not install dependencies globally. A broken or
unavailable interpreter/venv must be reported as a blocker, not silently
replaced by global installation.

**All generated/persistent runtime results belong under `./outputs/`**:
device-session directories, raw/filtered evidence, logs, manifests, preview
runtime records, hardware reports, graphs, downloaded source inputs,
intermediate files, plans, built images, checksums and verification reports.
Use `project_workspace.output_path(...)` (or its validated
`checked_output(...)` CLI interface) to build new destinations. All public
CLI writer entrypoints, including standalone image-build and diagnostic
helpers, enforce this policy; test-fixture library functions may retain
an isolated temporary directory for unit tests. Never write
them into the repository root or sibling paths, or follow output symlinks
outside the project. Only `./.venv/` is an explicit environment exception;
tracked source code/documentation edits stay in their original paths.
Do not move or delete preexisting user files without approval. `outputs/`
and `.venv/` are excluded from Git.

**Standing local authorization when local=read-write was granted at task
start:** Routine reversible project-scoped operations *inside the current
project* are approved for this task, such as
creating the virtual environment, creating private output directories,
running local tests, inspecting/editing project source and writing new
files under `outputs/`. Do not ask for fresh user approval for every such
operation. This does **not** waive permissions imposed by the host/OS/tool
sandbox; the Skill cannot suppress those prompts. It does not authorize
connections to target hardware, remote code execution, destructive deletion
or overwrite, package downloads or execution of untrusted scripts,
privileged host actions, modifying system configuration, booting a VM,
rebooting/powering off a device, writing disks or flashing firmware.
Those actions keep their existing explicit risk and consent boundaries.
Do not mistake a local `cwd` for containment when a command targets
absolute paths, remote hosts, devices, mounts or external resources.

## Standing device Python and device-shell authorization (highest priority)

**The user's instruction is: device-targeted Python commands and commands
inside the connected device may run directly, without individual permission
prompts.** Interpret this as standing authorization **after the connection
method, exact endpoint and one overall device plan have been confirmed**:

- Automatically invoke approved project-local Python helpers for device
  discovery, serial capture, log collection, status polling, DTB/driver
  read-only inspection, evidence verification and diagnosis. Choose the
  arguments internally; do not stop to ask whether each Python command
  may run. Use `./.venv/bin/python -B`, with outputs only in `./outputs/`.
- Automatically execute *consecutive* read-only Linux/Android shell
  diagnostics inside the verified SSH/ADB/TTL session, including fixed
  probes of `uname`, `getprop`, `cat /proc`, `cat /sys`, `ip ... show`,
  `ethtool` status/statistics, `dmesg` and boot diagnostics where
  supported and scoped. One confirmed plan covers the whole safe sequence;
  **never ask the user to authorize each device command again**.
  Continue collecting and interpreting results until the investigation
  reaches a genuine missing prerequisite or a new risk boundary.
- The implemented `device_session.py` backend still enforces a fixed
  read-only probe allowlist; Agent discretion does not bypass that
  execution constraint. If a needed diagnostic is not supported by the
  backend, extend/review the supported diagnostic workflow rather than
  blindly sending arbitrary Shell text or interrupting the user with
  repeated consent questions.
- **This is not blanket permission for destructive or disruptive effects.**
  A new, explicit scope/permission boundary still applies to eMMC writes,
  formatting/partition edits, raw flash/firmware or U-Boot writes, kernel
  installation, reboot/shutdown, network/SSH changes that could disconnect
  the device, privilege escalation, executing untrusted downloads/scripts,
  and other irreversible operations. Do not use `su`, `sudo`, `dd`,
  `flash_erase`, `fw_setenv`, or shell redirection into devices/sysfs
  under read-only standing authorization. Do not reinterpret an unsafe
  command as safe just because it uses `python` or runs inside the device.
- Hardware access remains restricted to the selected approved interface.
  Never invent ports, silently connect to another host, run on unknown
  UART/U-Boot/login prompts, or access the controlling Mac's local files
  outside the current repository. Device paths such as `/proc` and
  `/sys` belong to the **device**, not the Mac; do not conflate them.
  Host/Codex/OS sandbox permissions and transport authentication cannot
  be bypassed by Skill text.

The approved plan's `collect` step exposes
`device_python_auto_run=true`, `device_shell_auto_run=true` and
`per_command_user_confirmation=false`. These state facts mean **no
additional conversational permission for scoped diagnostics**; they do
not enable arbitrary remote execution or cancel any higher-risk gate.

## Persistent device access (preferred for interactive hardware)

For TTL/picocom, ADB and SSH, the preferred **authorized** collection path
is scripts/workflow/adaptive.py with --interactive-shell-approved --yes,
plus --transport, --target and a fresh private --output chosen by the Agent.
The adapter is scripts/workflow/device_session.py: one persistent host
process/PTY for the whole session, fixed read-only shell probes, private
console.log, SHA-256 manifest and per-probe result files. This uses
**picocom** for TTL, not the old passive pyserial-only recorder.

- Discover already-present ports, configured SSH aliases and authorized ADB
  serials before access; choose a unique observed device, never guess a port.
- After the user confirms the connection and overall read-only diagnostic
  scope once, automatically run the supported device-facing Python helper
  commands and all allowlisted device-internal Shell probes, without asking
  permission for each command. Continue the same safe investigation without
  repeating consent prompts. Codex/host sandbox approvals remain separate
  and **cannot be waived by a Skill**.
- The agent recognizes Android/Linux shells and reports U-Boot, login or
  unknown prompts as **blocked**. TTL must observe a trusted shell prompt
  before sending anything. Never type a password, interrupt U-Boot or send
  arbitrary commands to an unknown console. Only after the user separately
  confirms that the serial input line is blank may the Agent use
  --wake-console-approved for a single CR to reveal the prompt.
- For ADB and SSH, a newly opened interactive Shell may be verified by a
  fixed marker probe. Avoid repeated subprocess connections per file.
- Capture actual complete / partial / blocked results. Successful
  session completion does not prove a device is bootable, and probes can
  return unavailable or error. Keep logs private; they may include
  unique device identifiers and network configuration.
- If no executable transport is available or the host blocks PTY/serial
  access, state the precise missing prerequisite. Never claim the
  Agent operated a machine it cannot reach.

Existing adaptive.py without --interactive-shell-approved remains a
backward-compatible passive TTL or one-command-at-a-time SSH/ADB collector.
The persistent path is the default for a user's **interactive device
customization** request. Its initial connection-plan flag is not a
per-command prompt, and it does not bypass OS-image build approvals.
See [Interactive device consoles](references/device-session.md).

## One-start Agent entrypoint (highest priority)

**When the user says “开始” or requests customization, START by asking
local and target read/write permissions, before ANY host inspection**.
Then proceed to the approved host inspection and workspace bootstrap.
Never first respond with a long CLI checklist. Use the existing goal/target information
from the conversation; ask only for the single essential missing decision.

The Agent may use `scripts/workflow/agent_journey.py` as a **pure decision
helper**, not as a user-facing app. Its `start → next_step → transition`
policy returns a fixed next action or one short question. It never executes
commands or grants approvals. The Agent invokes the appropriate existing
Python helpers only when its host execution tool is actually connected,
records observed outcomes and automatically continues to the next safe stage.

A normal journey is **local read/write grant → target read/write grant →
approved host detection → .venv/outputs bootstrap (only with local RW) →
resolve only missing intent/target →
select SSH/ADB/TTL/local transport → choose its actual available interface →
explain the complete connection, collection and monitoring plan → obtain one
explicit approval for that plan → create a private session and start its
loopback live preview → report the verified preview URL → perform read-only
evidence collection → SHA-256 analysis → gather missing customization
requirements one at a time → compatibility planning → separately approved
build/verification when supported**. Never show a preview URL unless the
server actually started. The plan approval covers exactly the described
read-only connection and local observer; it does NOT authorize image writes,
system mutations, remote power controls or firmware flashing.

For physical ARM targets the Agent obtains a pinned official minimal ARM64
RootFS as the baseline, researches device-specific boot components, stages
versioned candidates and iterates on evidence gaps; unimplemented physical IMG
construction/deployment remains explicitly unverified and cannot be claimed.
QEMU must never be forced on physical-device flows.

Keep interactions in the conversation: one question at a time, with a
recommended/default safe option. Do not ask users to pick between
`qemu-img`, libguestfs, Lima, SSH flags or backend names. Do not silently
connect to a device, install tools, boot a VM, or create/write an image:
the general “开始” message grants **none** of those permissions.

For a one-computer setup, the Agent may use native Linux tools or an
**already-running**, explicitly authorized local Lima Linux guest on macOS.
The latter stays on the same physical Mac; never create/start Lima or change
a filesystem mount without explicit approval. If no execution bridge
is available, explain that limitation truthfully and propose the single
relevant setup action rather than pretending local work ran.

**All decisions are revocable at later stages**, and one approval applies
only to its described risk boundary. After any blocked ARM stage, attempt safe source research and the next
versioned candidate without repeating already-approved collection. Stop for
hardware intervention, external access authorization, or unsupported writes;
never bypass safety gates.
Report verified operations accurately and finish with ONE concrete next-step
follow-up button where the client supports it.

## Primary workflow

0. **Confirm permissions before any work.** Ask for the current-project
   local `none/read/read-write` scope and the selected device's
   `none/read/read-write` scope. Only after local read consent inspect
   host capabilities; only after local read-write consent prepare
   `.venv`/`outputs`. Keep all generated files under `outputs/`.
   Do not repeat permission prompts within the granted scope.
1. **Establish intent.** Ask whether the user needs discovery, diagnosis,
   maintenance, recovery or a portable system image. Distinguish target,
   control host and build host.
2. **Choose transport AND interface before designing the plan.** If neither
   was given, ask for SSH / authorized ADB / managed picocom TTL / local.
   Then discover or request the matching interface: trusted SSH Host alias,
   authorized ADB serial or connected address, exact /dev serial port with
   observed baud rate, or the approved local computer. Store a short,
   nonsecret *actual interface display* in the policy and show it in the plan;
   refuse plan confirmation while the interface is still unspecified. Reuse already-known
   selections; never guess a port or fabricate access. Close existing
   picocom before handing TTL ownership to the managed collector.
3. **Review the entire plan and obtain explicit confirmation.** Explain the
   target, the **actual chosen endpoint (TTL port AND baud rate)**,
   connection mode, read-only probe scope, evidence handling, planned
   stages, the local monitoring page, risks and limits.
   A single confirmed plan authorizes ONE read-only session plus a
   loopback-only preview. The legacy `manage.py collect` CLI must display
   this combined plan once (unless `--yes` already represents approved
   scope); monitor is included by default and `--no-preview` is an explicit
   opt-out. Before that answer do not open the device or start
   the collector or preview. If the user declines the preview, honor that
   exception and keep the rest of the plan unchanged.
4. **Start monitoring, then discover.** After confirmation, create a new
   private session and start the local preview before any shell probes.
   Managed SSH/ADB/picocom sessions use
   `adaptive.py --interactive-shell-approved --preview-approved --yes`
   (the Agent selects the real transport, target, output). Stream/surface
   only the URL returned by successful local observer startup, e.g. an
   actual `http://127.0.0.1:<port>/`. Never invent a URL or claim
   a remote viewer can reach localhost. If preview startup fails, report
   its unavailable state and continue safe discovery with text checkpoints.
   Read-only scope is unchanged by the monitoring feature.
5. **Normalize evidence.** Validate the session's SHA-256 manifest.
   Summarize OS, architecture, hardware, drivers, boot chain and unknowns.
   Use `dossier.py`, `capabilities.py`, `topology.py`,
   `device_tree.py`, `link_graph.py` selectively.
6. **Gather requirements and decide next task.** After evidence collection,
   ask only for missing customization facts: target OS/version,
   services/packages, boot medium, storage, network and desired validation.
   Reuse requirements already expressed in the conversation. These are
   Agent-owned dialogue steps, not executable target commands. For portable images,
   distinguish VM/cloud, installer ISO and **physical-hardware IMG** before
   choosing a backend.
7. **Inspect, plan and gate.** First use `scripts/workflow/image_inspect.py`
   to inspect the existing RAW/QCOW2 source **read-only** (qemu-img,
   virt-filesystems, virt-inspector, virt-drivers and guestfish). Then use
   `image_plan.py` for verified device-to-image compatibility decisions.
   The plan automatically re-inspects the image and requires proven partition
   table (GPT/MBR), partitions, Linux OS, measured guest architecture, kernel,
   firmware boot mode and bootloader. The declared source architecture alone
   can never authorize a build. Unknown tooling, unreadable filesystems,
   encrypted/backing-chain images or mismatches become explicit blockers.
   A successful plan is a **candidate for offline format conversion**, not
   proof of bootability. Physical-device IMG assembly remains blocked.
8. **Execute only supported, authorized work.** For an approved VM image,
   `build_image.py` provides offline RAW/QCOW2 conversion.
   `rootfs_builder.py` can **preview** a fixed offline RootFS recipe and,
   after explicit separate `--approved` authorization, make a private clone
   and apply an allowlisted hostname/MOTD/NoCloud initialization recipe.
   It runs virt-customize and narrowly scoped virt-sysprep *only on that
   private cloned image*, then validates the output and publishes a
   checksum-backed bundle. Require an inspected Linux VM image with
   cloud-init; missing support blocks work. `verify_vm.py` retains
   static verification and a legacy inconclusive smoke attempt.
   `verify_first_boot.py` is the **separately approved** RootFS bundle
   boot-health backend: it starts an isolated x86_64 QEMU snapshot and
   uses a challenge-bound, fixed read-only QEMU Guest Agent probe to check
   Linux boot, healthy systemd, completed cloud-init with matching NoCloud
   instance ID, hostname, initialized machine-id, regenerated SSH host keys,
   SSH service and local network. All checks must pass before
   `boot_confirmed=true`. Missing Guest Agent/Python or UEFI firmware
   is a blocker; never inject dependencies or infer guest boot from QEMU
   exit codes. Full arbitrary RootFS package installation, installer ISO
   creation, installed-system cloning, complete first-boot identity
   personalization, physical IMG/BSP assembly and flashing remain
   **not implemented**.
9. **Verify and report.** Record actual results, source/evidence hashes,
   image hash, remaining compatibility blockers, tests performed and
   recovery path. Do not claim tests or builds that were not run.

For a prepared Linux build host, `cloud_image_e2e.py` optionally coordinates
the VM pipeline with separate build and boot approvals. Its explicit download
option checks a pinned Ubuntu Cloud Image SHA-256, not an upstream signature;
the source URL's availability and real end-to-end execution are unverified.
Missing guest QGA/Python or host tools block execution without installation.

## Developer / Agent helper examples (NOT user onboarding)

These commands exist for debugging or for an Agent with authorized host
execution access. **Do not present this sequence as the user-facing
startup experience.** For normal use, users say “开始定制系统” and the
Agent owns the progression, choices and tool invocation.

```bash
# First collect evidence, with the user's approval:
./.venv/bin/python -B scripts/workflow/adaptive.py
# Then assess the evidence:
./.venv/bin/python -B scripts/workflow/dossier.py SESSION_DIR
./.venv/bin/python -B scripts/workflow/capabilities.py SESSION_DIR

# Optional standalone source inspection report (no image modification):
./.venv/bin/python -B scripts/workflow/image_inspect.py ./outputs/sources/base.img \
  --sha256 TRUSTED_SHA256 --output ./outputs/source-inspection.json

# Analyze an existing trusted base image against a collected session:
./.venv/bin/python -B scripts/workflow/image_plan.py SESSION_DIR \
  --target virtual-machine --format qcow2 \
  --source ./outputs/sources/base.img --sha256 TRUSTED_SHA256 \
  --source-arch amd64 --output ./outputs/image-plan.json

# Only when every mandatory guest inspection check passed AND the
# verified plan says build_allowed=true:
./.venv/bin/python -B scripts/workflow/build_image.py ./outputs/image-plan.json \
  --output ./outputs/portable.qcow2

# Optional fixed offline RootFS customization (requires approved image-plan):
# Copy profiles/examples/rootfs-config.json and update public key, instance-id.
./.venv/bin/python -B scripts/workflow/rootfs_builder.py ./outputs/image-plan.json \
  --config ./outputs/rootfs-config.json --dry-run

# Separate explicit approval is required to write an isolated image bundle:
./.venv/bin/python -B scripts/workflow/rootfs_builder.py ./outputs/image-plan.json \
  --config ./outputs/rootfs-config.json --output-dir ./outputs/new-rootfs-bundle --approved

# Recheck the published image/seed hashes and qemu metadata, read-only:
./.venv/bin/python -B scripts/workflow/rootfs_builder.py \
  --verify-bundle ./outputs/new-rootfs-bundle

# Only after separate approval, for a VM with QEMU Guest Agent/Python.
# Add --ovmf-code and --ovmf-vars for verified UEFI guests.
./.venv/bin/python -B scripts/workflow/verify_first_boot.py \
  --bundle ./outputs/new-rootfs-bundle \
  --timeout 300 --report ./outputs/first-boot-health.json --approved
```

## Safety invariants

- Never equate a declared source architecture with verified guest architecture.
- Unknown hardware/probe results are **unknown**, not absent.
- A DT software relationship never verifies physical pinout or voltage.
- R0 read-only; R1 offline artifacts; R2 service/package changes; R3
  network/kernel/DT; R4 device disk writes/firmware. Require separate
  approval, suitable backups and recovery at each higher-risk boundary.
- Never write to target disks or flash firmware on the strength of a generic
  architecture match.
- Never automatically publish raw evidence, credentials or machine identities.
- Do not enable bypasses for SSH trust or privilege elevation automatically.
- Respect no CI execution preference where applicable; submitted test source
  is not proof of passing tests.

## Optional live progress preview (not the Skill UI)

The AI Agent is always the workflow controller. The real-time preview is
**included by default in the execution plan shown before connection**:
the user's confirmation expressly covers starting a localhost-only
observer as well as the defined read-only device scope. No separate preview
question is necessary. If the user declines preview, disable it and continue
normally. Do not expose the viewer on LAN or the public Internet; bind
only to `127.0.0.1`.

Use `adaptive.py --preview-approved` for both the staged collector and
the **managed interactive SSH/ADB/TTL collector**. They create the private
session, start the observer before device probes, and report its actual URL
when local readiness succeeds. For managed sessions, the CLI emits a
`preview_ready` JSON line immediately, then a final result line.
The Agent should present that verified URL when the host's execution stream
permits it; a blocking execution tool may only deliver it upon completion.

```bash
./.venv/bin/python -B scripts/workflow/preview_control.py start SESSION_DIR --approved
./.venv/bin/python -B scripts/workflow/preview_control.py status SESSION_DIR
./.venv/bin/python -B scripts/workflow/preview_control.py stop SESSION_DIR
```

The start command reports the actual `http://127.0.0.1:<port>/` URL on
the controlling host only. The page polls sanitized local checkpoint status
every two seconds. It never serves raw evidence.

**Image helpers now report automatically when the preview is live**:
- `image_plan.py` → `image-plan`: source checksum, evidence integrity,
  compatibility decision (`blocked` when prerequisites are missing).
- `build_image.py` → `image-build`: source verification, format inspection,
  conversion, output verification, result manifest.
- `nocloud.py` → `first-boot`: NoCloud files, optional seed ISO, final manifest.
- `rootfs_builder.py` → `rootfs-build`: private-copy customization and
  bundle publication.
- `verify_first_boot.py` → `verify`: isolated AMD64 guest-health checks.
- `verify_vm.py` → `verify`: output hash, metadata, optional QEMU attempt.
  Static verification `complete` is **not** a verified guest boot;
  inconclusive boot attempts are `blocked` and nonzero QEMU exits `failed`.

The image plan contains the original `discovery.session`, and the build
result carries it as `discovery_session`, so the same user-approved preview
follows sequential phases. The helper verifies the local running preview
before updating `skill-status.json`. No live preview means **no automatic
status file writes** and no change to image-building behavior. Stopping
preview stops subsequent automatic status updates.

For other Agent-led stages not implemented as image scripts, an authorized
Agent can still explicitly publish factual progress:

```bash
./.venv/bin/python -B scripts/workflow/status.py SESSION_DIR \
  --stage analyze --state running --completed 1 --total 3
```

Only allowlisted stage/state names and integer counters are persisted;
never include credentials, paths, error text or command output in the
browser status. Recognized image phases are `image-plan`, `image-build`,
`rootfs-build`, `first-boot`, and `verify`. The preview observes status but
does not control or approve execution.

If a browser server cannot run on the controlling computer, report the
preview as unavailable and continue the Skill normally with text progress.
A `127.0.0.1` URL can only be opened on that controlling host; remote
access requires a separately reviewed secure tunnel, never automatic exposure.
Never assert that a preview or background process has started unless the
runtime has actually started it. See `references/live-preview.md`.

## Completion response contract

After **each development or Skill execution step**, report what changed,
which repository commit was produced, what tests actually ran (or did not),
and any remaining blockers. Then propose **one concrete next task** that
advances the existing user goal. In a host UI supporting interactive
follow-up actions, offer one visible **“继续下一步”** button which submits
a specific next-task prompt only when clicked. Otherwise provide the exact
next-task phrase for the user to send. A button is a follow-up request,
not permission to perform destructive operations or a claim that
background work has begun. Never automatically execute the next phase
without the user's follow-up or another explicitly authorized workflow.

## Source image inspection invariants

See `references/image-building.md`. Prefer a locally stored immutable base
image and a separately trusted SHA-256. Inspection runs Linux libguestfs
tools with a fixed image format, read-only guestfish access, no guest
networking and timeouts; oversized tool stdout is rejected after capture,
which does not bound memory use during capture. Treat a missing tool or
unrecognized XML as an evidence gap, **not** proof of an absent bootloader,
kernel, OS or partition. Store the source image SHA-256, tool provenance,
observed facts and failed checks in `image-plan.json`. The conversion helper
repeats the source inspection and rejects changes before invoking qemu-img.
Never run host-side mount, mkfs, parted write commands or firmware flashing
as part of source inspection. For a physical target, source guest boot
components still need a separately verified board-specific BSP and recovery
path. Successful checks do not substitute for boot testing.


## RootFS Builder Skill rules (VM only)

The Agent must first inspect both source image and target device evidence.
The RootFS recipe has a strict schema; only hostname, MOTD and a
public-key-only NoCloud first-boot seed are supported. Never accept
arbitrary executable commands, scripts, network package installation,
passwords, embedded private keys or custom guest file paths in the recipe.
Always run dry-run first and present the exact operations and dependencies
before seeking separate approval. No preview UI consent implies build
consent. Refuse any physical-device image plan without its independent
verified BSP/bootloader/DTB/firmware approval and suitable builder adapter.

RootFS customization uses only a private staging copy; never apply
virt-customize or virt-sysprep to the original image or a running VM disk.
Regenerating SSH host keys and machine-id is requested by virt-sysprep;
actual first-boot behavior and the absence of all device-specific secrets
remain **unverified** until separately audited. The optional NoCloud
seed assumes cloud-init support; the builder checks that the guest has
an installed cloud-init configuration but does not claim it was applied
on boot. Final bundles include image, seed, hashes and a build manifest;
verify these before attempting isolated VM boot testing. See
references/rootfs-building.md for the exact contract.

## Verified guest boot acceptance rule

Do not treat QEMU process exit status, boot messages or a Guest Agent ping
as successful boot. Use `verify_first_boot.py` only after explicitly
obtaining VM-launch authorization. It validates a RootFS bundle, boots a
temporary snapshot with TCG, offline restricted-DHCP virtual networking,
and a private local QEMU Guest Agent socket. The Agent obtains a fresh
challenge-bound, fixed read-only guest health report. Only if every check
passes may the report set `boot_confirmed=true`. Record incomplete
cloud-init, mismatched NoCloud instance ID, missing/old machine-id, invalid
SSH host key state, network errors or absent QGA as blocked/failed.
Do not infer physical board compatibility from an x86_64 VM result.
The optional status preview observes only sanitized states and cannot
approve or initiate this verification. See
`references/first-boot-verification.md`.
