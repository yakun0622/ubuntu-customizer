# Ubuntu Customizer — Agent entrypoint

This repository implements an **AI Agent Skill**, not a CLI application.
Always read `SKILL.md` and `references/interactive-agent-flow.md` for
device customization, diagnostic, image build, or boot-verification requests.

## User-facing behavior

When the user says **“开始” / “开始定制系统” / “开始检查设备”**:

1. Begin the guided workflow. Inspect the host read-only if the Agent has
   actual local execution access; never claim access or results you lack.
2. Infer goal and target from the ongoing conversation. Ask exactly **one**
   short question only for the next missing decision, not a questionnaire.
3. Use `agent_journey.py` as an optional pure next-step/consent planner.
   After a successful tool result, automatically advance safe stages.
4. Choose available local Linux or already-running Mac Lima tools behind
   the scenes. Do not ask the user to select Python or QEMU commands.
5. Offer the optional localhost progress preview; default **no**.
6. Obtain explicit authorization before read-only device connection,
   offline image construction, isolated VM boot, or higher-risk device
   changes. They are separate scopes; never infer approval from “开始”.
7. After a blocker, stop, explain the specific requirement and offer one
   safe, actionable next choice. Never invent compatibility or bypass
   firmware/BSP/recovery checks.
8. Summarize factual evidence, paths/artifact checksums, executed tests and
   unverified items; give **one** concrete follow-up button when supported.

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
`python3 -m unittest discover -s tests -v` when an execution environment
is available. Keep any added workflow helpers auditable and noninteractive
by themselves; the Agent should conduct the conversation.
