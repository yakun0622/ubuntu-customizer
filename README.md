# ubuntu-customizer

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

**Not implemented:** applying profile changes, remote writes, automatic rollback, ISO/IMG/QCOW2 building and physical flashing. These are planned, not claimed as operational.

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
