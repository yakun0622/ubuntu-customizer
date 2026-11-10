# ubuntu-customizer


## 开始使用：只需要告诉 Agent「开始定制系统」

**这是 AI Agent Skill，不是需要逐条执行命令的工具。** 在已加载本仓库
`SKILL.md` / `AGENTS.md` 且具备主机执行权限的 Agent 中，直接说：

> 开始定制系统

Agent 会逐步自动检查当前 Mac/Linux 的可用能力、识别目标类型、采集已获授权的
设备信息、分析镜像、选择本机运行后端，并按实际结果继续推进。中途**仅在需要
选择目标、批准设备访问/镜像构建/隔离启动或处理阻断时**进行简短交互。实时预览
页面是可选的，默认不开启；QEMU 也只是按需选择的验证工具。

用户不必选择 Lima、QEMU、Python 参数，也不必先准备另一台电脑。若 Agent
没有连接到你的电脑或没有实际执行权限，它必须说明这一前提，不能声称已经
在你的 Mac 上运行了命令。实体 ARM 设备的日志和镜像可以只读分析，但无已验证
BSP/DTB/Bootloader/恢复方案时不会自动制作可刷写镜像。

参见 [傻瓜式交互流程](references/interactive-agent-flow.md) 与 [Agent 工作约定](AGENTS.md)。
**以下命令示例仅供开发、调试或 Agent 调用，不是普通用户的启动步骤。**


> **Project identity: AI Agent Skill.** The Agent guides transport selection,
> evidence collection, compatibility reasoning, image-build planning and
> approval. All Python commands below are optional supporting tools, **not**
> an independent device manager product. Start from [SKILL.md](SKILL.md) and
> [Agent workflow](references/agent-workflow.md).
>
> **Build status:** existing image conversion is offline VM RAW/QCOW2 format
> conversion only; portable physical-device images, complete RootFS creation,
> installed-system cloning and guaranteed first boot are not yet implemented.
> No actual device boot validation has been completed.
>

AI Agent Skill for Ubuntu image customization and safe maintenance of installed Ubuntu, Debian and Armbian systems.

## Current status: v0.2 (read-only foundation)

Implemented:

- Read-only Linux system and network detection
- JSON profile validation
- Local profile-to-host drift plan for packages, hostname, timezone
- Read-only SSH inventory through an existing OpenSSH host alias
- Local backups of explicitly named regular files, with SHA-256 manifest
- Unit tests for profile validation and planning
- Interactive device discovery over SSH / ADB / TTL / local with a local evidence manifest

**Not implemented:** applying profile changes, remote writes, automatic rollback,
full installer ISO or physical-board IMG assembly, installed-system cloning
and physical flashing. Existing RAW/QCOW2 *offline conversion* is available
behind conservative guest inspection gates, but is not a complete OS builder.

## Interactive device discovery

Start a guided connection and evidence collection workflow:

```bash
python3 scripts/workflow/collect.py
```

Select SSH, ADB, TTL (passive RX) or local. The workflow saves raw category-specific evidence and a `manifest.json` with paths and SHA-256 hashes under a new local directory. It does **not** perform hardware modification, device flashing or automatically upload diagnostics. TTL requires optional `pyserial`.

See [Device discovery](references/device-discovery.md) for transport prerequisites, pinmux limitations and the evidence layout.

## Quick start

Run local Linux commands on the target machine (for example Ubuntu Server / Armbian):

```bash
bash scripts/detect/system.sh
bash scripts/detect/network.sh
python3 scripts/safety/validate_profile.py profiles/base/ubuntu-server.json
python3 scripts/system/plan.py profiles/base/ubuntu-server.json
python3 -m unittest discover -s tests -v
```

Run a remote, read-only inventory from a machine with OpenSSH and a configured Host alias:

```bash
python3 scripts/remote/ssh_probe.py ubuntu-server
```

Create a snapshot of explicitly selected local files:

```bash
python3 scripts/safety/snapshot.py --output-dir /tmp/uc-snapshot-001 /etc/hostname
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
python3 scripts/workflow/collect.py
python3 scripts/workflow/dossier.py ./devices/example-device/session-001
python3 scripts/workflow/compare.py ./devices/example-device/session-001/device.json ./devices/example-device/session-002/device.json
```

Dossier creation verifies each evidence file's SHA-256 digest and distinguishes missing collection from missing hardware. The comparison reports observed identity changes and evidence-file changes; it does not by itself diagnose a fault. Detailed guide: [device discovery](references/device-discovery.md).

The preliminary device-driver software graph is implemented; a fully verified pin/electrical topology is not yet available. No target-writing commands are performed by these utilities.

## Device-to-driver topology (read-only)

New discovery sessions collect limited sysfs binding evidence from network, serial,
GPIO, platform, I2C, SPI and MDIO devices. Generate the conservative topology:

```bash
python3 scripts/workflow/collect.py
python3 scripts/workflow/dossier.py ./devices/example-device/session-001
python3 scripts/workflow/topology.py ./devices/example-device/session-001
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
python3 scripts/workflow/collect.py
python3 scripts/workflow/device_tree.py ./devices/example-device/session-001
python3 scripts/workflow/topology.py ./devices/example-device/session-001
python3 scripts/workflow/link_graph.py ./devices/example-device/session-001
```

Outputs:
- `device-tree.json`: DTS node hierarchy, selected properties, and supported phandle references.
- `topology.json`: observed Linux sysfs device ↔ driver bindings.
- `linked-hardware.json`: combined graph, including observed `of_node` links between platform devices and DTS nodes.

Every input is verified against the session manifest SHA-256. Missing or truncated DTS data yields explicit gaps. Numeric phandle references are marked **candidates**, not confirmed specifier decoding; pinctrl/clock/reset cell counts require binding-specific analysis. Only trusted software topology is represented: physical header pins, PCB routes, electrical levels and functional hardware behavior remain unverified.

The parser supports common `dtc` output syntax; it is not a replacement for libfdt/dtc and does not interpret overlays or vendor-specific properties fully.

## Generic hardware discovery policy

This project is **device-agnostic**. There is no built-in target board, no preset
SoC and no assumption that Device Tree, GPIO, MDIO or any other interface exists.
Collection is evidence-driven; adapters for specific vendors or boards, if added,
must remain optional extensions.

After a discovery session, determine which classes of diagnostics were available:

```bash
python3 scripts/workflow/capabilities.py ./devices/example-device/session-001
```

The output `capabilities.json` describes observation availability (`available`,
`partial`, `unknown`), **not** a claim that the physical peripheral is present
or functioning. Example YAML is under `profiles/examples/` and is not yet
consumed by the JSON profile execution engine.

## Adaptive, capability-aware discovery (preview)

Use the staged workflow to avoid trying every deep probe blindly. It first
collects basic OS/kernel/CPU/RAM data, then checks read-only availability of
DT, sysfs, pinctrl, buses and diagnostic utilities. Only supported detailed
probes run; skipped probes and reasons are recorded. Each probe writes a
checkpointed `manifest.json` so interrupted sessions can be inspected.

```bash
# Interactive SSH / ADB / TTL / local wizard
python3 scripts/workflow/adaptive.py

# Explicitly approved unattended read-only collection (preconfigured SSH alias)
python3 scripts/workflow/adaptive.py --transport ssh --target my-linux-host \\
  --output ./new-session-001 --modules auto --yes

# Select only specific modules
python3 scripts/workflow/adaptive.py --transport local --target local \\
  --modules network,drivers --output ./new-session-002 --yes
```

**Restrictions:** `--yes` explicitly authorizes only read-only probes; it does
not authorize writes. TTL is still passive serial RX only. Session directories
must be new, and their parent directory must already exist. Collected files may
contain sensitive host/network identifiers and are never auto-uploaded.
The older `collect.py` remains available for fully exhaustive baseline probes.

## Device catalog and interactive manager

The new `scripts/workflow/manage.py` is the **local device-management
entry point**. It records a stable user-defined device ID and a connection
transport/target, then stores each collection session separately. It never
embeds passwords in its catalog.

```bash
# Interactive menu
python3 scripts/workflow/manage.py

# Enumerate candidate configured SSH Host aliases, authorized ADB devices,
# local serial-port names, and the local target
python3 scripts/workflow/manage.py discover

# Register a target without contacting it
python3 scripts/workflow/manage.py add lab-server --transport ssh --target server-alias

# View catalog; collect using the existing staged read-only engine
python3 scripts/workflow/manage.py list
python3 scripts/workflow/manage.py collect lab-server --modules hardware,drivers,network

# Inspect stored sessions and category summaries
python3 scripts/workflow/manage.py sessions lab-server
python3 scripts/workflow/manage.py inspect lab-server SESSION_ID
```

The catalog defaults to `~/.local/share/ubuntu-customizer/registry.json` and
captures are under `~/.local/share/ubuntu-customizer/devices/<id>/sessions/<session>/`.
Directories and the catalog are created with restrictive permissions.
`--data-dir` selects a different *private* directory.

Connection discovery enumerates candidates; SSH aliases are read from explicit
`Host` entries in the primary SSH config (without expanding `Include` or
wildcards). ADB uses `adb devices` and may start the local ADB server. Serial
discovery lists device names but does not open serial ports. It does not
establish connectivity or authenticate to discovered candidates.

The `collect` command asks for confirmation unless given `--yes`;
`--yes` authorizes only fixed read-only evidence probes. TTL uses passive
RX capture, without transmitting serial bytes, though opening adapters may
affect control signals. Raw files may contain identifiers and must not be
automatically published.

This is a **terminal interaction**: a browser-based dashboard, automatic
device grouping by serial number, session resumption and physical pin map
visualization are not yet implemented.

## Hardware explorer and task selection (preview)

The terminal manager now supports **Explore**. It reads the selected
session's SHA-256 verified evidence to assemble a software hardware graph,
browse node relationships and prepare an **execution-disabled** plan.

```bash
# Interactive: choose 7. Explore from device manager
python3 scripts/workflow/manage.py

# List nodes from a saved session
python3 scripts/workflow/manage.py explore lab-server SESSION_ID

# Inspect a specific node and its relationships
python3 scripts/workflow/manage.py explore lab-server SESSION_ID --node 'device:platform:example-controller'

# Generate a diagnosis plan scoped to a verified node (no target actions)
python3 scripts/workflow/manage.py explore lab-server SESSION_ID \
  --task diagnose --node 'device:platform:example-controller' \
  --goal 'Investigate why the controller is not responding'

# Run standalone wizard on a session directory
python3 scripts/workflow/explore.py ~/.local/share/ubuntu-customizer/devices/lab-server/sessions/SESSION_ID

# Generate a safe JSON plan file without overwriting existing plans
python3 scripts/workflow/explore.py SESSION_DIRECTORY --mode plan \
  --task maintain --output ./my-plan.json
```

Supported plan kinds: `diagnose`, `maintain`, `image`. A plan references
observed nodes, software relationships and collection gaps, but **does not
execute commands**, modify configurations, build an image or authorize
flashing. `maintain` and `image` remain blocked from execution pending
implementation and separate approval. Evidence gaps and incomplete sessions
must be resolved before relying on the resulting analysis.

This is currently a text-oriented node list, not a graphical/interactive
node-edge canvas. Board-specific physical pinout and electrical behavior
remain outside the scope of software evidence alone.

## Offline graphical hardware explorer (preview)

An interactive **local HTML file** can be exported from a verified evidence
session. No HTTP service, external libraries, CDN or device connection is
required to browse it.

```bash
# From the registered device manager (command 8 in the interactive menu)
python3 scripts/workflow/manage.py browse lab-server SESSION_ID

# Custom destination (must not exist; never overwrites)
python3 scripts/workflow/manage.py browse lab-server SESSION_ID --output /tmp/lab-hardware.html

# Directly from an existing collection session
python3 scripts/workflow/export_html.py SESSION_DIRECTORY --output /tmp/hardware.html
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
python3 scripts/workflow/image_plan.py SESSION_DIRECTORY \
  --target virtual-machine --format qcow2 \
  --source /srv/images/base.img \
  --sha256 VERIFIED_64_HEX_SHA256 --source-arch amd64 \
  --output ./image-plan.json

# The same plan can be created from a registered device
python3 scripts/workflow/manage.py image-plan lab-server SESSION_ID \
  --target virtual-machine --format qcow2 \
  --source /srv/images/base.img \
  --sha256 VERIFIED_64_HEX_SHA256 --source-arch amd64 \
  --output ./image-plan.json

# Once the plan reports build_allowed=true, perform OFFLINE conversion
# (requires qemu-img installed on the build host)
python3 scripts/workflow/build_image.py ./image-plan.json \
  --output ./output.qcow2
```

This generates an image and `output.qcow2.manifest.json`, including the
SHA-256 digest and virtual size. It **converts an already bootable source
image**; it does not automatically capture the running system, install
drivers, customize packages, reset machine identities, or make the output
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
integrity metadata and licensing records. Source architecture is currently
an operator declaration and is **not** validated from guest filesystems;
this limitation is explicitly reported.

## Optional real-time Skill status preview

**AI Agent first, browser preview optional.** At the start of a device
discovery or image-build task the Skill asks whether the user wants to
enable a local status page. Default is off; declining never blocks the task.

For a session that already exists (or is currently collecting):

```bash
python3 scripts/workflow/preview.py SESSION_DIR --port 8765
# Browser: http://127.0.0.1:8765/
```

The page polls the local checkpoint manifest every 2 seconds. In later
Agent-led stages (analysis / image planning / conversion / verification),
the Agent may publish safe stage/count updates:

```bash
python3 scripts/workflow/status.py SESSION_DIR \
  --stage image-plan --state running --completed 1 --total 3
```

Preview is read-only, bound to `127.0.0.1`, has no commands API, and
does **not** expose raw capture files. It is not a device manager, and
is not required for Skill execution. Stop with Ctrl+C. See
[Optional live preview](references/live-preview.md) for privacy,
consent and lifecycle rules.

### Skill-managed live preview lifecycle (opt-in)

The Skill asks **是否开启本地实时运行预览？** before collection.
The default is off. After positive user consent, the Agent can activate
the preview **during** collection with `--preview-approved` (independent
from `--yes`, which approves read-only probes):

```bash
python3 scripts/workflow/adaptive.py \
  --transport ssh --target trusted-host-alias \
  --output ./sessions/run-003 --yes --preview-approved
```

After creating the session directory, the collector starts a localhost-only
preview, returns the verified URL, and continues probing. A failed preview
does **not** stop collection. The page remains available for final review
until the user requests it be closed.

```bash
python3 scripts/workflow/preview_control.py status ./sessions/run-003
python3 scripts/workflow/preview_control.py stop ./sessions/run-003
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
supported chat interfaces, offer a clickable “继续下一步” control rather
than requiring the user to retype a command.

### Live progress throughout the image pipeline

When a user has explicitly enabled the local preview, the image helpers now
automatically update the same preview via verified session references.
Stages: `image-plan`, `image-build`, `first-boot` (NoCloud), and
`verify`. Each reports concrete milestones and distinguishes completion,
compatibility blockers and execution failures. A QEMU smoke attempt is
**not** proof of a guest boot.

No preview means no automatic status-file writes. A closed preview is not
restarted implicitly. The Skill remains the controller and the browser is
a passive view. For the phase mapping and privacy rules see
[Live preview](references/live-preview.md).

### Read-only source image introspection

The Agent Skill can now inspect an existing RAW/QCOW2 disk source and create
a traceable compatibility decision, **before** invoking the image conversion
helper. It uses `qemu-img` and optional read-only libguestfs utilities to
establish GPT/MBR partitioning, guest Linux architecture/OS, installed kernel
and BIOS/UEFI + bootloader. Missing evidence blocks conversion.

```bash
python3 scripts/workflow/image_inspect.py /srv/images/base.img \
  --sha256 TRUSTED_SOURCE_SHA256 \
  --output ./source-inspection.json

python3 scripts/workflow/image_plan.py SESSION_DIR \
  --target virtual-machine --format qcow2 --source /srv/images/base.img \
  --sha256 TRUSTED_SOURCE_SHA256 --source-arch amd64 \
  --output ./image-plan.json
```

`image-plan.json` now includes observed source details and a per-check
compatibility matrix with evidence. `build_image.py` refuses uninspected
or changed images even if an editable JSON plan claims they are allowed.
Physical device builds still require independent board-specific components.
See [image building](references/image-building.md). Tests were added but
require execution on a supported build host; no CI was automatically run.

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
python3 scripts/workflow/rootfs_builder.py image-plan.json \
  --config rootfs-config.json --dry-run

# Only after Agent obtains explicit separate approval.
python3 scripts/workflow/rootfs_builder.py image-plan.json \
  --config rootfs-config.json --output-dir ./new-rootfs-bundle --approved

# Independently verify the published image, NoCloud seed and hashes.
python3 scripts/workflow/rootfs_builder.py \
  --verify-bundle ./new-rootfs-bundle
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
python3 scripts/workflow/rootfs_builder.py --verify-bundle ./rootfs-bundle
python3 scripts/workflow/verify_first_boot.py \
  --bundle ./rootfs-bundle --timeout 300 \
  --report ./first-boot-health.json --approved

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
The report stores only boolean checks, not machine IDs, keys, secrets or
raw guest command output. The original disk is re-hashed after shutdown.

RootFS staging now removes stale `/var/lib/cloud` state **only in the
private cloned image**, allowing fresh NoCloud instance initialization.
The build result also retains its original discovery session link for
optional Skill preview status. No physical-board BSP, firmware or flash
support was added. See [First boot validation](references/first-boot-verification.md).

### macOS local test path compatibility

Python `tempfile.TemporaryDirectory()` may return paths under
`/var/folders` while macOS resolves those files to `/private/var/folders`.
The offline RootFS builder and Cloud Image E2E runner now canonicalize
these **verified, system-owned** aliases when creating new local output
directories. The restrictions on user-created symlinks, pre-existing
destinations, directory traversal and block-device/pseudo-filesystem
targets remain unchanged. The unit tests compare resolved paths where
the collector or QEMU intentionally canonicalizes them.

```bash
cd ubuntu-customizer
git pull --ff-only origin main
python3 -m unittest discover -s tests -v
```

The macOS unit tests use mocks for QEMU and libguestfs. Real Ubuntu Cloud
Image end-to-end boots still require a suitable Linux build host and a
guest image with the required QEMU Guest Agent dependencies.
