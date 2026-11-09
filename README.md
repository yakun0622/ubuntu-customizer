# ubuntu-customizer

An AI Agent skill for Ubuntu image customization and safe maintenance of installed Ubuntu, Debian and Armbian systems.

## Scope

- **image**: design, customize and validate Ubuntu Server autoinstall ISO, cloud images and board-specific ARM images.
- **provision**: compare desired configuration against an installed system.
- **maintain**: inspect packages, services, SSH, networking and security.
- **diagnose**: collect evidence for networking, kernel, DTB, UART, PHY and boot failures.
- **recover**: plan verified backups and reversible changes.

> **Status: v0.1 foundation.** Only read-only discovery and plan validation are implemented as executable commands. Image builds and remote writes are deliberately not implemented yet. No commands here flash devices or modify a remote host.

## Layout

- [SKILL.md](SKILL.md): skill entry point and mandatory workflow
- [references/](references/): image, system and hardware operating procedures
- [profiles/](profiles/): illustrative declarative YAML profiles
- [scripts/detect/](scripts/detect/): safe, read-only discovery
- [scripts/safety/](scripts/safety/): local plan validation
- [schemas/](schemas/): JSON Schema for profiles
- [tests/](tests/): self-contained smoke tests

## Quick start

```bash
bash scripts/detect/system.sh
bash scripts/detect/network.sh
python3 scripts/safety/validate_profile.py profiles/base/ubuntu-server.json
python3 -m unittest discover -s tests -v
```

Discovery scripts run on the **target Linux machine**, not on your macOS controller. They do not require root; privileged output may be incomplete.

## Profiles

The authoritative machine-readable example uses JSON to avoid requiring a third-party YAML parser. YAML profiles are examples for the future renderer; no script presently consumes them. Never pass profile strings to a shell via eval.

## Design principles

1. Detect before planning and plan before changes.
2. Distinguish build host, target system and target architecture.
3. Resolve backend compatibility before attempting image creation.
4. Protect remote SSH access and prefer out-of-band recovery.
5. Preview exact changes; require approval for sensitive actions.
6. Validate output and report what was *actually* verified.
7. Never promise automatic recovery for firmware, partitions or package upgrades.

See [references/roadmap.md](references/roadmap.md) for implementation phases.
