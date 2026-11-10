---
name: ubuntu-customizer
description: Agent-led, evidence-first discovery and customization of Ubuntu, Debian, Armbian and compatible Linux systems; plan portable images, assess hardware boot compatibility and safely coordinate builds, maintenance and recovery across SSH, ADB, TTL or local access.
---

# Ubuntu Customizer — AI Agent Skill

**This is a Skill, not a standalone application.** The AI Agent guides the
conversation and invokes only the scripts it needs. Device manager menus,
browser exports and image tools are optional helpers, never prerequisites.

Read [Agent workflow](references/agent-workflow.md) first. Then read
[Device discovery](references/device-discovery.md),
[Image building](references/image-building.md),
[Offline RootFS building](references/rootfs-building.md),
[QEMU first-boot verification](references/first-boot-verification.md),
[System management](references/system-management.md),
[ARM hardware](references/arm-hardware.md), or
[Safety](references/safety.md) *only for relevant stages*.

## Primary workflow

1. **Establish intent.** Ask whether the user needs discovery, diagnosis,
   maintenance, recovery or a portable system image. Distinguish target,
   control host and build host.
2. **Choose transport and optional preview.** Offer SSH / ADB / passive TTL /
   local depending on access. Before starting work, explicitly offer: "是否开启本地实时运行预览页面？"
   The default is **no**. Never assume a device model or claim access that is unavailable.
   If the user opts in, use `scripts/workflow/adaptive.py --preview-approved`
   or `scripts/workflow/preview_control.py start SESSION_DIR --approved` to
   start the localhost observer. Do not start a web server when declined.
3. **Discover.** Obtain connection consent and execute only permitted,
   read-only probes. Prefer `scripts/workflow/adaptive.py` when available,
   or give the user precise commands to run locally.
4. **Normalize evidence.** Validate the session's SHA-256 manifest.
   Summarize OS, architecture, hardware, drivers, boot chain and unknowns.
   Use `dossier.py`, `capabilities.py`, `topology.py`,
   `device_tree.py`, `link_graph.py` selectively.
5. **Decide next task.** Present evidence and options. For portable images,
   distinguish VM/cloud, installer ISO and **physical-hardware IMG** before
   choosing a backend.
6. **Inspect, plan and gate.** First use `scripts/workflow/image_inspect.py`
   to inspect the existing RAW/QCOW2 source **read-only** (qemu-img,
   virt-filesystems, virt-inspector, virt-drivers and guestfish). Then use
   `image_plan.py` for verified device-to-image compatibility decisions.
   The plan automatically re-inspects the image and requires proven partition
   table (GPT/MBR), partitions, Linux OS, measured guest architecture, kernel,
   firmware boot mode and bootloader. The declared source architecture alone
   can never authorize a build. Unknown tooling, unreadable filesystems,
   encrypted/backing-chain images or mismatches become explicit blockers.
   A successful plan is a **candidate for offline format conversion**, not
   proof of bootability. Physical-device IMG assembly remains blocked.
7. **Execute only supported, authorized work.** For an approved VM image,
   `build_image.py` provides offline RAW/QCOW2 conversion.
   `rootfs_builder.py` can **preview** a fixed offline RootFS recipe and,
   after explicit separate `--approved` authorization, make a private clone
   and apply an allowlisted hostname/MOTD/NoCloud initialization recipe.
   It runs virt-customize and narrowly scoped virt-sysprep *only on that
   private cloned image*, then validates the output and publishes a
   checksum-backed bundle. Require an inspected Linux VM image with
   cloud-init; missing support blocks work. `verify_vm.py` retains
   static verification and a legacy inconclusive smoke attempt.
   `verify_first_boot.py` is the **separately approved** RootFS bundle
   boot-health backend: it starts an isolated x86_64 QEMU snapshot and
   uses a challenge-bound, fixed read-only QEMU Guest Agent probe to check
   Linux boot, healthy systemd, completed cloud-init with matching NoCloud
   instance ID, hostname, initialized machine-id, regenerated SSH host keys,
   SSH service and local network. All checks must pass before
   `boot_confirmed=true`. Missing Guest Agent/Python or UEFI firmware
   is a blocker; never inject dependencies or infer guest boot from QEMU
   exit codes. Full arbitrary RootFS package installation, installer ISO
   creation, installed-system cloning, complete first-boot identity
   personalization, physical IMG/BSP assembly and flashing remain
   **not implemented**.
8. **Verify and report.** Record actual results, source/evidence hashes,
   image hash, remaining compatibility blockers, tests performed and
   recovery path. Do not claim tests or builds that were not run.

## Examples (optional helpers)

```bash
# First collect evidence, with the user's approval:
python3 scripts/workflow/adaptive.py
# Then assess the evidence:
python3 scripts/workflow/dossier.py SESSION_DIR
python3 scripts/workflow/capabilities.py SESSION_DIR

# Optional standalone source inspection report (no image modification):
python3 scripts/workflow/image_inspect.py /safe/base.img \
  --sha256 TRUSTED_SHA256 --output source-inspection.json

# Analyze an existing trusted base image against a collected session:
python3 scripts/workflow/image_plan.py SESSION_DIR \
  --target virtual-machine --format qcow2 \
  --source /safe/base.img --sha256 TRUSTED_SHA256 \
  --source-arch amd64 --output image-plan.json

# Only when every mandatory guest inspection check passed AND the
# verified plan says build_allowed=true:
python3 scripts/workflow/build_image.py image-plan.json \
  --output portable.qcow2

# Optional fixed offline RootFS customization (requires approved image-plan):
# Copy profiles/examples/rootfs-config.json and update public key, instance-id.
python3 scripts/workflow/rootfs_builder.py image-plan.json \
  --config rootfs-config.json --dry-run

# Separate explicit approval is required to write an isolated image bundle:
python3 scripts/workflow/rootfs_builder.py image-plan.json \
  --config rootfs-config.json --output-dir ./new-rootfs-bundle --approved

# Recheck the published image/seed hashes and qemu metadata, read-only:
python3 scripts/workflow/rootfs_builder.py \
  --verify-bundle ./new-rootfs-bundle

# Only after separate approval, for a VM with QEMU Guest Agent/Python.
# Add --ovmf-code and --ovmf-vars for verified UEFI guests.
python3 scripts/workflow/verify_first_boot.py \
  --bundle ./new-rootfs-bundle \
  --timeout 300 --report first-boot-health.json --approved
```

## Safety invariants

- Never equate a declared source architecture with verified guest architecture.
- Unknown hardware/probe results are **unknown**, not absent.
- A DT software relationship never verifies physical pinout or voltage.
- R0 read-only; R1 offline artifacts; R2 service/package changes; R3
  network/kernel/DT; R4 device disk writes/firmware. Require separate
  approval, suitable backups and recovery at each higher-risk boundary.
- Never write to target disks or flash firmware on the strength of a generic
  architecture match.
- Never automatically publish raw evidence, credentials or machine identities.
- Do not enable bypasses for SSH trust or privilege elevation automatically.
- Respect no CI execution preference where applicable; submitted test source
  is not proof of passing tests.

## Optional live progress preview (not the Skill UI)

The AI Agent is always the workflow controller. A preview is **opt-in only**:
ask the user before starting a localhost service and honor "no" without
reducing any Skill functionality. Do not expose the preview on LAN or
the public Internet; bind only to `127.0.0.1`. When the session directory exists, the Agent can start it with explicit
user approval, or add `--preview-approved` to an authorized
`adaptive.py` collection to launch the observer as soon as the session
is created:

```bash
python3 scripts/workflow/preview_control.py start SESSION_DIR --approved
python3 scripts/workflow/preview_control.py status SESSION_DIR
python3 scripts/workflow/preview_control.py stop SESSION_DIR
```

The start command reports the actual `http://127.0.0.1:<port>/` URL on
the controlling host only. The page polls sanitized local checkpoint status
every two seconds. It never serves raw evidence.

**Image helpers now report automatically when the preview is live**:
- `image_plan.py` → `image-plan`: source checksum, evidence integrity,
  compatibility decision (`blocked` when prerequisites are missing).
- `build_image.py` → `image-build`: source verification, format inspection,
  conversion, output verification, result manifest.
- `nocloud.py` → `first-boot`: NoCloud files, optional seed ISO, final manifest.
- `verify_vm.py` → `verify`: output hash, metadata, optional QEMU attempt.
  Static verification `complete` is **not** a verified guest boot;
  inconclusive boot attempts are `blocked` and nonzero QEMU exits `failed`.

The image plan contains the original `discovery.session`, and the build
result carries it as `discovery_session`, so the same user-approved preview
follows sequential phases. The helper verifies the local running preview
before updating `skill-status.json`. No live preview means **no automatic
status file writes** and no change to image-building behavior. Stopping
preview stops subsequent automatic status updates.

For other Agent-led stages not implemented as image scripts, an authorized
Agent can still explicitly publish factual progress:

```bash
python3 scripts/workflow/status.py SESSION_DIR \
  --stage analyze --state running --completed 1 --total 3
```

Only allowlisted stage/state names and integer counters are persisted;
never include credentials, paths, error text or command output in the
browser status. Recognized image phases are `image-plan`, `image-build`,
`first-boot`, and `verify`. The preview observes status but does not
control or approve execution.

If a browser server cannot run on the controlling computer, explain that
preview is unavailable and continue the Skill normally with text progress.
Never assert that a preview or background process has started unless the
runtime has actually started it. See `references/live-preview.md`.

## Completion response contract

After **each development or Skill execution step**, report what changed,
which repository commit was produced, what tests actually ran (or did not),
and any remaining blockers. Then propose **one concrete next task** that
advances the existing user goal. In a host UI supporting interactive
follow-up actions, offer one visible **“继续下一步”** button which submits
a specific next-task prompt only when clicked. Otherwise provide the exact
next-task phrase for the user to send. A button is a follow-up request,
not permission to perform destructive operations or a claim that
background work has begun. Never automatically execute the next phase
without the user's follow-up or another explicitly authorized workflow.

## Source image inspection invariants

See `references/image-building.md`. Prefer a locally stored immutable base
image and a separately trusted SHA-256. Inspection runs Linux libguestfs
tools with a fixed image format, read-only guestfish access, no guest
networking, bounded tool output and timeouts. Treat a missing tool or
unrecognized XML as an evidence gap, **not** proof of an absent bootloader,
kernel, OS or partition. Store the source image SHA-256, tool provenance,
observed facts and failed checks in `image-plan.json`. The conversion helper
repeats the source inspection and rejects changes before invoking qemu-img.
Never run host-side mount, mkfs, parted write commands or firmware flashing
as part of source inspection. For a physical target, source guest boot
components still need a separately verified board-specific BSP and recovery
path. Successful checks do not substitute for boot testing.


## RootFS Builder Skill rules (VM only)

The Agent must first inspect both source image and target device evidence.
The RootFS recipe has a strict schema; only hostname, MOTD and a
public-key-only NoCloud first-boot seed are supported. Never accept
arbitrary executable commands, scripts, network package installation,
passwords, embedded private keys or custom guest file paths in the recipe.
Always run dry-run first and present the exact operations and dependencies
before seeking separate approval. No preview UI consent implies build
consent. Refuse any physical-device image plan without its independent
verified BSP/bootloader/DTB/firmware approval and suitable builder adapter.

RootFS customization uses only a private staging copy; never apply
virt-customize or virt-sysprep to the original image or a running VM disk.
Regenerating SSH host keys and machine-id is requested by virt-sysprep;
actual first-boot behavior and the absence of all device-specific secrets
remain **unverified** until separately audited. The optional NoCloud
seed assumes cloud-init support; the builder checks that the guest has
an installed cloud-init configuration but does not claim it was applied
on boot. Final bundles include image, seed, hashes and a build manifest;
verify these before attempting isolated VM boot testing. See
references/rootfs-building.md for the exact contract.

## Verified guest boot acceptance rule

Do not treat QEMU process exit status, boot messages or a Guest Agent ping
as successful boot. Use `verify_first_boot.py` only after explicitly
obtaining VM-launch authorization. It validates a RootFS bundle, boots a
temporary snapshot with TCG, offline restricted-DHCP virtual networking,
and a private local QEMU Guest Agent socket. The Agent obtains a fresh
challenge-bound, fixed read-only guest health report. Only if every check
passes may the report set `boot_confirmed=true`. Record incomplete
cloud-init, mismatched NoCloud instance ID, missing/old machine-id, invalid
SSH host key state, network errors or absent QGA as blocked/failed.
Do not infer physical board compatibility from an x86_64 VM result.
The optional status preview observes only sanitized states and cannot
approve or initiate this verification. See
`references/first-boot-verification.md`.
