# ubuntu-customizer

[English](README.md) | [简体中文](README.zh-CN.md)

## Grant local and target read/write scopes before starting

The first two steps of each new Skill task explicitly ask for **local
host** and **target machine** access (`none`, `read`, or `read-write`),
before any host inspection, workspace creation, Python command or device
connection. Local access is restricted to this repository: read-write
permits `.venv`, `outputs/`, source edits and new offline image
artifacts, but never unrestricted Mac file access. Target access is
restricted to the endpoint subsequently chosen and reviewed in the
connection plan: read permits diagnostics, while read-write covers only
supported, reviewed, reversible ordinary configuration changes with
verified recovery. The current interactive backend still executes its
fixed read-only probe allowlist, not arbitrary writable shell commands.

After the two grants, the user selects a connection and confirms the
overall plan once. Reuse the approved scope for Python device helpers,
supported target diagnostics and new outputs-only offline image revisions
**without repetitive per-command consent**. Physical eMMC/partition or
firmware writes, reboots, disruptive network changes, privilege
escalation, untrusted code, network downloads and isolated VM boot retain
their distinct safety and consent rules. Task grants can be explicitly
revised or revoked; this invalidates the old connection plan.
Host OS/terminal sandbox prompts cannot be overridden.

## Device command approval: one plan, no per-command prompts

After the user approves the exact transport/endpoint and overall device
diagnostics plan once, the Agent may run project-local device-targeted
Python collectors/analyses and the supported read-only commands inside
the verified SSH/ADB/TTL session without asking again for each command.
The backend still uses a fixed safe-probe allowlist and blocks unknown
shell/U-Boot/login prompts. Destructive/disruptive actions (eMMC or
partition writes, firmware flashing, reboot, network lockout, privilege
escalation, untrusted scripts) remain separately gated. Host platform
permissions cannot be disabled by this Skill. All host artifacts remain
under `outputs/`; Python runs from the project `.venv/`.

## New physical ARM path: official baseline before board drivers

For physical ARM hardware, the Agent no longer begins by searching your
computer for an image. It selects an official pinned minimal ARM64 userspace
(Ubuntu Base 24.04.5), asks before downloading, verifies the SHA-256 and
stores the source under `outputs/baselines/`. Then it researches board
components and stages numbered candidates under `outputs/arm-candidates/`.
These candidates are **not yet bootable USB disk images**: full board image
assembly, kernel/DTB driver adaptation and hardware boot validation are
still to be implemented.

**Local file scope:** the Agent may only read and write files inside the
current project. All generated files live in `outputs/` (apart from the
project-local `.venv`). External image search, home-directory SSH config
discovery, host `/dev` directory enumeration and implicit Lima inspection
are disabled in the default path. Direct hardware access and OS subprocess
file operations need their own approvals/sandbox; Python guards cannot
guarantee whole-process isolation.

## Mac Python TLS certificate verification

When downloading Ubuntu Base with `arm_baseline.py`, HTTPS verification now
uses the Mozilla CA bundle vendored by pip in the current project's `.venv/`.
This prevents relying on a missing or mismatched Mac Python default OpenSSL
CA directory. No insecure TLS mode is provided.

If a separately trusted corporate HTTPS interception CA is needed, store its
PEM file inside the project (for example `outputs/certs/roots.pem`), then
use `--ca-bundle outputs/certs/roots.pem`. The path is checked against the
project scope and symlinks leaving it are rejected. Obtain and verify the
trusted CA independently; never disable certificate validation or the
pinned Ubuntu Base SHA-256 checksum.

## Physical ARM64 USB candidate image and boot diagnosis

The project now has guarded offline builders: `arm_image_builder.py`
creates a checksum-backed regular RAW IMG with 1 MiB-aligned MBR,
FAT32 boot and ext4 root partitions from the pinned official ARM64
Ubuntu Base userspace. It stages checksum-verified Kernel/DTB/initramfs,
vendor boot files and optional driver overlays. `arm_dtb_adapter.py`
compiles and structurally inspects project-local DTBs; `arm_boot_diagnose.py`
binds each revision's serial log and candidate image hashes to guide the
next board-specific correction.

These are **unverified USB boot candidates**, not a W152D boot guarantee.
FAT32 boot creation now runs in pure Python (no required mkfs.vfat/mtools).
The ext4 writer still needs a verified project-local `mke2fs`, and DTS
compilation optionally needs `dtc`. `arm_preflight.py` checks source hashes,
board assets and the ext4 writer without probing external host directories.
An OS-enforced sandbox is still necessary for process-wide confinement. No attached
disks, eMMC, host mounts, or automatic flashing are accessed. All input
paths remain within the current repository, all artifacts within
`outputs/`; synthetic tests cannot prove W152D boots.

## Project workspace

With host execution access, the Agent prepares or reuses project-local
`.venv/` and private `outputs/` before choosing a device connection. No
packages are downloaded and global Python is not changed. Subsequent helpers
use `./.venv/bin/python -B` to avoid source-tree bytecode caches.

All generated runtime artifacts belong under `./outputs/`; `.venv/` is the
local environment exception. Tracked source edits stay in place. Existing
user artifacts are not moved or deleted. Routine reversible project work
has standing authorization; host/tool permission gates, device access,
network installation, image construction, VM launch and target changes
retain their independent permissions.

Developer/Agent bootstrap and validation example:

```bash
python3 -B scripts/workflow/project_workspace.py
./.venv/bin/python -B -m unittest discover -s tests -v
```

## Get started: tell the Agent “Start customizing the system”

**This is an AI Agent Skill.** Load `SKILL.md` / `AGENTS.md` in an Agent
with host execution access, then say:

> Start customizing the system

The Agent checks host capabilities and prepares the workspace, resolves only
missing intent/target information, then selects SSH, ADB, managed TTL/picocom
or local access and its actual interface. The review shows the real SSH/ADB
endpoint or the TTL port and baud; a missing interface blocks approval.
It explains the read-only probes,
privacy, local monitor and stages, and waits for plan approval before device
access or server startup. The confirmed plan includes the localhost monitor
by default; explicit monitor opt-out is honored. After approval the monitor
starts before probes and the Agent reports only the actual verified URL.

Authorized SSH/ADB/TTL collection uses one persistent session with fixed
read-only probes. Legacy passive TTL capture remains available. After evidence
analysis, image goals gather missing OS/version, boot medium and feature
requirements one at a time, then continue through supported planning and
separately approved image construction or optional QEMU verification.

You do not need to choose Python, Lima or QEMU arguments or prepare a second
computer. An Agent without execution access must explain that limitation.
Physical ARM image assembly and flashing remain unsupported without a
verified board adapter, BSP/DTB/bootloader and recovery path.

See the [guided interaction flow](references/interactive-agent-flow.md),
[managed device sessions](references/device-session.md) and [Agent agreement](AGENTS.md).
**Commands below are internal development/Agent examples, not user onboarding.**

> **Project identity: AI Agent Skill.** The Agent guides transport selection,
> evidence collection, compatibility reasoning, image-build planning and
> approval. All Python commands below are optional supporting tools, **not**
> an independent device manager product. Start from [SKILL.md](SKILL.md) and
> [Agent workflow](references/agent-workflow.md).
>
> **Build status:** implemented helpers support inspected VM RAW/QCOW2
> conversion, limited offline RootFS customization and separately approved
> AMD64 QEMU guest-health verification. Real image builds and guest boots
> remain unverified; physical-device image assembly and flashing are unsupported.
>

AI Agent Skill for read-only discovery, maintenance planning and limited
offline VM image customization for Ubuntu, Debian and Armbian systems.

## Current capabilities and validation

“Implemented” describes code that exists; “validated” requires an actual
test result. The maintained capability matrix, test record and remaining
work are in [Roadmap and acceptance](references/roadmap.md).

| Capability | Implemented scope | Validation boundary |
| --- | --- | --- |
| Device discovery and evidence | Fixed read-only SSH / ADB / local probes, persistent SSH/ADB/picocom sessions, legacy passive TTL capture, SHA-256 dossiers, comparisons and software topology | Python tests passed on macOS; real-device integration unverified |
| Planning and archives | JSON safe-subset profiles, local drift plans, explicit-file snapshots, device/session catalog, execution-disabled task plans | No profile application, automatic rollback or authenticated hardware identity |
| VM images | Read-only guest inspection, compatibility gates, RAW/QCOW2 conversion, private-copy hostname/MOTD customization, identity cleanup and public-key-only NoCloud seed | Real qemu-img/libguestfs builds unverified; no arbitrary packages or scripts |
| Boot verification | Static-image and ARM log evidence adapters; separate AMD64 QEMU Guest Agent health backend | Mocked guest tests passed; no real guest or physical-device boot validated |
| Agent experience | Pure next-step/consent policy, project workspace bootstrap, native Linux or existing Mac Lima adapter, plan-approved localhost monitor with opt-out and offline HTML viewer | Local HTTP/socket tests passed; real Lima, browser and full Agent handoffs unverified |

The guided policy currently ends inspect / diagnose / maintain goals after
evidence analysis. Separate task planners exist, but automatic diagnosis,
maintenance execution and recovery are not implemented. Installer ISO creation,
physical-board IMG/BSP assembly, installed-system cloning and flashing are
also unsupported. A NoCloud seed ISO is not an OS installer ISO.

## Terminology

| English term | Chinese term | Meaning in this project |
| --- | --- | --- |
| Inspection / verification | 检查／验证 | Inspection gathers observations; verification checks a specific requirement. Hash verification alone does not establish authenticity or bootability. |
| Evidence session / dossier / manifest | 证据会话／设备档案／清单 | A session contains captured evidence; a dossier summarizes it; a manifest records files and hashes. |
| Artifact bundle | 产物包 | A published image, seed, configuration and build manifest, not just one image file. |
| Guest / build host | 来宾／构建主机 | The system inside a VM / the environment running image tools. |
| Bootloader / pinmux | 引导加载程序／引脚复用 | Retain tool, property and format identifiers unchanged in both languages. |
| Public-key-only NoCloud seed | 仅使用公钥的 NoCloud 种子 | Initialization data using a public SSH key, without passwords or private keys; not an OS installer. |
| Feature preview / live preview | 功能预览／实时预览 | An early feature / the optional read-only localhost progress observer. |

Use **implemented / 已实现**, **tested / 已测试**, **unverified / 未验证** and
**unsupported / 不支持** as defined in the [roadmap](references/roadmap.md#status-terminology).
Record test scope with each result. Preserve machine-readable states such as
`complete`, `blocked`, `failed` and `boot_confirmed` unchanged; completion of
a static check is not confirmation of guest boot.

## Interactive device discovery

Start a guided connection and evidence collection workflow:

```bash
./.venv/bin/python -B scripts/workflow/collect.py
```

Select SSH, ADB, TTL (passive RX) or local. The workflow saves raw category-specific evidence and a `manifest.json` with paths and SHA-256 hashes under a new local directory. It does **not** perform hardware modification, device flashing or automatically upload diagnostics. This legacy TTL mode requires optional `pyserial`.

See [Device discovery](references/device-discovery.md) for transport prerequisites, pinmux limitations and the evidence layout.

For an approved managed interactive SSH/ADB/TTL session, the Agent uses the
persistent adapter instead of the legacy collector:

```bash
# Only after approval of the actual connection and monitoring plan.
./.venv/bin/python -B scripts/workflow/adaptive.py \
  --transport ssh --target trusted-host-alias \
  --output ./outputs/managed-session-001 \
  --interactive-shell-approved --preview-approved --yes
```

Use the observed serial port/baud for managed TTL. Unknown, login and U-Boot
prompts block shell probes; a single blank-line wake requires separate
confirmation that the input line is empty. Explicit monitor opt-out omits
`--preview-approved`. Missing tools or failed observer startup must be reported
accurately. See [device-session guards](references/device-session.md).


## Developer helper examples (not user onboarding)

Run local Linux commands on the target machine (for example Ubuntu Server / Armbian):

```bash
bash scripts/detect/system.sh
bash scripts/detect/network.sh
./.venv/bin/python -B scripts/safety/validate_profile.py profiles/base/ubuntu-server.json
./.venv/bin/python -B scripts/system/plan.py profiles/base/ubuntu-server.json
./.venv/bin/python -B -m unittest discover -s tests -v
```

Run a remote, read-only inventory from a machine with OpenSSH and a configured Host alias:

```bash
./.venv/bin/python -B scripts/remote/ssh_probe.py ubuntu-server
```

Create a snapshot of explicitly selected local files:

```bash
./.venv/bin/python -B scripts/safety/snapshot.py --output-dir ./outputs/snapshot-001 ./outputs/sample-input.txt
```

Snapshots do not provide an automatic restore capability. They should be stored in a secure location.

## Documentation

- [SKILL.md](SKILL.md) — Agent entry point
- [V0.2 operations](references/v0.2-operations.md) — command usage and limitations
- [Image design](references/image-building.md) — backend selection
- [System management](references/system-management.md) — desired-state workflow
- [ARM diagnostics](references/arm-hardware.md) — DTB / PHY / UART
- [Safety](references/safety.md) — approvals and recovery rules
- [Roadmap](references/roadmap.md) — upcoming milestones

Profile JSON is validated by a **narrow standard-library validator**; it is not a general-purpose JSON Schema implementation. YAML examples are illustrative and are not executable profiles yet.

Do not include credentials in profiles or commit any machine-generated diagnostics containing secrets.

## Structured device archives (discovery workflow)

Collect a session with the existing interactive wizard, then build its evidence-indexed dossier:

```bash
./.venv/bin/python -B scripts/workflow/collect.py
./.venv/bin/python -B scripts/workflow/dossier.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/compare.py ./outputs/example-device-session-001/device.json ./outputs/example-device-session-002/device.json
```

Dossier creation verifies each evidence file's SHA-256 digest. Missing collection is recorded as an evidence gap, not proof that hardware is absent. The comparison reports observed identity changes and evidence-file changes; it does not by itself diagnose a fault. Detailed guide: [device discovery](references/device-discovery.md).

The preliminary device-driver software graph is implemented; a fully verified pin/electrical topology is not yet available. No target-writing commands are performed by these utilities.

## Device-to-driver topology (read-only)

New discovery sessions collect limited sysfs binding evidence from network, serial,
GPIO, platform, I2C, SPI and MDIO devices. Generate the conservative topology:

```bash
./.venv/bin/python -B scripts/workflow/collect.py
./.venv/bin/python -B scripts/workflow/dossier.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/topology.py ./outputs/example-device-session-001
```

The new `topology.json` stores device and driver nodes, observed `bound_to`
edges, source evidence path/line, and unavailable or unbound observations.
Its meaning is **Linux driver bindings only**, not verified physical PCB pinout,
PHY signaling, electrical voltages, or full SoC pinmux relationships. Existing
sessions without new probes produce explicit `not_collected` gaps.
Use [device discovery](references/device-discovery.md) for further context.

## Device-tree and runtime graph (experimental)

For **new** Linux/Armbian sessions with `dtc` installed on the target,
the collector captures a decompiled DTS alongside driver bindings and
platform-device `of_node` paths. All probes remain read-only.

```bash
./.venv/bin/python -B scripts/workflow/collect.py
./.venv/bin/python -B scripts/workflow/device_tree.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/topology.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/link_graph.py ./outputs/example-device-session-001
```

Outputs:

- `device-tree.json`: DTS node hierarchy, selected properties, and supported phandle references.
- `topology.json`: observed Linux sysfs device ↔ driver bindings.
- `linked-hardware.json`: combined graph, including observed `of_node` links between platform devices and DTS nodes.

Every input is verified against the session manifest SHA-256. Missing or truncated DTS data yields explicit gaps. Numeric phandle references are marked **candidates**, not confirmed specifier decoding; pinctrl/clock/reset cell counts require binding-specific analysis. Only software relationships derived from hash-verified evidence are represented: physical header pins, PCB routes, electrical levels and functional hardware behavior remain unverified.

The parser supports common `dtc` output syntax; it is not a replacement for libfdt/dtc and does not interpret overlays or vendor-specific properties fully.

## Generic hardware discovery policy

This project is **device-agnostic**. There is no built-in target board, no preset
SoC and no assumption that Device Tree, GPIO, MDIO or any other interface exists.
Collection is evidence-driven; adapters for specific vendors or boards, if added,
must remain optional extensions.

After a discovery session, determine which classes of diagnostics were available:

```bash
./.venv/bin/python -B scripts/workflow/capabilities.py ./outputs/example-device-session-001
```

The output `capabilities.json` describes observation availability (`available`,
`partial`, `unknown`), **not** a claim that the physical peripheral is present
or functioning. Example YAML is under `profiles/examples/` and is not yet
consumed by the JSON profile execution engine.

## Adaptive, capability-aware discovery (feature preview)

Use the staged workflow to avoid trying every deep probe blindly. It first
collects basic OS/kernel/CPU/RAM data, then checks read-only availability of
DT, sysfs, pinctrl, buses and diagnostic utilities. Only supported detailed
probes run; skipped probes and reasons are recorded. Each probe writes a
checkpointed `manifest.json` so interrupted sessions can be inspected.

```bash
# Interactive SSH / ADB / TTL / local wizard
./.venv/bin/python -B scripts/workflow/adaptive.py

# Explicitly approved unattended read-only collection (preconfigured SSH alias)
./.venv/bin/python -B scripts/workflow/adaptive.py --transport ssh --target my-linux-host \\
  --output ./outputs/new-session-001 --modules auto --yes

# Select only specific modules
./.venv/bin/python -B scripts/workflow/adaptive.py --transport local --target local \\
  --modules network,drivers --output ./outputs/new-session-002 --yes
```

**Restrictions:** `--yes` explicitly authorizes only read-only probes; it does
not authorize writes. TTL is still passive serial RX only. Session directories
must be new, and their parent directory must already exist. Collected files may
contain sensitive host/network identifiers and are never auto-uploaded.
Without `--interactive-shell-approved`, these examples use the legacy
per-command SSH/ADB or passive TTL path. For interactive customization, use
the separately approved persistent adapter described above.

## Device catalog and interactive manager

The optional `scripts/workflow/manage.py` helper maintains a local device
catalog. It records a stable user-defined device ID and a connection
transport/target, then stores each collection session separately. It never
embeds passwords in its catalog.

```bash
# Interactive menu
./.venv/bin/python -B scripts/workflow/manage.py

# Enumerate candidate configured SSH Host aliases, authorized ADB devices,
# local serial-port names, and the local target
./.venv/bin/python -B scripts/workflow/manage.py discover

# Register a target without contacting it
./.venv/bin/python -B scripts/workflow/manage.py add lab-server --transport ssh --target server-alias

# View catalog; collect using the existing staged read-only engine
./.venv/bin/python -B scripts/workflow/manage.py list
./.venv/bin/python -B scripts/workflow/manage.py collect lab-server --modules hardware,drivers,network

# Inspect stored sessions and category summaries
./.venv/bin/python -B scripts/workflow/manage.py sessions lab-server
./.venv/bin/python -B scripts/workflow/manage.py inspect lab-server SESSION_ID
```

The legacy manager catalog defaults to `./outputs/device-manager/registry.json` and
captures are under `./outputs/device-manager/devices/<id>/sessions/<session>/`.
Directories and the catalog are created with restrictive permissions.
`--data-dir` is enforced as a private directory under `./outputs/` by the
Agent workspace contract. The default manager location is no longer in the home directory.

Connection discovery enumerates candidates; SSH aliases are read from explicit
`Host` entries in the primary SSH config (without expanding `Include` or
wildcards). ADB uses `adb devices` and may start the local ADB server. Serial
discovery lists device names but does not open serial ports. It does not
establish connectivity or authenticate to discovered candidates.

The `collect` command asks for confirmation unless given `--yes`;
`--yes` authorizes only fixed read-only evidence probes. The legacy manager uses passive TTL
RX capture, without transmitting serial bytes, though opening adapters may
affect control signals. Raw files may contain identifiers and must not be
automatically published.

The manager provides a terminal interaction. The optional localhost status
preview and offline HTML explorer described below are implemented viewers.
A browser device-control dashboard, automatic grouping by authenticated
device identity, resumable collection and physical pin maps are not implemented.

## Hardware explorer and task selection (feature preview)

The terminal manager now supports **Explore**. It reads the selected
session's SHA-256 verified evidence to assemble a software hardware graph,
browse node relationships and prepare an **execution-disabled** plan.

```bash
# Interactive: choose 7. Explore from device manager
./.venv/bin/python -B scripts/workflow/manage.py

# List nodes from a saved session
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID

# Inspect a specific node and its relationships
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID --node 'device:platform:example-controller'

# Generate a diagnosis plan scoped to a verified node (no target actions)
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID \
  --task diagnose --node 'device:platform:example-controller' \
  --goal 'Investigate why the controller is not responding'

# Run standalone wizard on a session directory
./.venv/bin/python -B scripts/workflow/explore.py ./outputs/device-manager/devices/lab-server/sessions/SESSION_ID

# Generate a safe JSON plan file without overwriting existing plans
./.venv/bin/python -B scripts/workflow/explore.py SESSION_DIRECTORY --mode plan \
  --task maintain --output ./outputs/my-plan.json
```

Supported plan kinds: `diagnose`, `maintain`, `image`. A plan references
observed nodes, software relationships and collection gaps, but **does not
execute commands**, modify configurations, build an image or authorize
flashing. `maintain` execution remains unimplemented. Explorer `image` plans
do not invoke the separate VM image pipeline described below. Evidence gaps
and incomplete sessions must be resolved before relying on the resulting analysis.

This is currently a text-oriented node list, not a graphical/interactive
node-edge canvas. Board-specific physical pinout and electrical behavior
remain outside the scope of software evidence alone.

## Offline graphical hardware explorer (feature preview)

An interactive **local HTML file** can be exported from a verified evidence
session. No HTTP service, external libraries, CDN or device connection is
required to browse it.

```bash
# From the registered device manager (command 8 in the interactive menu)
./.venv/bin/python -B scripts/workflow/manage.py browse lab-server SESSION_ID

# Custom destination (must not exist; never overwrites)
./.venv/bin/python -B scripts/workflow/manage.py browse lab-server SESSION_ID --output ./outputs/lab-hardware.html

# Directly from an existing collection session
./.venv/bin/python -B scripts/workflow/export_html.py SESSION_DIRECTORY --output ./outputs/hardware.html
```

Open the resulting HTML file locally in a browser. The left panel supports
search and type filtering (device / driver / device-tree node); the right
panel displays node attributes, related nodes, evidence source and collection
gaps. Clicking a relationship jumps to that node.

Security and scope:

- It validates the session's evidence SHA-256 hashes before rendering.
- Data is embedded as escaped JSON and written with private file permissions.
- The page has a restrictive Content Security Policy and no network access.
- Collected source material may include private device identifiers; do **not**
  upload the HTML without reviewing/redacting its content.
- This is a browser-based **offline viewer**, not a server application or
  interactive device controller. Node properties are software evidence, not
  verified physical header pinout or electrically measured conditions.
- Task execution remains disabled; diagnose / maintain / image still create
  plans only.

## Image portability pipeline (initial working backend)

Once a target's evidence session is collected, select **virtual-machine**
or **physical-device**. The planner verifies every source evidence file hash
and separately checks a *locally supplied base image* against an independently
obtained SHA-256. It records observed target architecture, the operator-declared
source architecture, readiness gaps, and the intended output format.

```bash
# Generate plan for an existing verified base image and a VM target
./.venv/bin/python -B scripts/workflow/image_plan.py SESSION_DIRECTORY \
  --target virtual-machine --format qcow2 \
  --source ./outputs/sources/base.img \
  --sha256 VERIFIED_64_HEX_SHA256 --source-arch amd64 \
  --output ./outputs/image-plan.json

# The same plan can be created from a registered device
./.venv/bin/python -B scripts/workflow/manage.py image-plan lab-server SESSION_ID \
  --target virtual-machine --format qcow2 \
  --source ./outputs/sources/base.img \
  --sha256 VERIFIED_64_HEX_SHA256 --source-arch amd64 \
  --output ./outputs/image-plan.json

# Once the plan reports build_allowed=true, perform OFFLINE conversion
# (requires qemu-img installed on the build host)
./.venv/bin/python -B scripts/workflow/build_image.py ./outputs/image-plan.json \
  --output ./outputs/output.qcow2
```

This generates an image and `output.qcow2.manifest.json`, including the
SHA-256 digest and virtual size. It **converts an inspected source image**;
source inspection does not prove bootability. The converter does not capture
the running system, install drivers, customize packages, reset machine identities, or make the output
bootable on arbitrary hardware. The created image requires a separate VM
boot test (machine type, firmware and virtual drivers) before deployment.

For `--target physical-device --format raw`, the planner returns explicit
blockers and **does not allow assembly** until a board-specific bootloader,
kernel/DTB or ACPI support, firmware, storage partition scheme and recovery
path are verified. A generic ARM64 system cannot be made universally
bootable merely by changing an image format.

Never pass block devices as input or output. The converter rejects paths
under `/dev`, `/proc` and `/sys`, output overwrites, unsupported
input formats, and images with a QEMU backing file. Keep source image
integrity metadata and licensing records. Source architecture must be
measured by guest inspection and match both the declaration and discovered
target. Missing tools or incomplete inspection block conversion; declaring
`--source-arch` alone cannot authorize it.

## Live Skill status preview (included in the approved plan)

**AI Agent first; browser page is only an observer.** After the connection
method and actual interface are chosen, the Agent explains and requests
approval for the read-only plan including a loopback-only status page.
Once approved, the backend starts the viewer before probes and returns the
actual URL. The user may explicitly opt out of monitoring without blocking
collection.

For a session that already exists (or is currently collecting):

```bash
./.venv/bin/python -B scripts/workflow/preview.py SESSION_DIR --port 8765
# Browser: http://127.0.0.1:8765/
```

The page polls the local checkpoint manifest every 2 seconds. In later
Agent-led stages (analysis / image planning / conversion / verification),
the Agent may publish safe stage/count updates:

```bash
./.venv/bin/python -B scripts/workflow/status.py SESSION_DIR \
  --stage image-plan --state running --completed 1 --total 3
```

Preview is read-only, bound to `127.0.0.1`, has no commands API, and
does **not** expose raw capture files. It is not a device manager, and
is not required for Skill execution. Stop with Ctrl+C. See
[Optional live preview](references/live-preview.md) for privacy,
consent and lifecycle rules.

### Skill-managed live preview lifecycle (plan-approved)

After the Agent explains the entire connection and monitoring plan and
receives confirmation, it starts the observer *before* collection with
`--preview-approved`. The Agent does not ask a second preview question.
The host runs only approved read-only probes (`--yes` in the internal
CLI); viewer consent does not authorize target system modification:

```bash
./.venv/bin/python -B scripts/workflow/adaptive.py \
  --transport ssh --target trusted-host-alias \
  --output ./outputs/run-003 --yes --preview-approved
```

After creating the session directory, the collector starts a localhost-only
preview, returns the verified URL, and continues probing. A failed preview
does **not** stop collection. The page remains available for final review
until the user requests it be closed.

```bash
./.venv/bin/python -B scripts/workflow/preview_control.py status ./outputs/run-003
./.venv/bin/python -B scripts/workflow/preview_control.py stop ./outputs/run-003
```

For a preexisting session, `preview_control.py start SESSION_DIR --approved`
starts a preview without rerunning collection. The helper selects an
available local port, checks that the observer is responsive, and records
only private process metadata. A stopped/stale preview cannot authorize
system actions. If stale, `clear-stale` removes only its local record and
never sends an unchecked signal. The session directory must be private
(mode 0700). See [live preview](references/live-preview.md).

After each iteration, the Agent should give a concise completion summary,
accurate test status, and **one actionable next-step follow-up**. In
supported chat interfaces, offer a clickable “Continue to the next step” control rather
than requiring the user to retype a command.

### Live progress throughout the image pipeline

When a user has approved the plan including local monitoring, the image helpers
automatically update the same preview via verified session references.
Stages: `image-plan`, `image-build`, `rootfs-build`, `first-boot` (NoCloud),
and `verify` (including guest-health verification). Each reports concrete
milestones and distinguishes completion, compatibility blockers and execution
failures. A QEMU smoke attempt is
**not** proof of a guest boot.

No preview means no automatic status-file writes. A closed preview is not
restarted implicitly. The Skill remains the controller and the browser is
a passive view. For the phase mapping and privacy rules see
[Live preview](references/live-preview.md).

### Read-only source image introspection

The Agent Skill can now inspect an existing RAW/QCOW2 disk source and create
a traceable compatibility decision, **before** invoking the image conversion
helper. It requires `qemu-img` and read-only libguestfs utilities to
establish GPT/MBR partitioning, guest Linux architecture/OS, installed kernel
and BIOS/UEFI + bootloader. Missing evidence blocks conversion.

```bash
./.venv/bin/python -B scripts/workflow/image_inspect.py ./outputs/sources/base.img \
  --sha256 TRUSTED_SOURCE_SHA256 \
  --output ./outputs/source-inspection.json

./.venv/bin/python -B scripts/workflow/image_plan.py SESSION_DIR \
  --target virtual-machine --format qcow2 --source ./outputs/sources/base.img \
  --sha256 TRUSTED_SOURCE_SHA256 --source-arch amd64 \
  --output ./outputs/image-plan.json
```

`image-plan.json` now includes observed source details and a per-check
compatibility matrix with evidence. `build_image.py` refuses uninspected
or changed images even if an editable JSON plan claims they are allowed.
Physical device builds still require independent board-specific components.
See [image building](references/image-building.md). Synthetic inspection
tests passed on macOS; real libguestfs inspection remains unverified.

### Offline Portable RootFS Builder (VM only)

The **AI Agent Skill** can now preview and, after explicit separate approval,
build a limited customized Linux VM RootFS bundle from a source image that
passed `image_plan.py` compatibility inspection. A physical board/IMG
requires an independent verified BSP and is still blocked.

Strict recipe example: `profiles/examples/rootfs-config.json`. Supported
changes are hostname, MOTD and a public-key-only NoCloud first-boot seed.
The builder clones the original image, modifies **only its private copy**
with `virt-customize --no-network`, applies narrowly scoped
`virt-sysprep` machine-id/SSH host-key cleanup, rechecks the guest image,
and publishes hashes and a manifest. It does **not** install packages,
run arbitrary commands or prove bootability.

```bash
# Check requirements and exact planned operations without writing an image.
./.venv/bin/python -B scripts/workflow/rootfs_builder.py ./outputs/image-plan.json \
  --config ./outputs/rootfs-config.json --dry-run

# Only after Agent obtains explicit separate approval.
./.venv/bin/python -B scripts/workflow/rootfs_builder.py ./outputs/image-plan.json \
  --config ./outputs/rootfs-config.json --output-dir ./outputs/new-rootfs-bundle --approved

# Independently verify the published image, NoCloud seed and hashes.
./.venv/bin/python -B scripts/workflow/rootfs_builder.py \
  --verify-bundle ./outputs/new-rootfs-bundle
```

Requires qemu-img and libguestfs tools on the **build host**. The source
guest must be shut down and must contain cloud-init configuration. NoCloud
first boot/SSH regeneration, VM boot, and machine-specific secret
sanitization remain unverified until separately audited. The output is
not suitable for direct physical flashing. Full constraints are in
[RootFS Builder Skill workflow](references/rootfs-building.md).

The RootFS artifact bundle also contains a sanitized `build-config.json`
(no original public-key filesystem path) and the `image_plan_sha256`
provenance field for reproducibility. The build manifest verifies both
configuration and image hashes.

### QEMU first-boot health verification (amd64 VM only)

The Skill now offers a separately approved, isolated **first-boot health
check** for a completed Portable RootFS Builder bundle:

```bash
./.venv/bin/python -B scripts/workflow/rootfs_builder.py --verify-bundle ./outputs/rootfs-bundle
./.venv/bin/python -B scripts/workflow/verify_first_boot.py \
  --bundle ./outputs/rootfs-bundle --timeout 300 \
  --report ./outputs/first-boot-health.json --approved

# For UEFI guests additionally supply:
# --ovmf-code /trusted/OVMF_CODE.fd --ovmf-vars /trusted/OVMF_VARS.fd
```

This runs a disposable QEMU TCG snapshot with restricted guest DHCP,
no Internet/host routing or forwarded ports, a private UNIX Guest Agent
socket and a verified NoCloud seed ISO. It requires preinstalled
qemu-guest-agent and Python 3 in the guest. A fresh challenge and a fixed
read-only guest script check Linux boot, systemd, cloud-init and expected
instance ID, hostname, initialized machine-id and SSH host keys, SSH
service, and a configured guest network interface. All must pass for
`boot_confirmed=true`. Exit codes and serial output are **not** proof.
Missing prerequisites, timeout or failed checks remain blocked/failed.
The report stores health checks as booleans, alongside metadata such as
artifact hashes and status. It does not store machine IDs, keys, secrets or
raw guest command output. The original disk is re-hashed after shutdown.

RootFS staging now removes stale `/var/lib/cloud` state **only in the
private cloned image**, allowing fresh NoCloud instance initialization.
The build result also retains its original discovery session link for
optional Skill preview status. No physical-board BSP, firmware or flash
support was added. See [First boot validation](references/first-boot-verification.md).

### macOS local test path compatibility

Python `tempfile.TemporaryDirectory()` may return paths under
`/var/folders` while macOS resolves those files to `/private/var/folders`.
The offline RootFS builder, Cloud Image E2E runner and Lima path validator
canonicalize these **verified, system-owned** aliases for local paths.
The restrictions on user-created symlinks, pre-existing
destinations, directory traversal and block-device/pseudo-filesystem
targets remain unchanged. The unit tests compare resolved paths where
the collector or QEMU intentionally canonicalizes them.

The standard command `./.venv/bin/python -B -m unittest discover -s tests -v` passed on
macOS with the default temporary directory and local test socket permissions.
QEMU and libguestfs execution is mocked in this suite; local preview HTTP
and fake Guest Agent socket tests do run. See the
[validation record](references/roadmap.md#validation-record) for counts and scope.

### Ubuntu Cloud Image end-to-end helper (real execution unverified)

`scripts/workflow/cloud_image_e2e.py` coordinates preflight, source checks,
inspection/planning, RootFS customization, bundle verification and guest-health
verification on a prepared Linux build host. It accepts a trusted local image
or an explicitly requested download from its pinned Ubuntu Cloud Image URL
and SHA-256. This is hash checking, not upstream signature verification;
availability of the pinned download has not been validated by the test suite.
Offline build and VM boot require distinct explicit approvals. Missing tools,
firmware or guest dependencies block execution; the helper does not install
QGA or other packages. Its full-pipeline tests are synthetic and do not prove
a real build or boot. Native Linux and existing Mac Lima adapters are
implemented, but real Lima execution remains unverified.
