# Device Discovery Workflow

## Intent

Inventory a target **before** designing firmware, driver, device tree, network or image modifications. The workflow is evidence-first: select a transport, establish access, probe known read-only resources, save source evidence, then analyze gaps and decide next collection steps.

## Current scope

The Agent is the user entrypoint; commands below are internal helper examples.
Dossiers, comparisons, capability-gated collection, software graphs, the device
catalog and offline HTML viewer are implemented. Python tests passed on
macOS; real Linux/ARM/ADB/TTL collection remains unverified. See the
[capability matrix and validation record](roadmap.md).

## Wizard

```bash
./.venv/bin/python -B scripts/workflow/collect.py
```

Explicit transport selection with a final interactive collection confirmation:

```bash
./.venv/bin/python -B scripts/workflow/collect.py --transport ssh --target ubuntu-server --output ./outputs/ubuntu-server-20261109-01
./.venv/bin/python -B scripts/workflow/collect.py --transport adb --target SERIAL123 --output ./outputs/android-20261109-01
./.venv/bin/python -B scripts/workflow/collect.py --transport ttl --target /dev/cu.usbserial-110 --baud 115200 --duration 20 --output ./outputs/board-serial-01
```

These `collect.py` examples are the **legacy passive collector**. Target for SSH is a configured OpenSSH Host alias with a previously trusted host key. ADB requires a device serial from `adb devices`. Legacy TTL requires optional `pyserial` and only receives data. For **Agent-controlled interactive TTL**, use the persistent picocom adapter instead; see [device sessions](device-session.md). Opening a serial port may change handshake lines, so verify adapter wiring before running.

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
outputs/<session>/
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

Collected files can contain MAC addresses, IPs, hostnames, board identifiers
or kernel configuration. They are kept locally and never uploaded automatically. Default evidence
folders such as `outputs/`, `devices/`, `captures/` and `sessions/` are ignored by Git.
New runtime artifacts belong under `outputs/`; the CLI default is now
`outputs/device-session-*`. Root-level `device-session-*` and
`<label>-YYYYMMDD-HHMMSS` rules protect legacy captures without moving them.
Other custom names are not automatically ignored. Use validated `outputs/`
paths and check `git check-ignore` before staging; ignore rules do not untrack
files already committed. Review/redact
before publishing. No kernel debugfs mounting, privilege escalation, file writes
on target, firmware flash or remote network change occurs.

## Analysis and remaining work

The helpers below already turn manifest-backed evidence into a normalized
`device.json`, capability inventory and software binding/DT graphs. They do
not generate a verified physical pin map. Selective re-probing and privileged
deep probes with per-command authorization remain future work.


## Structured dossier and session comparison

After successful collection, transform the immutable evidence bundle into a
separate indexed dossier:

```bash
./.venv/bin/python -B scripts/workflow/dossier.py ./outputs/example-device-session-001
# creates ./outputs/example-device-session-001/device.json
```

`device.json` contains the observed OS, kernel, CPU identifiers, RAM,
device-tree model/compatible, interface names, evidence category index, and
collection gaps. It validates all referenced files against manifest SHA-256
digests before parsing. Uncollected or inaccessible properties are marked
`not_collected` / `unknown`, **never** assumed to be absent.

For historical comparison (for example before/after a kernel upgrade):

```bash
./.venv/bin/python -B scripts/workflow/compare.py \
  ./outputs/example-device-session-001/device.json \
  ./outputs/example-device-session-002/device.json \
  --output ./outputs/example-device-kernel-diff.json
```

The diff contains field-level identity changes plus changed evidence hashes.
Dynamic network counters or device listings may change normally; the diff
does not claim that every evidence change represents a hardware change.
These analysis commands never connect to the target or modify it.

### Remaining limitations

- GPIO pinmux / IRQ / PHY bindings are presently indexed as **raw evidence**,
  not a verified SoC register or PCB physical pin map.
- Linux device/driver binding graphs and experimental DT/runtime links are
  implemented below. Binding-specific dependency decoding, selective re-probing,
  archive redaction and cross-transport merging remain future work.
- These tools do not implement system mutation, flash, remote reboot or
  automatic rollback.

## Device-to-driver topology (read-only)

New discovery sessions collect limited sysfs binding evidence from network, serial,
GPIO, platform, I2C, SPI and MDIO devices. Generate the conservative topology:

```bash
./.venv/bin/python -B scripts/workflow/collect.py
./.venv/bin/python -B scripts/workflow/dossier.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/topology.py ./outputs/example-device-session-001
```

The new `topology.json` stores device and driver nodes, observed `bound_to`
edges, source evidence path/line, and unavailable or unbound observations.
Its meaning is **Linux driver bindings only**, not verified physical PCB pinout,
PHY signaling, electrical voltages, or full SoC pinmux relationships. Existing
sessions without new probes produce explicit `not_collected` gaps.
See [ARM hardware diagnosis](arm-hardware.md) for physical-evidence limits.

## Device-tree and runtime graph (experimental)

For **new** Linux/Armbian sessions with `dtc` installed on the target,
the collector captures a decompiled DTS alongside driver bindings and
platform-device `of_node` paths. All probes remain read-only.

```bash
./.venv/bin/python -B scripts/workflow/collect.py
./.venv/bin/python -B scripts/workflow/device_tree.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/topology.py ./outputs/example-device-session-001
./.venv/bin/python -B scripts/workflow/link_graph.py ./outputs/example-device-session-001
```

Outputs:

- `device-tree.json`: DTS node hierarchy, selected properties, and supported phandle references.
- `topology.json`: observed Linux sysfs device ↔ driver bindings.
- `linked-hardware.json`: combined graph, including observed `of_node` links between platform devices and DTS nodes.

Every input is verified against the session manifest SHA-256. Missing or truncated DTS data yields explicit gaps. Numeric phandle references are marked **candidates**, not confirmed specifier decoding; pinctrl/clock/reset cell counts require binding-specific analysis. Only software relationships derived from hash-verified evidence are represented: physical header pins, PCB routes, electrical levels and functional hardware behavior remain unverified.

The parser supports common `dtc` output syntax; it is not a replacement for libfdt/dtc and does not interpret overlays or vendor-specific properties fully.

## Hardware-agnostic capability negotiation

Never assume an attached device is an ARM board or that a Device Tree exists.
Base the next probe stage on prior evidence and recorded permission or tool
errors. From an existing session:

```bash
./.venv/bin/python -B scripts/workflow/capabilities.py ./outputs/example-device-session-001
```

`capabilities.json` records status for system identity, CPU/memory, storage,
network, kernel driver bindings, peripheral buses, DT, GPIO/pinctrl and boot
artifacts. `unknown` means not successfully observed, not absent. A generic
adapter must not select a board-specific pin map solely from a compatible
string; physical pinout requires independent board documentation.

Optional board or vendor plugins can be proposed later but must never be
loaded automatically without positive identity evidence and user choice.

## Adaptive staged discovery

The Agent prefers `scripts/workflow/adaptive.py` for device-agnostic collection.
Its collection stages and the subsequent Agent-invoked analysis are:

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
privileged commands. Legacy TTL mode performs only passive capture. New **approved interactive
TTL mode** invokes picocom through `device_session.py`, verifies a Linux/Android
shell prompt, and runs fixed read-only probes over that one session.
U-Boot, login and unknown prompts remain blocked from automatic commands.

```bash
./.venv/bin/python -B scripts/workflow/adaptive.py
./.venv/bin/python -B scripts/workflow/adaptive.py --transport ssh --target my-linux-host --output ./outputs/session-A --yes
./.venv/bin/python -B -m unittest discover -s tests -v
```

The new adaptive workflow does not yet support session resumption or automatic
retries; checkpointing preserves evidence to analyze failures, not a claim of
resumable execution. Per-module privilege approval and additional probe
adapters are future work.

## Device catalog and interactive manager

The optional `scripts/workflow/manage.py` helper maintains a local device
catalog. It records a stable user-defined device ID and a connection
transport/target, then stores each collection session separately. It never
embeds passwords in its catalog.

```bash
# Interactive menu
./.venv/bin/python -B scripts/workflow/manage.py

# Enumerate candidate configured SSH Host aliases, authorized ADB devices,
# local serial-port names, and the local target
./.venv/bin/python -B scripts/workflow/manage.py discover

# Register a target without contacting it
./.venv/bin/python -B scripts/workflow/manage.py add lab-server --transport ssh --target server-alias

# View catalog; collect using the existing staged read-only engine
./.venv/bin/python -B scripts/workflow/manage.py list
./.venv/bin/python -B scripts/workflow/manage.py collect lab-server --modules hardware,drivers,network

# Inspect stored sessions and category summaries
./.venv/bin/python -B scripts/workflow/manage.py sessions lab-server
./.venv/bin/python -B scripts/workflow/manage.py inspect lab-server SESSION_ID
```

The catalog defaults to `./outputs/device-manager/registry.json` and
captures are under `./outputs/device-manager/devices/<id>/sessions/<session>/`.
Directories and the catalog are created with restrictive permissions.
`--data-dir` selects a different *private* directory.

Connection discovery enumerates candidates; SSH aliases are read from explicit
`Host` entries in the primary SSH config (without expanding `Include` or
wildcards). ADB uses `adb devices` and may start the local ADB server. Serial
discovery lists device names but does not open serial ports. It does not
establish connectivity or authenticate to discovered candidates.

The `collect` command asks for confirmation unless given `--yes`;
`--yes` authorizes only fixed read-only evidence probes. TTL uses passive
RX capture, without transmitting serial bytes, though opening adapters may
affect control signals. Raw files may contain identifiers and must not be
automatically published.

The manager provides terminal interaction; the optional offline HTML explorer
and localhost status observer are implemented viewers. Browser device control,
automatic grouping by authenticated hardware identity, resumable collection
and verified physical pin maps are not implemented.

## Hardware explorer and task selection (feature preview)

The terminal manager now supports **Explore**. It reads the selected
session's SHA-256 verified evidence to assemble a software hardware graph,
browse node relationships and prepare an **execution-disabled** plan.

```bash
# Interactive: choose 7. Explore from device manager
./.venv/bin/python -B scripts/workflow/manage.py

# List nodes from a saved session
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID

# Inspect a specific node and its relationships
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID --node 'device:platform:example-controller'

# Generate a diagnosis plan scoped to a verified node (no target actions)
./.venv/bin/python -B scripts/workflow/manage.py explore lab-server SESSION_ID \
  --task diagnose --node 'device:platform:example-controller' \
  --goal 'Investigate why the controller is not responding'

# Run standalone wizard on a session directory
./.venv/bin/python -B scripts/workflow/explore.py ./outputs/device-manager/devices/lab-server/sessions/SESSION_ID

# Generate a safe JSON plan file without overwriting existing plans
./.venv/bin/python -B scripts/workflow/explore.py SESSION_DIRECTORY --mode plan \
  --task maintain --output ./outputs/my-plan.json
```

Supported plan kinds: `diagnose`, `maintain`, `image`. A plan references
observed nodes, software relationships and collection gaps, but **does not
execute commands**, modify configurations, build an image or authorize
flashing. Maintenance execution remains unsupported. Explorer `image` plans
do not invoke the separate [VM image pipeline](image-building.md). Evidence
gaps and incomplete sessions must be resolved before relying on the resulting analysis.

This is currently a text-oriented node list, not a graphical/interactive
node-edge canvas. Board-specific physical pinout and electrical behavior
remain outside the scope of software evidence alone.

## Offline graphical hardware explorer (feature preview)

An interactive **local HTML file** can be exported from a verified evidence
session. No HTTP service, external libraries, CDN or device connection is
required to browse it.

```bash
# From the registered device manager (command 8 in the interactive menu)
./.venv/bin/python -B scripts/workflow/manage.py browse lab-server SESSION_ID

# Custom destination (must not exist; never overwrites)
./.venv/bin/python -B scripts/workflow/manage.py browse lab-server SESSION_ID --output ./outputs/lab-hardware.html

# Directly from an existing collection session
./.venv/bin/python -B scripts/workflow/export_html.py SESSION_DIRECTORY --output ./outputs/hardware.html
```

Open the resulting HTML file locally in a browser. The left panel supports
search and type filtering (device / driver / device-tree node); the right
panel displays node attributes, related nodes, evidence source and collection
gaps. Clicking a relationship jumps to that node.

Security and scope:

- It validates the session's evidence SHA-256 hashes before rendering.
- Data is embedded as escaped JSON and written with private file permissions.
- The page has a restrictive Content Security Policy and no network access.
- Collected source material may include private device identifiers; do **not**
  upload the HTML without reviewing/redacting its content.
- This is a browser-based **offline viewer**, not a server application or
  interactive device controller. Node properties are software evidence, not
  verified physical header pinout or electrically measured conditions.
- Task execution remains disabled; diagnose / maintain / image still create
  plans only.
