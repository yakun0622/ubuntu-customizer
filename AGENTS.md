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
