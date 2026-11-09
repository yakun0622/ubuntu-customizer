# Installed system management

## Inventory first

- OS: `/etc/os-release`, `uname -a`, `dpkg --print-architecture`.
- Boot: `/proc/cmdline`, `/boot`, EFI vs U-Boot.
- Network: `ip -j address`, `ip route`, `ip rule`, active SSH peer, NetworkManager/netplan/systemd-networkd.
- Storage: `lsblk`, `findmnt`, `df -h`.
- Services: `systemctl --failed`, units and logs.
- Hardware: `lspci`, `lsusb`, device tree, modules when available.

Use `scripts/detect/system.sh` and `scripts/detect/network.sh` when applicable. Never infer absence of a device from missing tool output.

## Applying configuration (future execution adapter)

1. Determine current state and exact desired state.
2. Produce file-level diff and ordered operations.
3. Reject schema-invalid, platform-incompatible or secret-bearing profiles.
4. Save checksums, permissions, owners and backups of every modified file.
5. Require authorization and ensure another valid SSH access route before network changes.
6. Apply one reversible step at a time; test after each dependency boundary.
7. Re-run read-only discovery and compare before/after.
8. Report drift and the exact commands needed for rollback.

## Remote network changes

- Identify management interface, gateway, DNS and SSH session path.
- Prefer a rollback timer/transaction when supported, and verify its behavior before applying.
- Confirm a **new** SSH connection over the intended route before finalizing.
- Do not automatically disable SSH/password auth on an unknown remote host.
- Never reboot as an implicit part of a package update.

## Idempotence

A planned operation must include a check of the target state and should skip changes when already satisfied. Avoid shell command interpolation from untrusted profile values.
