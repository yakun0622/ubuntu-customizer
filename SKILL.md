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
6. **Plan and gate.** Use `scripts/workflow/image_plan.py` only for the
   supported base-image VM/physical compatibility assessment. Confirm source
   hash, architecture, target boot firmware, disk layout, kernel and driver
   requirements. Report blockers rather than inventing support.
7. **Execute only supported, authorized work.** For an approved VM image,
   `build_image.py` provides offline RAW/QCOW2 conversion. Optional
   `nocloud.py` renders NoCloud seed files for cloud-init-capable guests;
   `verify_vm.py` provides static checks and opt-in isolated boot attempt.
   Neither conversion nor a smoke attempt proves portable bootability.
   Full rootfs customization, installer ISO creation, installed-system
   cloning, first-boot identity scrubbing, physical IMG assembly and
   flashing are **not implemented**.
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

# Analyze an existing trusted base image against a collected session:
python3 scripts/workflow/image_plan.py SESSION_DIR \
  --target virtual-machine --format qcow2 \
  --source /safe/base.img --sha256 TRUSTED_SHA256 \
  --source-arch amd64 --output image-plan.json

# Only when the verified plan says build_allowed=true:
python3 scripts/workflow/build_image.py image-plan.json \
  --output portable.qcow2
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
the controlling host only. The page
polls a redacted summary derived from the collector's `manifest.json`
every two seconds. It never serves raw evidence. During other Skill stages,
the Agent can write an allowlisted, private checkpoint using:

```bash
python3 scripts/workflow/status.py SESSION_DIR \
  --stage image-plan --state running --completed 1 --total 3
```

Use only factual progress and never record credentials or unbounded logs.
Allowed stages: connect, bootstrap, capability, collect, analyze, image-plan,
image-build, verify, finish. The Agent should update stage boundaries
**only when those operations actually occurred**. The preview displays
status but does not control work or grant permission for any action.

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
