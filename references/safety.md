# Safety and execution contracts

The R2–R4 entries below are safety requirements for future adapters, not
implemented mutation capabilities. Current writes are local evidence,
snapshots and separately approved VM artifacts; isolated VM launch requires
its own approval. Physical writes, maintenance application and automatic
rollback are unsupported. See the [capability matrix](roadmap.md).

## Gate each step

| Risk | Examples | Requirement |
| --- | --- | --- |
| R0 | Read-only inspection | Can run when target access is authorized |
| R1 | Offline image construction, isolated VM launch | Safe paths, validated inputs, distinct explicit approval for construction and launch |
| R2 | Packages, ordinary service config | Exact diff and user approval |
| R3 | SSH, route, firewall, kernel, DTB | Explicit scoped approval, backup and proven recovery |
| R4 | Partition writes, U-Boot/firmware flashing | Exact-device confirmation and external rescue plan |

## Before changes

Capture target fingerprint, pre-change file hashes, ownership, permissions, and active network/SSH route. Redact credentials and tokens from logs. Keep backup on separate trusted storage if a change could impact boot or disks.

## During changes

Never use `curl | sh`, `eval`, or unquoted variables sourced from profiles. Do not silently fall back to `sudo` with arbitrary commands. Do not schedule unapproved reboot or shutdown.

## After changes

Verify the specific acceptance criterion, not just exit code. For remote networking, establish a fresh SSH connection. For image builds, verify hashes and perform boot test where feasible. For bootloader writes, require reboot verification under supervision.

## Rollback

Rollback is only available when a **tested reversible** action exists. Package upgrades, on-disk format changes, disk writes and flashes cannot be promised automatic rollback. If verification fails, stop and report evidence and the tested recovery method.

Local profile validation and evidence interpretation are read-only operations.
Snapshot helpers create copies and checksums but do not implement restoration.
Neither a plan, a follow-up button nor preview consent grants device access,
offline construction, isolated boot or higher-risk device-write permission.
