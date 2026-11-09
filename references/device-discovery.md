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
python3 scripts/workflow/dossier.py ./devices/example-device/session-001
# creates ./devices/example-device/session-001/device.json
```

`device.json` contains the observed OS, kernel, CPU identifiers, RAM,
device-tree model/compatible, interface names, evidence category index, and
collection gaps. It validates all referenced files against manifest SHA-256
digests before parsing. Uncollected or inaccessible properties are marked
`not_collected` / `unknown`, **never** assumed to be absent.

For historical comparison (for example before/after a kernel upgrade):

```bash
python3 scripts/workflow/compare.py \
  ./devices/example-device/session-001/device.json \
  ./devices/example-device/session-002/device.json \
  --output ./devices/example-device/kernel-diff.json
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
python3 scripts/workflow/dossier.py ./devices/example-device/session-001
python3 scripts/workflow/topology.py ./devices/example-device/session-001
```

The new `topology.json` stores device and driver nodes, observed `bound_to`
edges, source evidence path/line, and unavailable or unbound observations.
Its meaning is **Linux driver bindings only**, not verified physical PCB pinout,
PHY signaling, electrical voltages, or full SoC pinmux relationships. Existing
sessions without new probes produce explicit `not_collected` gaps.
Use [device discovery](references/device-discovery.md) for further context.

## Device-tree and runtime graph (experimental)

For **new** Linux/Armbian sessions with `dtc` installed on the target,
the collector captures a decompiled DTS alongside driver bindings and
platform-device `of_node` paths. All probes remain read-only.

```bash
python3 scripts/workflow/collect.py
python3 scripts/workflow/device_tree.py ./devices/example-device/session-001
python3 scripts/workflow/topology.py ./devices/example-device/session-001
python3 scripts/workflow/link_graph.py ./devices/example-device/session-001
```

Outputs:
- `device-tree.json`: DTS node hierarchy, selected properties, and supported phandle references.
- `topology.json`: observed Linux sysfs device ↔ driver bindings.
- `linked-hardware.json`: combined graph, including observed `of_node` links between platform devices and DTS nodes.

Every input is verified against the session manifest SHA-256. Missing or truncated DTS data yields explicit gaps. Numeric phandle references are marked **candidates**, not confirmed specifier decoding; pinctrl/clock/reset cell counts require binding-specific analysis. Only trusted software topology is represented: physical header pins, PCB routes, electrical levels and functional hardware behavior remain unverified.

The parser supports common `dtc` output syntax; it is not a replacement for libfdt/dtc and does not interpret overlays or vendor-specific properties fully.

## Hardware-agnostic capability negotiation

Never assume an attached device is an ARM board or that a Device Tree exists.
Base the next probe stage on prior evidence and recorded permission or tool
errors. From an existing session:

```bash
python3 scripts/workflow/capabilities.py ./devices/example-device/session-001
```

`capabilities.json` records status for system identity, CPU/memory, storage,
network, kernel driver bindings, peripheral buses, DT, GPIO/pinctrl and boot
artifacts. `unknown` means not successfully observed, not absent. A generic
adapter must not select a board-specific pin map solely from a compatible
string; physical pinout requires independent board documentation.

Optional board or vendor plugins can be proposed later but must never be
loaded automatically without positive identity evidence and user choice.

## Adaptive staged discovery

The new `scripts/workflow/adaptive.py` is the preferred device-agnostic entry
point. Its deterministic stages are:

1. **Bootstrap:** OS, kernel, CPU and RAM evidence
2. **Capability checks:** read-only filesystem/tool availability probes
3. **Selection:** choose applicable probes for hardware, drivers, buses, pins,
   network, storage and boot; unavailable prerequisites are *skipped with reasons*
4. **Checkpoint:** persist every probe's stdout, status, hash, and error into
   an updated `manifest.json` plus its evidence file
5. **Analysis:** run `dossier.py`, `capabilities.py`, `topology.py`,
   `device_tree.py` and `link_graph.py` as applicable

Unobserved prerequisites are never interpreted as hardware absence. Partial
outputs and unsupported tools remain visible as gaps. The initial capability
checks assess **access**, not actual electrical functionality. The collector
uses fixed read-only shell commands, existing SSH known-host trust, and no
privileged commands. TTL performs only passive capture; it cannot discover
Linux capabilities until an authorized shell transport is selected.

```bash
python3 scripts/workflow/adaptive.py
python3 scripts/workflow/adaptive.py --transport ssh --target my-linux-host --output ./session-A --yes
python3 -m unittest discover -s tests -v
```

The new adaptive workflow does not yet support session resumption or automatic
retries; checkpointing preserves evidence to analyze failures, not a claim of
resumable execution. Per-module privilege approval and additional probe
adapters are future work.
