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

## Read-only topology milestone

- Added sysfs binding inventory probes for network/serial/GPIO, platform, I2C, SPI and MDIO
- Added SHA-256 validated topology parser with provenance per binding edge and missing-evidence gaps
- Added unit tests for bound/unbound/malformed/tampered evidence
- Pending: actual integration test on Linux and ARM devices, DT phandle graph, SoC pinctrl mapping, privileged debugfs workflow and structured hardware troubleshooting decisions

## Device-tree deep discovery (experimental)

- Added DTS hierarchy and phandle graph parser from verified collection evidence
- Added read-only platform `of_node` capture and runtime-to-DTS correlation
- Added unit test fixtures for DTS labels, pinctrl candidates, integrity and device linkage
- Pending: executing tests in CI/local Linux; real ARM board validation; robust libfdt-compatible parser; binding-specific clock/reset/IRQ cells; pinctrl groups and SoC pin bank mapping; authorized optional debugfs evidence

## Generic device policy (current)

- Removed the named-board diagnostics profile from the core repository.
- Added an illustrative generic ARM64 discovery profile.
- Added evidence-driven capability inventory (`capabilities.json`) with
  available/partial/unknown states and tests.
- Next: capability-aware probe selection, extensible transport and hardware
  adapters, structured registry of sessions per device with stable identifiers,
  and optional vendor plugins separated from the core.
- No platform-specific flashing or physical pinout assumptions are permitted
  in the generic workflow.

## Adaptive discovery preview

- Added staged read-only bootstrap, capability checks, module selection, and
  per-probe manifest checkpoints with skipped-reason recording.
- Added CLI module selection for SSH/ADB/local, passive TTL remains separate.
- Added tests for prerequisite gating, skip semantics and checkpoint outputs.
- Still required: actual runtime test execution, resumable collection, secure
  privileged probe authorization, progress UI, cross-platform probe adapters,
  stable device identity and plugin extension registry.

## Device management milestone (terminal UI)

- Added local device registry with validated IDs and private on-disk metadata.
- Added candidate discovery for explicit SSH Host aliases, ADB online serials, and local serial port names.
- Added interactive command menu, per-device collection sessions and inspection of prior sessions.
- Reused the existing capability-aware read-only collection engine, without adding write-capable remote execution.
- Pending: runtime tests on supported host platforms; secure device identity verification; resumable capture; graphical device tree browser; plugin transports; optional archive redaction.
