# Roadmap and acceptance

## Product boundary

The deliverable is the Agent Skill (`SKILL.md` and focused references).
The conversational Agent owns decisions, tool invocation and consent;
`scripts/` contains scoped helpers, not a standalone application or a
required UI. The device catalog, offline HTML explorer and localhost
status observer are optional tools.

This document is the maintained capability matrix, validation record and
remaining-work list. [README](../README.md) summarizes it;
[SKILL](../SKILL.md) defines how the Agent uses the supported capabilities.
Earlier milestone entries are preserved in Git history. Their v0.1–v0.4
labels described planning stages, not verified releases or deployment support.

## Portable Mac ARM milestone — 2026-11-12

- `arm_fat32.py` is a pure-Python FAT32/VFAT writer for the USB boot
  partition, including long filenames such as `aml_autoscript` and
  `extlinux.conf`. It has no mkfs.vfat/mtools runtime requirement,
  validates project-only paths, and never touches host block devices.
  The legacy mtools backend remains available when all tools are
  explicitly staged inside this project.
- `arm_preflight.py` is a non-scanning readiness audit. It checks the
  official RootFS SHA-256, versioned board components, and a
  project-local ext4 writer, and reports missing inputs. It never claims
  an OS sandbox was established or that hardware was booted. The Agent
  performs preflight before requesting offline-build consent.
- `tests/test_arm_fat32.py` and `tests/test_arm_preflight.py`
  exercise portable FAT structures, VFAT names, content, unsafe paths
  and evidence validation. `test_arm_image_builder.py` covers the
  single-tool default and legacy backend compatibility.
- An opt-in GitHub-hosted Linux smoke job runs a **real** `mke2fs`,
  `debugfs`, `fsck.fat`, and `mdir` against synthetic test rootfs
  and boot files. These binaries are staged only inside CI's outputs,
  not fetched from a user's Mac. The job runs on main changes and must
  show a passing result before claiming real filesystem-tool validation.
- Mac ARM64 is **not yet fully self-contained**: `mke2fs` still needs a
  trusted project-local binary and OS-enforced process sandbox. This
  commit does not supply or install one. Physical W152D Kernel/DTB
  compatibility and true USB boot are unverified; eMMC flashing remains
  unsupported.

## Physical ARM USB builder milestone — 2026-11-12

New executable components: `arm_image_builder.py` (pinned Ubuntu Base
RootFS extraction, MBR+FAT32+ext4 RAW IMG assembly, board assets, optional
hash-checked modules/firmware overlay, fixed project-local mkfs/mtools tool
invocations, full artifact SHA-256); `arm_dtb_adapter.py` (project-local
DTS to DTB compilation and structural inspection); `arm_boot_diagnose.py`
(candidate-hash-bound serial error diagnosis); and the consent-gated
physical ARM iteration in `agent_journey.py`.

**Validation:** 12 focused new tests passed in an isolated local fixture
with mocked filesystem utilities, no network or target access. GitHub
commit does not represent successful installation or W152D boot.
Real Ubuntu Base extraction, real `mkfs.vfat`/`mke2fs`/`mtools`,
project-only OS sandbox enforcement, real U-Boot load path, Kernel, DTB,
drivers and USB boot all remain unverified. Direct eMMC flashing is
unsupported by design. Existing tests need a fresh complete run on the
user's actual checkout; an old 251-test pass is not proof this revision
passed all regressions. The IMG manifest retains
`usb_boot_confirmed=false` and `deployment_allowed=false`.

## Status terminology

- **Implemented:** a helper or policy exists in source with the stated limits.
- **Tested:** the named checks actually ran in the recorded environment.
  Mocked tools and synthetic fixtures validate logic, not real builds or boots.
- **Unverified:** implementation exists, but the relevant real execution has
  no recorded validation here. Do not infer support from a unit-test pass.
- **Unsupported:** no execution backend exists, or required safety gates keep
  the operation blocked. A plan or approval alone does not implement it.

## Current capability matrix

| Area | Implemented helpers and scope | Remaining boundary |
| --- | --- | --- |
| ARM base-first acquisition (new) | `arm_baseline.py`: pinned Ubuntu Base 24.04.5 ARM64 HTTPS download into `outputs`, SHA-256 integrity verification, non-overwriting manifest | Userspace only; download requires consent; untested against real upstream network; does not contain bootloader, board kernel or DTB |
| ARM candidate revisions (new) | `arm_candidate.py`: verify pinned base, stage project-local kernel/DTB/bootloader/firmware into immutable numbered revision and report missing components | No DTB patch/compiler, ext4 partitioned USB IMG builder, real board boot or flashing; new stages are not bootable images |
| Project-local reads (new) | `project_workspace.checked_input/checked_project_dir` and fail-closed CWD; default host discovery avoids external directory enumeration and implicit Lima probing | Application-level guards only; OS subprocess/stdio/serial operations need OS sandbox for whole-process confinement |
| Guided conversation | `agent_journey.py`: pure next-step/consent policy, workspace bootstrap stage, transport/interface selection, plan confirmation, requirements, halt/retry and optional boot skip | No executor or persistent session store; real Agent tool/permission handoffs unverified; non-image goals finish with evidence analysis |
| Discovery | `collect.py`, `adaptive.py`, `device_session.py`, detect scripts, `ssh_probe.py`: fixed read-only probes, persistent SSH/ADB/picocom sessions, legacy passive TTL RX, OS/prompt guards and manifest checkpoints | Real Linux/ARM/ADB/TTL integration unverified; no resumable collection or privileged deep-probe authorization workflow |
| Evidence and graph analysis | `dossier.py`, `compare.py`, `capabilities.py`, `topology.py`, `device_tree.py`, `link_graph.py`: hash checks, evidence references, Linux bindings, DTS hierarchy, phandle candidates and runtime links | No authenticated hardware identity, physical pinout or electrical verification; DTS parsing is experimental, not libfdt or binding-specific decoding |
| Catalog and exploration | `manage.py`, `explore.py`, `export_html.py`: user-defined device IDs, historical sessions, node relationships, execution-disabled task plans and offline HTML viewer | No automatic identity-based grouping, browser device-control dashboard or task execution; real browser review unverified |
| Installed-system planning | Profile validator, `system/plan.py`, `safety/snapshot.py`: narrow JSON profile subset, local package/hostname/timezone drift plans, explicit-file snapshots and hashes | No profile application, automatic diagnosis, approved maintenance mutation, automatic restore or recovery; YAML examples are illustrative |
| Source inspection and conversion | `image_inspect.py`, `image_plan.py`, `build_image.py`: trusted source SHA-256, guest OS/architecture/kernel/partition/firmware/bootloader checks, reinspection and VM RAW/QCOW2 conversion | Real qemu-img/libguestfs inspection and conversion unverified; format conversion does not establish bootability; physical-device plans stay blocked |
| Limited offline RootFS customization | `rootfs_builder.py`, `nocloud.py`: dry-run, separately approved private clone, hostname/MOTD, narrowly scoped identity cleanup, stale cloud-init cache removal, public-key-only seed, optional seed ISO and hashed bundle | Requires inspected Linux VM image with cloud-init; real build and initialization unverified; no arbitrary package/script customization, complete secret sanitization or from-scratch OS creation |
| Verification adapters | `verify_backend.py`, `physical_verify.py`, `verify_vm.py`: static inspection, passive ARM boot-log evidence and legacy inconclusive QEMU smoke attempt | Static checks, UART text and QEMU exit status never establish a healthy guest or physical-device deployment readiness |
| AMD64 guest-health verification | `verify_first_boot.py`: separately approved QEMU TCG snapshot, restricted guest DHCP, QGA challenge, fixed read-only checks, BIOS or explicit trusted OVMF inputs for UEFI | Needs guest QGA/Python and NoCloud; real BIOS/UEFI boot and network isolation unverified; no non-AMD64 health adapter or physical attestation |
| Cloud Image end-to-end coordination | `cloud_image_e2e.py`: prepared Linux host preflight, local trusted image or explicit pinned Ubuntu download, inspection/plan, RootFS bundle and guest health report | Synthetic pipeline tests only; pinned URL availability and real execution unverified; pinned SHA-256 checking is not upstream signature verification; no automatic dependency installation |
| Project workspace | `project_workspace.py`: local .venv creation/reuse without downloads, private outputs, validated output destinations; discovery CLI and legacy manager artifacts use outputs | Existing user captures are not moved; high-risk/device/network actions retain separate permissions; workspace policy does not itself prove containment in every standalone helper |
| Local host adapters | `host_capabilities.py`, `single_host.py`: native Linux or already-running Mac Lima guest, tool/share checks, fixed invocations, no automatic VM start | Real Lima execution and mount compatibility unverified; an installed or stopped VM is not a usable backend |
| Plan-approved progress | `preview.py`, `preview_control.py`, `status.py`, `progress.py`: loopback-only observer included in the confirmed plan with explicit opt-out, lifecycle checks and image/rootfs/verification milestones | Local HTTP/lifecycle tests passed; real browser and full Agent journey unverified; no preview control/approval API or implicit restart |

The generic core has no built-in board or assumed SoC. A pinned minimal
ARM64 RootFS and numbered board component staging now provide the beginning
of physical-device iteration. Physical IMG/BSP assembly, firmware flashing,
installer ISO generation, installed-system cloning and automatic rollback
remain unsupported. A NoCloud `cidata` ISO
is an initialization seed, not an OS installer.

## Validation record

### Pre-merge local baseline

On **2026-11-11**, code revision **`64abef2`** passed the standard command
on the local macOS host with Python 3.11:

```bash
python3 -m unittest discover -s tests -v
```

Result: **181 tests, OK, zero failures and zero errors**, using the default
temporary directory without a `TMPDIR` override. Local test socket permissions
were granted because the sandbox initially prohibited loopback and UNIX
socket binding. No tests were skipped in this recorded run.

The run covers Python logic, synthetic evidence, mocked qemu-img/libguestfs
and QEMU execution, real local preview HTTP/lifecycle checks and a fake
local QGA socket server. It does **not** validate real device collection,
Linux image construction, actual guest boot, OVMF firmware, DHCP isolation,
physical hardware compatibility, Lima execution or a browser/Agent journey.
No GitHub Actions were triggered.

The revision fixes macOS `/var` and `/tmp` alias handling in the Lima path
validator by sharing the existing restricted alias policy, and fixes two
verification tests to use the real argument parser. User-controlled symlinks,
paths outside the shared home and output overwrites remain rejected.

Temporary full log from that run: `/private/tmp/ubuntu-customizer-tests-fixed.log`.
This is a host-local diagnostic path, not a committed or durable test artifact.
Future validation records should name the tested revision, environment,
command, result and actual execution scope; do not overwrite missing
integration evidence with unit-test results.

### Upstream integration evidence retained

Upstream recorded a focused 20-test device-session run in an isolated Linux
Python environment. It covered synthetic transport guards and a local PTY;
it did not validate physical hardware or macOS picocom. The merged suite
retains these cases, both macOS alias regressions, real-parser verification
checks and narrow-parser backend-forwarding checks. A fresh combined run is
required; the older 181-test result above applies only to its named revision.

### Combined merge regression — 2026-11-12

The integrated working tree combining local `6664532` and upstream `013b048`
passed on macOS / Python 3.11 using the project virtual environment:

```bash
./.venv/bin/python -B -m unittest discover -s tests -v
```

Result: **226 tests, OK, zero failures, errors or skips**. Full local log:
`outputs/merge-tests-final.log` (ignored runtime artifact, not a durable
committed test report). The focused device-session suite also passed all
25 tests. These include actual local simulated-shell PTY execution, local
HTTP/UNIX sockets, mocked device transports and mocked image/QEMU tools;
no physical device, actual image build, guest boot or Lima run was performed.

The first combined run exposed blocking PTY child reaping on macOS. Cleanup
now releases the PTY master before bounded nonblocking reap attempts and
reports an unreaped child instead of waiting forever. Regression tests cover
kill escalation, deadline failure and descriptor cleanup. Portable shell
fixtures now set PS1 explicitly and check the actual host kernel name;
workspace tests compare canonical paths. Both real-parser and narrow-parser
backend tests, and both macOS alias regressions, remain in the merged suite.
No GitHub Actions were triggered. Local test socket/PTY permission was granted
through the host execution gate; this is not target-device access approval.

## Remaining work in priority order

1. **Real Linux VM pipeline validation.** Prepare a supported build host and
   trusted guest image with QGA/Python/cloud-init; inspect and preview first.
   Obtain separate approvals before building and booting. Record exact input
   hashes, tool versions, firmware, output hashes and complete guest-health
   results. Retain blockers if prerequisites fail. Validate BIOS/UEFI and
   restricted DHCP behavior explicitly rather than inferring them from flags.
2. **Agent handoffs and local adapters.** Exercise a real connected Agent
   journey, cancellation/retry and consent boundaries on Linux and an
   already-running Mac Lima guest. Review preview/browser behavior and
   cleanup. Never install tools, start Lima or change mounts implicitly.
3. **Diagnostic and maintenance planning.** Give diagnose / maintain goals
   their own evidence-backed decisions beyond the current evidence-only end
   state. Later mutation/restore adapters need separate review, authorization,
   idempotency and tested recovery; planning alone does not authorize writes.
4. **Real device evidence and parser depth.** Validate SSH/ADB/managed picocom and passive TTL on
   representative Linux/ARM devices; improve resumable capture, trusted device
   identity, export redaction, binding-specific DT cells and SoC pinctrl
   interpretation. Keep physical pin/electrical claims separate from software
   graphs. Add narrowly authorized deep probes only when justified.
5. **Source trust and artifact handling.** Add upstream signature verification
   and maintained source-pin updates, durable sanitized validation reports,
   bounded subprocess output during capture, and auditable plugin contracts.
6. **Future builders.** Package/service customization, installer ISO creation,
   installed-system cloning and board-specific physical assembly are future
   work. A physical adapter first needs exact board identity, verified BSP,
   bootloader/DTB/firmware/storage compatibility and an external recovery path.

## Acceptance rules

- Source code and documentation are not proof of runtime validation.
- A complete inspected plan is only a candidate for offline VM conversion.
- A bundle checksum proves artifact integrity, not bootability or authenticity.
- Only a complete challenge-bound guest-health report may set
  `boot_confirmed=true`; no such real guest result is recorded above.
- VM guest health never proves physical board compatibility or authorizes flash.
- Keep device access, offline construction, isolated boot and higher-risk
  device writes as distinct consent scopes. Follow-up buttons request the
  named next task; they do not grant unrelated permissions.
- Do not automatically trigger GitHub Actions. Record local checks honestly
  and commit fixes on `main` unless the user changes that preference.
