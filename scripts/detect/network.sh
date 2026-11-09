#!/usr/bin/env bash
# Read-only network inventory. No interface or route modifications.
set -u
section() { printf '\n=== %s ===\n' "$1"; }
run() { if command -v "$1" >/dev/null 2>&1; then "$@" 2>&1 || true; else printf 'unavailable: %s\n' "$1"; fi; }
section "Interfaces and counters"
run ip -s link show
section "IP addresses"
run ip address show
section "Routes"
run ip route show table all
section "Rules"
run ip rule show
section "DNS"
if [[ -r /etc/resolv.conf ]]; then cat /etc/resolv.conf; fi
section "Network managers"
if command -v systemctl >/dev/null 2>&1; then
  run systemctl is-active NetworkManager
  run systemctl is-active systemd-networkd
fi
section "SSH session indicator (redact before sharing)"
printf 'SSH_CONNECTION is %s\n' "${SSH_CONNECTION:+set}"
