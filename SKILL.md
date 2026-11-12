---
name: ubuntu-customizer
description: Agent-led, evidence-first discovery and customization of Ubuntu, Debian, Armbian and compatible Linux systems; plan portable images, assess hardware boot compatibility and safely coordinate builds, maintenance and recovery across SSH, ADB, TTL or local access.
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

## Default project workspace, outputs and local command authorization (highest priority)

When the Agent has real execution access to the user's **current**
`ubuntu-customizer` project directory, it automatically performs the
project-local bootstrap **before choosing a device connection**, without
asking for another confirmation:

```bash
# Agent invocation from the current repository directory, not user onboarding.
python3 scripts/workflow/project_workspace.py
```

The helper invokes the current Python interpreter's standard-library
`venv` module to create **`./.venv/`**, or reuses a valid existing
virtual environment. It creates **`./outputs/`** with private mode 0700,
and performs no package download, `pip install`, device connection, reboot,
or host configuration change. The Agent must then use
`./.venv/bin/python` (Windows: `./.venv/Scripts/python.exe`) for Python
helpers and tests; do not install dependencies globally. A broken or
unavailable interpreter/venv must be reported as a blocker, not silently
replaced by global installation.

**All generated/persistent runtime results belong under `./outputs/`**:
device-session directories, raw/filtered evidence, logs, manifests, preview
runtime records, hardware reports, graphs, downloaded source inputs,
intermediate files, plans, built images, checksums and verification reports.
Use `project_workspace.output_path(...)` (or its validated
`checked_output(...)` CLI interface) to build new destinations. Never write
them into the repository root or sibling paths, or follow output symlinks
outside the project. Only `./.venv/` is an explicit environment exception;
tracked source code/documentation edits stay in their original paths.
Do not move or delete preexisting user files without approval. `outputs/`
and `.venv/` are excluded from Git.

**Standing local authorization:** This user has approved routine, reversible
project-scoped operations and commands *inside the current project*, such as
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
- After the user grants **one clearly scoped read-only interactive session**
  authorization, batch all permitted commands into one host tool invocation.
  Codex/host sandbox approval is separate and **cannot be waived by a Skill**.
  Do not request a fresh user confirmation for each allowlisted read.
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
The new persistent path is the default for a user's **interactive device
customization** request, not a bypass for OS-image build approvals.
See [Interactive device consoles](references/device-session.md).

## One-start Agent entrypoint (highest priority)

**When the user says “开始” or requests customization, START the guided
conversation and available safe host inspection immediately**. Never first
respond with a long CLI checklist. Use the existing goal/target information
from the conversation; ask only for the single essential missing decision.

The Agent may use `scripts/workflow/agent_journey.py` as a **pure decision
helper**, not as a user-facing app. Its `start → next_step → transition`
policy returns a fixed next action or one short question. It never executes
commands or grants approvals. The Agent invokes the appropriate existing
Python helpers only when its host execution tool is actually connected,
records observed outcomes and automatically continues to the next safe stage.

A normal journey is **host detection → automatic local .venv/outputs bootstrap → resolve only missing intent/target →
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

For physical ARM targets the Agent progressively collects requirements and
boot/BSP/DTB/recovery evidence, but must label unimplemented physical IMG
construction and deployment as blockers rather than claiming completion.
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
only to its described risk boundary. After any failed or blocked stage,
stop automatic progression and present the blocker and a supported remedy.
Report verified operations accurately and finish with ONE concrete next-step
follow-up button where the client supports it.

## Primary workflow

0. **Prepare the local project automatically.** If a real host execution
   bridge exists, run `project_workspace.py` from the current project
   directory, use its `.venv` interpreter and route all generated files
   under `outputs/`. No repeat prompt for safe, project-local commands.
1. **Establish intent.** Ask whether the user needs discovery, diagnosis,
   maintenance, recovery or a portable system image. Distinguish target,
   control host and build host.
2. **Choose transport AND interface before designing the plan.** If neither
   was given, ask for SSH / authorized ADB / managed picocom TTL / local.
   Then discover or request the matching interface: trusted SSH Host alias,
   authorized ADB serial or connected address, exact /dev serial port with
   observed baud rate, or the approved local computer. Reuse already-known
   selections; never guess a port or fabricate access. Close existing
   picocom before handing TTL ownership to the managed collector.
3. **Review the entire plan and obtain explicit confirmation.** Explain the
   target, interface, connection mode, read-only probe scope, evidence
   handling, planned stages, the local monitoring page, risks and limits.
   A single confirmed plan authorizes ONE read-only session plus a
   loopback-only preview. Before that answer do not open the device or start
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

## Developer / Agent helper examples (NOT user onboarding)

These commands exist for debugging or for an Agent with authorized host
execution access. **Do not present this sequence as the user-facing
startup experience.** For normal use, users say “开始定制系统” and the
Agent owns the progression, choices and tool invocation.

```bash
# First collect evidence, with the user's approval:
python3 scripts/workflow/adaptive.py
# Then assess the evidence:
python3 scripts/workflow/dossier.py SESSION_DIR
python3 scripts/workflow/capabilities.py SESSION_DIR

# Optional standalone source inspection report (no image modification):
python3 scripts/workflow/image_inspect.py /safe/base.img \
  --sha256 TRUSTED_SHA256 --output source-inspection.json

# Analyze an existing trusted base image against a collected session:
python3 scripts/workflow/image_plan.py SESSION_DIR \
  --target virtual-machine --format qcow2 \
  --source /safe/base.img --sha256 TRUSTED_SHA256 \
  --source-arch amd64 --output image-plan.json

# Only when every mandatory guest inspection check passed AND the
# verified plan says build_allowed=true:
python3 scripts/workflow/build_image.py image-plan.json \
  --output portable.qcow2

# Optional fixed offline RootFS customization (requires approved image-plan):
# Copy profiles/examples/rootfs-config.json and update public key, instance-id.
python3 scripts/workflow/rootfs_builder.py image-plan.json \
  --config rootfs-config.json --dry-run

# Separate explicit approval is required to write an isolated image bundle:
python3 scripts/workflow/rootfs_builder.py image-plan.json \
  --config rootfs-config.json --output-dir ./new-rootfs-bundle --approved

# Recheck the published image/seed hashes and qemu metadata, read-only:
python3 scripts/workflow/rootfs_builder.py \
  --verify-bundle ./new-rootfs-bundle

# Only after separate approval, for a VM with QEMU Guest Agent/Python.
# Add --ovmf-code and --ovmf-vars for verified UEFI guests.
python3 scripts/workflow/verify_first_boot.py \
  --bundle ./new-rootfs-bundle \
  --timeout 300 --report first-boot-health.json --approved
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
python3 scripts/workflow/preview_control.py start SESSION_DIR --approved
python3 scripts/workflow/preview_control.py status SESSION_DIR
python3 scripts/workflow/preview_control.py stop SESSION_DIR
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
python3 scripts/workflow/status.py SESSION_DIR \
  --stage analyze --state running --completed 1 --total 3
```

Only allowlisted stage/state names and integer counters are persisted;
never include credentials, paths, error text or command output in the
browser status. Recognized image phases are `image-plan`, `image-build`,
`first-boot`, and `verify`. The preview observes status but does not
control or approve execution.

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
networking, bounded tool output and timeouts. Treat a missing tool or
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
