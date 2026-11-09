# ubuntu-customizer

AI Agent Skill for Ubuntu image customization and safe maintenance of installed Ubuntu, Debian and Armbian systems.

## Current status: v0.2 (read-only foundation)

Implemented:

- Read-only Linux system and network detection
- JSON profile validation
- Local profile-to-host drift plan for packages, hostname, timezone
- Read-only SSH inventory through an existing OpenSSH host alias
- Local backups of explicitly named regular files, with SHA-256 manifest
- Unit tests for profile validation and planning\n- Interactive device discovery over SSH / ADB / TTL / local with a local evidence manifest

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
