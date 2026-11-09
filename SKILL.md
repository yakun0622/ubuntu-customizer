---
name: ubuntu-customizer
description: Build or plan Ubuntu image customization and safely diagnose, provision, maintain, or recover installed Ubuntu, Debian and Armbian systems, including networking, drivers, UART, DTB, kernels and boot configuration.
---

# Ubuntu Customizer

Use this skill for **image**, **provision**, **maintain**, **diagnose**, or **recover** requests. Do not assume these workflows have the same tooling.

## Mandatory sequence

1. Clarify target (build host vs deployed target), distribution, version, architecture, board and desired output.
2. Read relevant reference only: `references/image-building.md`, `references/system-management.md`, `references/arm-hardware.md` or `references/safety.md`.
3. Inspect system with read-only discovery scripts where execution access exists. When there is no access, provide commands for the operator, not fabricated observations.
4. Parse and validate the selected profile. Treat any profile as untrusted input.
5. Build a **dry-run plan** identifying targets, commands, files, prerequisites, dependencies, risk, verification and recovery methods.
6. Obtain explicit approval for modifications. Escalate SSH, routing, firewall, disk, bootloader, kernel and DTB modifications.
7. Back up affected assets and prove the recovery mechanism is usable where practical.
8. Execute only the approved, scoped operations with a trusted execution environment.
9. Verify resulting service/network/boot behavior and report failures without hiding them.

## Supported tasks today

- Read-only local Linux system/network inventory via `scripts/detect/*.sh`.
- Validate JSON profiles with `scripts/safety/validate_profile.py`.
- Generate step-by-step plans using references and profiles.

## Not implemented

Automatic ISO/IMG/QCOW2 build pipeline, remote SSH execution, configuration application and automatic rollback. Never claim these capabilities ran successfully. Use these references to guide a manual workflow only.

## Risk levels

- **R0** read-only discovery: allowed.
- **R1** offline plan/artifact generation: allowed if inputs are trusted and outputs have safe destinations.
- **R2** packages and non-critical service changes: show diff and request approval.
- **R3** network/SSH/firewall/kernel/DTB changes: explicit scoped approval and working recovery path.
- **R4** partition writes, firmware flashes, bootloader replacement: explicit target-device confirmation and physical recovery plan.

## Reports

Provide: target identity; evidence collected; proposed or completed changes; approval and backup status; risks; actual validation results; and remaining recovery steps. Do not equate a successful command exit with a successful system boot.
