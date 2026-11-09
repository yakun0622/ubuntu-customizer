---
name: ubuntu-customizer
description: Build or plan Ubuntu image customization and safely diagnose, provision, maintain, or recover installed Ubuntu, Debian and Armbian systems, including networking, drivers, UART, DTB, kernels and boot configuration.
---

# Ubuntu Customizer

Choose one workflow: **image**, **provision**, **maintain**, **diagnose**, **recover**.

## Device discovery first

When the user asks to work with a physical target or unknown Ubuntu/Armbian device, prefer `references/device-discovery.md`. Offer transport choices (SSH, ADB, TTL serial, local), then run `python3 scripts/workflow/collect.py` when the execution environment has access. Use the resulting `manifest.json` and category evidence before suggesting driver, DTB or kernel fixes. Distinguish pinmux evidence from verified physical PCB pinout. TTL access in this version is **passive log capture only**.

## Mandatory flow

1. Distinguish controlling/build host from the target; identify OS and architecture from evidence, record the board only if verified, and establish expected output.
2. Read only relevant reference files: `references/image-building.md`, `references/system-management.md`, `references/arm-hardware.md`, `references/safety.md`, `references/v0.2-operations.md`.
3. Inspect current state with read-only diagnostics. When execution access is missing, provide commands rather than pretending to have results.
4. Validate a JSON profile using `scripts/safety/validate_profile.py`. Unrecognized fields and unsafe execution modes are invalid.
5. Generate a local, read-only drift plan with `scripts/system/plan.py` if on the target Linux machine. A blocked plan must not be applied.
6. For an SSH target, use `scripts/remote/ssh_probe.py` only with a previously configured and trusted Host alias.
7. Classify proposed changes by R0–R4 risk. Present exact edits, dependencies, service impacts, approval requirements and verification steps.
8. For local file changes, use explicit file snapshots as a preparation step when appropriate. Never imply that snapshot creation ensures recovery.
9. Require user approval for modifications and verified recovery before sensitive operations. **There is no general mutation or rollback engine implemented yet.**
10. Report actual observations and any unverified assumptions.

## Available executable commands

```bash
python3 scripts/workflow/collect.py
bash scripts/detect/system.sh
bash scripts/detect/network.sh
python3 scripts/safety/validate_profile.py profiles/base/ubuntu-server.json
python3 scripts/system/plan.py profiles/base/ubuntu-server.json
python3 scripts/remote/ssh_probe.py configured-host-alias
python3 scripts/safety/snapshot.py --output-dir /secure/new-directory /etc/hostname
python3 -m unittest discover -s tests -v
```

## Image behavior

Image building is **design-only** in v0.2. Select backend by output format and release and describe verifiable instructions; do not claim that ISO, QCOW2, or board-specific IMG generation was completed.

## Risk classification

- R0: read-only discovery
- R1: offline plan, local artifact or profile validation
- R2: packages and ordinary service changes — approval
- R3: remote SSH/network/firewall, kernel or DTB edits — explicit scope, backup and recovery
- R4: disk writes, firmware flashing, U-Boot replacement — physical recovery plan and exact-device approval

Do not blindly flash images, install network-unsafe configuration, bypass SSH trust, or reboot without approval.

## Reporting

Include host identity, evidence, proposed changes, compatibility blockers, approved operations, snapshot details, performed verifications, outstanding risks and recovery instructions.

## Discovery dossier phase

After a completed discovery session, execute `python3 scripts/workflow/dossier.py <session-dir>` to create a verified, source-linked `device.json`. Read `gaps` and evidence status before asserting any hardware capability. To compare two sessions, run `python3 scripts/workflow/compare.py <old-device.json> <new-device.json>`. Compare device identity and raw evidence, but do not infer that changes in volatile counters prove hardware changes. Physical pin numbers and driver binding graphs remain unverified until separately supported by datasheets, schematics and deeper probes.

## Linux driver topology phase

For a new Linux discovery session, run `python3 scripts/workflow/topology.py <session-dir>` after evidence collection. Use `topology.json` for **observed sysfs device-driver binding edges only**; source file and line numbers must accompany conclusions. An unbound, missing, malformed or inaccessible driver path is not proof that the physical peripheral is absent. Treat DT pinctrl, IRQ mapping, physical header pinout, PCB routes, PHY electrical signals and voltages as *unverified* unless independently supported. For sessions collected before sysfs binding probes, the parser records explicit collection gaps.

## Device-tree and linked hardware graph

For a newly collected Linux session, use `scripts/workflow/device_tree.py` for software DTS references and `scripts/workflow/link_graph.py` to correlate observed platform device `of_node` symlinks with DTS nodes. Each input is verified through the evidence manifest. Treat missing or truncated DTS, unbound drivers and unresolved phandles as gaps; never infer physical PCB pin numbering, voltage, or a successfully functioning PHY. Numeric phandles are candidates pending binding-specific cell parsing. Do not modify DTB or hardware based only on these graphs.

## Generic device capability negotiation

Always treat the connected target as **unknown hardware** until read-only
evidence identifies it. Never default to a named board, vendor SoC, GPIO bank,
PHY, serial controller or physical pin header. After collection run
`python3 scripts/workflow/capabilities.py <session-dir>`. Choose subsequent
collection and analysis based on `available`, `partial` or `unknown`
observations, never guessing that an unknown component is absent. Use
`profiles/examples/generic-arm64-discovery.yaml` only as documentation for
ARM64, not as a universal preset or an executable profile. Prefer generic
analysers and make vendor/board adapters opt-in after identity verification.

## Adaptive discovery default

For a target with command-execution access, prefer
`python3 scripts/workflow/adaptive.py` over the legacy exhaustive collector.
It performs a minimal bootstrap, availability checks and scoped deeper probes.
If running unattended, require the user's prior authorization and use
`--yes` only for read-only probes; this flag must never imply permission to
modify target systems. Review `manifest.json` for skipped, unavailable,
truncated and failed observations before producing a hardware diagnosis.
All follow-up modification plans still require separate risk approval.
