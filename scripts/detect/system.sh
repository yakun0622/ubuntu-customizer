#!/usr/bin/env bash
# Read-only Linux inventory. Does not require root.
set -u
section() { printf '\n=== %s ===\n' "$1"; }
run() { if command -v "$1" >/dev/null 2>&1; then "$@" 2>&1 || true; else printf 'unavailable: %s\n' "$1"; fi; }
section "OS"
if [[ -r /etc/os-release ]]; then cat /etc/os-release; fi
section "Kernel and architecture"
run uname -a
section "CPU"
run uname -m
section "Boot arguments"
if [[ -r /proc/cmdline ]]; then cat /proc/cmdline; fi
section "Device tree model"
for f in /proc/device-tree/model /sys/firmware/devicetree/base/model; do
  if [[ -r "$f" ]]; then tr '\0' '\n' < "$f"; break; fi
done
section "Root filesystem"
run findmnt -no SOURCE,FSTYPE,TARGET /
section "Block devices"
run lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
section "Memory"
run free -h
section "Failed services"
if command -v systemctl >/dev/null 2>&1; then run systemctl --failed --no-pager; fi
