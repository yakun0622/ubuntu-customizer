# Managed device sessions: TTL/picocom, ADB and SSH

## Scope

The Agent manages one *real* persistent console process for an approved
read-only discovery session. This is separate from old passive serial
logging. It is not a general-purpose shell or a firmware flasher.

| Transport | Backend process | Can send fixed probes? |
| --- | --- | --- |
| TTL | picocom inside a private PTY, 8N1, no flow control | Yes, **only after shell prompt is observed** |
| ADB | adb -s SERIAL shell | Yes; newly opened shell is probed |
| SSH | ssh -tt with BatchMode and strict known-host checking | Yes; no password prompts or trust bypass |
| Old TTL mode | pyserial.receive | No; still available for passive boot capture |

The Agent owns the open PTY throughout the collection. It captures the raw
local transcript in a mode-0600 console.log, writes each fixed probe result
to a separate 0600 file, and checkpoints a SHA-256 manifest. Unknown or
unavailable probes are reported; a completed session is **not** evidence of
booting an Ubuntu image.

## Task-start permission matrix and endpoint binding

Before any real Python/device command, obtain the task-local
`local_access` and target `target_access` grants separately
(`none/read/read-write`). Host permission is limited to the current
project; target permission is bound to the selected endpoint **only after**
the reviewed connection plan is confirmed. No session is started when
target read permission is absent or when the local project cannot store
the required private outputs.

Once the permission matrix and plan are confirmed, Python helpers and
the existing fixed read-only SSH/ADB/TTL probe batch run automatically.
Target `read-write` permits only supported reversible ordinary changes
with review/backup/recovery, NOT arbitrary Shell writes: the current
adapter still only runs fixed read-only diagnostics. Revoking/changing
target access invalidates the prior session. eMMC writes, flash,
reboot, network cutover, privilege escalation and untrusted scripts
are not covered by a blanket task grant.

## Direct device commands after one confirmed plan

Once the user confirms the device connection and read-only diagnostic
scope, execute device-targeted Python helpers and the supported shell
probes inside this verified session **automatically**, without asking
for consent before every Python or Linux/Android command.
`--approved-readonly`, `--interactive-shell-approved` and `--yes`
are CLI records of the *already-confirmed plan*, not instructions to
ask again. Reuse one process/PTY, stream progress and continue diagnostics.

This backend intentionally enforces named fixed read-only commands;
it is **not** an unrestricted Shell executor. Do not send arbitrary
user-provided commands or text copied from UART logs. Unknown prompts,
login and U-Boot remain blocked. Separate authorization remains
necessary for network changes, reboot, eMMC/partition/firmware writes,
privilege escalation, untrusted code and other destructive actions.
The OS and host tool sandbox can still require its own permission.

## Agent invocation (internal helper, not a user setup checklist)

The Agent must first select the connection method, resolve its exact
interface, explain a detailed read-only execution/monitoring plan and wait
for explicit confirmation. That consent covers the full scoped session of consecutive read-only
device Python and remote shell diagnostics plus the loopback-only viewer,
**without per-command permission prompts**. It does not authorize
device writes or reboot.
Use a unique private session under the current project's **./outputs/**
directory. Do not put evidence in the repository root or a different folder. Add
`--preview-approved` to the managed `adaptive.py` invocation when the
reviewed plan includes the viewer: the session starts it **before** probes
and emits a `preview_ready` URL. Do not invent a URL or expose it to
other machines. The commands below are illustrative implementation calls:

    ./.venv/bin/python -B scripts/workflow/adaptive.py \
      --transport ttl --target /dev/cu.wchusbserial1140 \
      --baud 921600 --output ./outputs/session-unique \
      --interactive-shell-approved --preview-approved --yes

    ./.venv/bin/python -B scripts/workflow/adaptive.py \
      --transport adb --target SERIAL \
      --output ./outputs/adb-session-unique \
      --interactive-shell-approved --yes

    ./.venv/bin/python -B scripts/workflow/adaptive.py \
      --transport ssh --target trusted-ssh-config-alias \
      --output ./outputs/ssh-session-unique \
      --interactive-shell-approved --yes

The device-session helper can also be run directly with --approved-readonly.
It is **never** appropriate to ask ordinary users to select flags unless the
host Agent has no local execution capability.


## Live progress for persistent sessions

Once the plan is confirmed, the Agent invokes the managed adapter with
`--interactive-shell-approved --preview-approved --yes`. The backend
creates a mode-0700 session directory, checkpoints its manifest, starts
the loopback observer, and emits a verified `preview_ready` URL before
connecting and issuing fixed shell probes. The manifest updates after
each named probe; the web page polls only sanitized status counts.
A user-specified preview opt-out omits the flag. Startup failure is
recorded as `preview.state=unavailable`; collection continues.

Viewer address `127.0.0.1` is available only on the controlling host.
Remote viewing requires separately reviewed secure access, not an
automatically exposed `0.0.0.0` listener.

## TTL login/shell rules

1. Only one process may own the serial port. Close an existing picocom before
   starting an Agent-managed picocom session.
2. Read the initial serial stream for a trusted shell prompt. Android
   console:/ # and normal host:user shell prompts are recognized. U-Boot,
   login/password and unknown prompts must not be given shell commands.
3. An idle serial console may produce no prompt. Never assume that silence
   means a shell is available. The Agent can ask the operator to confirm
   the terminal's input line is empty; only then can it request one blank CR
   through --wake-console-approved.
4. If Shell verification fails, save what was received and return blocked,
   without attempting passwords, sudo/su, reboot, saveenv or device writes.
5. Once a shell is identified, run only internally enumerated fixed read-only
   probes. Each probe is bracketed by unique output markers, return code is
   recorded and subsequent probes are stopped if marker sync is lost.
6. Treat console transcript as sensitive: kernel command lines, serial
   numbers, device identifiers and IP addresses may be included.

## Operating-system probes and limits

The first interactive probe tests whether Android's getprop is available.
Subsequent probes are selected from common, Android-specific or Linux-specific
fixed lists (OS, model, kernel, CPU/memory, device tree compatibility, storage,
network). No untrusted input is treated as executable text.

Device customization **beyond read-only inventory** remains out of scope
for this session manager: Ubuntu rootfs/IMG construction, U-Boot changes,
DTB/kernel replacement, network changes, firmware flash and eMMC writes must
go through separately approved and implemented workflows. In particular,
a working TTL/ADB/SSH session does not prove a W152D-compatible BSP exists.

## Host permissions and reproducible checks

Codex/host sandbox approvals are independent of Skill permission prompts.
Group a scope of fixed read-only operations into one persistent command
rather than asking for a separate host action per probe. Do not disable
sandbox protections or bypass SSH/ADB authorization.

Offline validation:

    ./.venv/bin/python -B -m unittest discover -s tests -p 'test_device_session.py' -v

Those tests exercise terminal states, an allowlist, synthetic sessions and a
real local PTY shell. They do **not** test a physical W152D, macOS picocom,
ADB or SSH endpoints. Physical tests require separate access and evidence.
