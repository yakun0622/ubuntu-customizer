# Implementation roadmap

## v0.1 Foundation (this repository baseline)

- Skill entry point and reference runbooks
- JSON profile schema and validated example
- Read-only Linux system and network discovery
- Smoke tests and explicit safety boundary

## v0.2 Installed systems

- Structured plan/diff engine and idempotent apply interface
- SSH execution adapter with host identity and access protection
- Transactional backup and per-resource restore tests
- Package and systemd adapters

## v0.3 Image pipeline

- Version-pinned Ubuntu Server Autoinstall ISO renderer
- QCOW2/cloud-init renderer
- Source signature/hash verification and QEMU automated smoke tests
- Reproducible manifest

## v0.4 ARM/Armbian

- Board plugin discovery and BSP metadata
- Device tree read/diff support and UART/PHY diagnostics
- Board-specific image builds and external recovery checks

## Acceptance rule

No component is marked implemented until integration tests verify actual behavior. Never treat markdown design notes as a working build or execution engine.
