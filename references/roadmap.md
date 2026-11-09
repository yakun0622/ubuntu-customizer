## Product boundary: Skill-first design

The deliverable is the Agent Skill (`SKILL.md` + focused references).
`scripts/` only contains invoked helpers, not a separate application or
required UI. Prioritize Agent decision logic, evidence-to-target compatibility
contracts, backend selection, build gates and verification instructions.
Standalone device-manager and offline HTML viewer are optional utilities;
no new feature should require them.

The next development goal is to make the Skill guide a complete
discovery-to-image conversation without claiming unimplemented rootfs/BSP
builders, followed by test validation of helper scripts.

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

## Device explorer and task workflow (preview)

- Added SHA-256 evidence-backed terminal node browser and relationship lookup.
- Added choose-task wizard for diagnose / installed-system maintain / image-build planning.
- Added non-executable JSON task plans including evidence links, missing observations, risks, and approval blockers.
- Integrated device ID + historical session selection with the device manager.
- Added synthetic-data tests for graph browsing, evidence tampering, path validation and plan gating.
- Pending: execute full test suite on supported platforms, interactive graphical graph view, resumable/target-specific deep probes, robust state machine and a separately reviewed safe mutation engine.

## Offline graphical browser milestone

- Added standalone offline HTML hardware explorer generated from SHA-256 verified session data.
- Added search, type filtering, node details, relation navigation, evidence reference and gap summaries.
- Added browser export to multi-device terminal manager and new browser-escaping tests.
- Pending: actual local and real-device tests, richer hierarchical tree and scalable rendering, approved diagnostic drilldowns, export redaction and signed portable evidence packages.

## Image portability assessment and offline VM converter (initial)

- Added SHA-256 verified discovery-to-image plan for a local base image,
  explicit source architecture and target type/format.
- Added physical device blockers: boot chain, partitioning, kernel/DTB
  compatibility, firmware and restore procedure.
- Added guarded `qemu-img` RAW/QCOW2 offline conversion for VM targets,
  output checksum/build metadata, no direct block device writes.
- Added source mismatch, architecture, backing chain and output-path tests.
- Pending: confirmed test execution, upstream signature verification, guest
  OS/architecture inspection, package/rootfs personalization, first-boot
  identity reset, cloud-init seed generation, QEMU boot smoke tests and
  backend plugins for verified physical boot targets.

## Optional Skill live status preview

- Added an opt-in, loopback-only HTTP viewer that polls sanitized
  probe progress from the existing checkpoint manifest.
- Added a minimal Agent-owned status helper for analyze/image-plan/
  image-build/verification stage updates (allowlisted fields only).
- Added focused tests covering summary redaction, status validation,
  HTTP read-only routes and output privacy.
- Next: run tests with real local browsers and Unix/macOS hosts, improve
  lifecycle automation after explicit consent, and measure progress
  completeness across multistage workflows.
- The Skill, not the viewer, remains the authoritative orchestration layer.

## Preview lifecycle — current milestone

- Added an Agent-callable helper to start, check, stop or clear a stale
  local preview instance; no HTTP write/control endpoint is introduced.
- Collection starts the preview at session creation **only when**
  `--preview-approved` was provided following user opt-in.
- Preview startup failures are nonfatal for core collection.
- Added tests for approval gating, identity verification, stale runtime
  handling, and the localhost start/status/stop integration path.
- Added completion-response contract: one precise next task plus an
  interactive follow-up action when the host chat UI supports it.
- Remaining: run the new suite on Linux/macOS, lifecycle smoke tests in
  a real Agent runtime, consent UX validation, and cleanup policies for
  canceled sessions.
