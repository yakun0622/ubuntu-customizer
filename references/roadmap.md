# Roadmap and acceptance

## v0.1 completed: repository foundation

- Agent SKILL.md and reference runbooks
- JSON safe-subset profile validator
- Read-only Linux inventory
- Validation smoke tests

## v0.2 in progress: safe installed-system workflow

Implemented in source:
- Read-only local profile drift plan
- Remote read-only inventory with OpenSSH
- Local explicit-file snapshots and SHA-256 manifest
- Unit tests for the plan

Still needed for full v0.2:
- Verified local test execution and automated integration tests
- Structured plan/diff engine beyond packages and hostname/timezone
- Idempotent approved mutation adapters
- Tested per-resource restore and remote network recovery
- Remote compatibility verification, structured SSH error reporting

## v0.3 planned: image pipeline

- Version-pinned Ubuntu Server Autoinstall ISO renderer
- Official cloud image / QCOW2 + cloud-init workflow
- Source signature/hash verification and QEMU smoke tests
- Reproducibility manifest

## v0.4 planned: ARM/Armbian

- Board plugin discovery and BSP metadata
- Device tree read/diff support, UART/PHY diagnostics
- Board-specific image builds and verified external recovery

## Acceptance rule

Source committed is not sufficient evidence that runtime tests passed. Mark features validated only after test logs show successful execution. Never equate markdown instructions with a working build engine.

## Device discovery extension (in progress)

- Existing wizard: SSH / ADB / local read-only collection and TTL passive capture
- Added: SHA-256 verified `device.json` dossier derived from evidence session
- Added: comparison of two dossiers with field-level identity changes and evidence digest differences
- Pending: structured driver bindings, validated pinmux topology, historical device registry, selective deep probes with per-command approval, sensitive-data redaction and runtime integration testing
