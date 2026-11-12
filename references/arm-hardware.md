# ARM / Armbian hardware diagnosis

## Minimal userspace first, then board adaptation

The physical ARM path selects an official, checksum-pinned minimal ARM64
userspace by default (Ubuntu Base 24.04.5 currently). It never searches a
Mac's disks for an IMG first. `arm_baseline.py` fetches into `outputs`
when explicitly approved. `arm_candidate.py` starts a revisioned local
staging directory and accepts only board components already within the
active project. Research and authorized device extraction should resolve
missing kernel/DTB/bootloader in subsequent revisions. Merely extracting or
staging them does not make a bootable disk. Boot-script/partition assembly,
driver recompilation and physical USB verification still require additional
implementation and per-action safety approvals.

## Current scope

Implemented tools collect fixed read-only evidence, parse software bindings
and experimental DT/runtime links, and analyze existing ARM boot logs or
candidate images through `physical_verify.py`. They do not confirm physical
boot health, generate verified pin maps or implement BSP assembly/flashing.
The steps below are diagnostic guidance, not an automated repair workflow.
Real ARM integration remains unverified; see [current status](roadmap.md).

## Required identity

Collect exact board model and PCB revision, SoC, kernel version, bootloader, DTB compatible strings, root device, power configuration, recovery UART and recovery storage availability.

## Ethernet TX works / RX does not

1. Confirm interface administrative and carrier state with `ip -s link`.
2. Read `ethtool`, `ethtool -S`, PHY address and MDIO evidence.
3. Compare baseline RX/TX counters before and after a controlled ARP/ICMP exchange.
4. Check `dmesg` and journal for MAC, DMA, RX ring, PHY reset and driver failures.
5. Capture packets at both peers (when authorized) to distinguish link, MAC, driver and protocol-stack faults.
6. Inspect device tree for PHY mode, RGMII/RMII delays, clock, pinctrl, interrupts, reset lines and regulator configuration.
7. Propose the **smallest** testable DTB/driver change only after evidence narrows the fault.

The legacy fixed collector does not perform the complete checklist: its ethtool
probe reads the tool version, not PHY registers or full statistics. Packet
capture, traffic generation and additional log/MDIO reads need separately
scoped authorization and appropriate tools; no DTB/driver mutation backend
exists. Never synthesize shell commands from untrusted device evidence.

## UART and DTB

- Read DT node properties and overlays before editing.
- Record original DTB hash and exact boot selection path.
- Use `dtc` only when present; preserve compiled boot image and originals.
- Check pinctrl conflicts, clock gating and login console ownership.
- A compiled DTB alone does **not** establish functional hardware.

## Flashing / boot modifications

All bootloader, kernel, partition and DTB writes are at least R3, potentially R4. Require an independently verified restore method and physical console before actions that could prevent boot. No flashing or boot-modification backend is implemented; authorization alone does not make these operations supported.
