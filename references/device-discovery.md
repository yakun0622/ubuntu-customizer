# Device Discovery Workflow

## Intent

Inventory a target **before** designing firmware, driver, device tree, network or image modifications. The workflow is evidence-first: select a transport, establish access, probe known read-only resources, save source evidence, then analyze gaps and decide next collection steps.

## Wizard

```bash
python3 scripts/workflow/collect.py
```

Noninteractive selection with a final explicit local collection confirmation:

```bash
python3 scripts/workflow/collect.py --transport ssh --target ubuntu-server --output ./devices/ubuntu-server/2026-11-09-01
python3 scripts/workflow/collect.py --transport adb --target SERIAL123 --output ./devices/android/2026-11-09-01
python3 scripts/workflow/collect.py --transport ttl --target /dev/cu.usbserial-110 --baud 115200 --duration 20 --output ./devices/board/serial-01
```

Target for SSH is a configured OpenSSH Host alias with a previously trusted host key. ADB requires a device serial from `adb devices`. TTL requires optional `pyserial`. Serial access is passive receive only; opening a serial port may change handshake lines, so verify adapter wiring before running.

## Collection layers

1. Device identity: `/etc/os-release`, kernel, CPU, memory
2. Hardware enumeration: model/compatible DT properties, PCI and USB
3. Drivers: loaded modules, TTY, network and GPIO class devices
4. Pinctrl and DT: debugfs pinctrl discovery, `gpioinfo` if installed, `dtc -I fs` if installed
5. Network: links, routes, driver tools
6. Storage/boot: block device and boot directory listing
7. TTL: serial receive log only; subsequent shell interaction requires a separately scoped, reviewed command workflow

The collector writes under a **new**, user-selected session directory:

```text
devices/<device>/<session>/
  manifest.json
  identity/
  hardware/
  drivers/
  pins/
  network/
  storage/
  boot/
  serial/                  # TTL-only
```

Each manifest entry has a relative file path, SHA-256 digest, byte count and probe status. Some categories may be absent depending on transport. A nonzero remote command may produce partial evidence, never silently described as complete.

## Interpreting pinouts

- Device-tree pinctrl nodes can identify mux functions and candidate pin banks.
- GPIO numbering can be relative to a controller and may differ from silkscreen numbers.
- Physical PCB pads/header numbering, voltage, pull-ups and trace routing are **not reliably inferable** from DTS alone. Add schematic, SoC pin datasheet, PCB photos and multimeter measurements as explicitly labeled evidence.
- Maintain `observed`, `inferred` and `unverified` distinctions in subsequent analysis. Do not guess electrical voltage or attach a 5V UART to a 3.3V TTL device.

## Privacy and safety

Collected files can contain MAC addresses, IPs, hostnames, board identifiers or kernel configuration. They are kept locally, ignored by git and never uploaded automatically. Review/redact before publishing. No kernel debugfs mounting, privilege escalation, file writes on target, firmware flash or remote network change occurs.

## Next phase

Analyze manifest and raw evidence into a normalized device dossier (`device.json`, pin map, buses, bindings, confidence/source provenance) and support selective deep probes with a per-command authorization gate.


## Structured dossier and session comparison

After successful collection, transform the immutable evidence bundle into a
separate indexed dossier:

```bash
python3 scripts/workflow/dossier.py ./devices/w152d/session-001
# creates ./devices/w152d/session-001/device.json
```

`device.json` contains the observed OS, kernel, CPU identifiers, RAM,
device-tree model/compatible, interface names, evidence category index, and
collection gaps. It validates all referenced files against manifest SHA-256
digests before parsing. Uncollected or inaccessible properties are marked
`not_collected` / `unknown`, **never** assumed to be absent.

For historical comparison (for example before/after a kernel upgrade):

```bash
python3 scripts/workflow/compare.py \
  ./devices/w152d/session-001/device.json \
  ./devices/w152d/session-002/device.json \
  --output ./devices/w152d/kernel-diff.json
```

The diff contains field-level identity changes plus changed evidence hashes.
Dynamic network counters or device listings may change normally; the diff
does not claim that every evidence change represents a hardware change.
These analysis commands never connect to the target or modify it.

### Remaining limitations

- GPIO pinmux / IRQ / PHY bindings are presently indexed as **raw evidence**,
  not a verified SoC register or PCB physical pin map.
- Structured driver-to-device dependency graph, selective re-probing,
  redaction and cross-transport session merging are still planned.
- These tools do not implement system mutation, flash, remote reboot or
  automatic rollback.

## Device-to-driver topology (read-only)

New discovery sessions collect limited sysfs binding evidence from network, serial,
GPIO, platform, I2C, SPI and MDIO devices. Generate the conservative topology:

```bash
python3 scripts/workflow/collect.py
python3 scripts/workflow/dossier.py ./devices/w152d/session-001
python3 scripts/workflow/topology.py ./devices/w152d/session-001
```

The new `topology.json` stores device and driver nodes, observed `bound_to`
edges, source evidence path/line, and unavailable or unbound observations.
Its meaning is **Linux driver bindings only**, not verified physical PCB pinout,
PHY signaling, electrical voltages, or full SoC pinmux relationships. Existing
sessions without new probes produce explicit `not_collected` gaps.
Use [device discovery](references/device-discovery.md) for further context.
