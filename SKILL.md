---
name: ubuntu-customizer
description: Build or plan Ubuntu image customization and safely diagnose, provision, maintain, or recover installed Ubuntu, Debian and Armbian systems, including networking, drivers, UART, DTB, kernels and boot configuration.
---

# Ubuntu Customizer

Choose one workflow: **image**, **provision**, **maintain**, **diagnose**, **recover**.

## Device discovery first

When the user asks to work with a physical target or unknown Ubuntu/Armbian device, prefer `references/device-discovery.md`. Offer transport choices (SSH, ADB, TTL serial, local), then run `python3 scripts/workflow/collect.py` when the execution environment has access. Use the resulting `manifest.json` and category evidence before suggesting driver, DTB or kernel fixes. Distinguish pinmux evidence from verified physical PCB pinout. TTL access in this version is **passive log capture only**.

## Mandatory flow

1. Distinguish controlling/build host from the target; identify OS, architecture, exact board and expected output.
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
python3 scripts/workflow/collect.py\nbash scripts/detect/system.sh
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
