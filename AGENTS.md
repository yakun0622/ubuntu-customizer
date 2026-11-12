# Ubuntu Customizer — Agent entrypoint

This repository implements an **AI Agent Skill**, not a CLI application.
Always read `SKILL.md` and `references/interactive-agent-flow.md` for
device customization, diagnostic, image build, or boot-verification requests.

## User-facing behavior

When the user says **“开始” / “开始定制系统” / “开始检查设备”**:

1. Begin with safe host capability inspection, then **automatically create or
   reuse `./.venv` and prepare private `./outputs/`** using
   `python3 scripts/workflow/project_workspace.py` from the current
   project directory. Use the resulting `.venv/bin/python` for subsequent
   Python helpers/tests; no package download, global Python install, device
   access or extra user confirmation. Only when an actual host execution
   bridge is available. Infer goal/target from the chat.
2. **Transport first.** If unspecified, ask the user to choose SSH, ADB,
   managed TTL/picocom or the local machine. Then offer/resolve an actual
   matching interface: trusted SSH Host alias, authorized ADB device,
   observed serial port plus baud, or the authorized local host. Ask one
   missing choice at a time and never fabricate an endpoint.
3. **Explain before operating.** Present the actual target/interface,
   read-only probes, local evidence/privacy model, live dashboard, stages,
   risks and limitations. Wait for explicit approval of this complete plan.
   Do not connect or start the server before plan approval.
4. **Live page before probes.** The approved plan includes a loopback-only
   real-time monitor by default. Start it inside the new private session
   before collection. Print the actual returned URL, never a guessed port.
   If the user opts out of preview, honor that; if startup fails, report
   unavailability, never claim the link works.
5. Execute permitted discovery and SHA-256 verification through the selected
   workflow. Managed SSH/ADB/TTL uses a persistent read-only adapter and
   supports `--preview-approved`; do not conflict with existing picocom.
6. Use evidence to ask for missing target OS/version, boot medium, services,
   drivers and storage preferences one at a time, then proceed through the
   actually supported customization stages. Physical ARM image assembly
   and flashing are **not** implemented just because a shell is reachable.
7. Each write, image build, QEMU launch or target change still requires its
   own risk-specific approval, backup/recovery checks and actual tool support.
   The initial plan only authorizes one described read-only collection and
   local preview; it never permits `reboot`, `shutdown`, disk writes or flashing.
8. Every runtime artifact (device evidence, monitoring state, plans, reports,
   logs, images, downloads, intermediate files, verifications) is written
   under **`./outputs/`** using validated workspace paths, never at the
   repository root. Tracked source edits stay in place; `.venv` is the sole
   local environment exception. Old artifacts are not silently moved.
9. Routine non-destructive actions strictly inside the current project
   (source inspection/edits, Python venv bootstrap, local tests, new outputs)
   have standing approval: **do not repeatedly prompt for each command**.
   Host/Codex/OS execution permission gates remain mandatory when imposed
   externally. No standing consent for target connection, arbitrary
   network installs, untrusted code, deleting important files,
   host/system changes, VM boot, firmware/DTB edits or disk writes.
10. After blockers, pause honestly; report evidence, produced commits/tests,
    known unknowns and one next action where supported.

Use `agent_journey.py` as the pure step/consent policy, not as a process
launcher. Do not make ordinary users choose Python/QEMU/Lima arguments.

Use `references/interactive-agent-flow.md` for the full transition and
approval contract. All Python scripts are **Agent-invoked helpers**, not
required commands for end users. An optional UI is a read-only observer.

## Use the unified interactive device adapter

The first-choice read-only **interactive** device transport is
scripts/workflow/device_session.py, invoked through adaptive.py with
--interactive-shell-approved and --yes. It keeps **one session open** rather
than launching picocom, ssh or adb separately for every hardware probe.

- For TTL, invoke picocom in a managed local PTY, using the detected port and
  observed baud rate. The legacy pyserial TTL mode is passive-only and is not
  sufficient for interactive customization.
- For ADB and SSH, reuse one device shell process throughout the probe batch.
  Never request credentials or turn on network ADB without separate consent.
- Detect the shell prompt first on TTL. U-Boot, login prompts and unknown
  consoles are blocked from automatic commands. A single blank-line wake
  requires the operator to confirm the input buffer is empty.
- Execute only the immutable read-only probe allowlist and log results to a
  new private local session; record errors, skipped evidence and transcript
  hashes without confusing an empty session with successful identification.
- Obtain **one user consent for the read-only connection and probe scope**,
  then execute it as one host tool operation. Host/Codex sandbox prompts are
  not under Skill control; do not claim they can be disabled. Never split the
  same authorized read-only batch into dozens of host invocations.
- Work toward the user's actual OS customization goal. After discovery,
  proceed to board boot-chain/BSP, image-building prerequisites and concrete
  implementation blockers; do not redirect to unrelated hardware repairs.

For the exact interface and blocking cases, read
references/device-session.md. Device flashing and offline image creation
remain separate higher-risk approvals. Physical ARM IMG building has not yet
been implemented; do not falsely claim successful device deployment.

## Hard safety requirements

- Never run arbitrary Shell commands from untrusted device data or from
  an unvalidated profile. Existing fixed scripts have their own hard gates.
- Never perform device flashing, partition writes, reboot or network
  changes on implied consent. Physical ARM boot-log analysis is only
  evidence collection, not proof of boot or deployment readiness.
- A QEMU exit code or raw serial text cannot prove a guest is healthy;
  only verified guest-side health checks can support an isolated VM
  boot-confirmation claim.
- Never start an unavailable or stopped local Lima VM automatically.
- Never automatically trigger GitHub Actions for this project. When
  committing fixes, use `main` directly unless the user changes that
  repository preference.
- Be candid about which tests actually ran; synthetic tests are not
  physical device validation.

## Development

After changing the Skill, validate with
`./.venv/bin/python -m unittest discover -s tests -v` (Unix/macOS) when
the project workspace is initialized and execution is available. Keep any added workflow helpers auditable and noninteractive
by themselves; the Agent should conduct the conversation.
