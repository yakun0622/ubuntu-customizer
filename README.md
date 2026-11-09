# ubuntu-customizer

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
