# Execution-plan-approved live Skill progress viewer

Ubuntu Customizer is an **AI Agent Skill**, not a web management product.
This optional page displays **only execution status**. It must not schedule,
authorize or execute operations. The Agent remains responsible for all
decisions, consent, evidence interpretation and execution controls.

## Consent and lifecycle

The Agent MUST first resolve the selected transport and actual interface,
then show the complete execution plan and ask for approval. The plan
**includes** the local-only live viewer by default, so no separate viewer
question is required. User refusal of the plan blocks connection and viewer
startup. If the user explicitly opts out of the viewer but approves the
rest of the read-only plan, the collection works without a server.

On confirmation, the Agent creates a private session and starts the
viewer **before** fixed device probes. Its startup reports a verified
localhost URL; a failed startup reports `unavailable`, never a guessed port.

Legacy manual standalone debugging example (not the Agent user journey):

```bash
# Terminal 1: launch evidence collection; a new session directory is created
python3 scripts/workflow/adaptive.py --transport local --target local \
  --output ./outputs/run-001 --yes

# Terminal 2, while Terminal 1 is running or after it completes:
python3 scripts/workflow/preview.py ./outputs/run-001 --port 8765
```

Visit `http://127.0.0.1:8765/` **from the same computer**. The server
listens only on `127.0.0.1`; terminate with Ctrl+C. If the collection has
already completed, the page shows its final state. Starting the preview is
not required for the collection. Sessions may contain sensitive data;
neither the page nor its API returns raw IP/MAC addresses, commands, stdout,
SSH aliases, file paths or credentials.

## How progress updates

- The existing collector checkpoints `manifest.json` after each probe.
  `preview.py` polls only a redacted summary on `GET /api/status`.
- For later steps (analysis, image compatibility, conversion, validation),
  the Agent explicitly invokes the **optional** checkpoint helper:

```bash
python3 scripts/workflow/status.py ./outputs/run-001 \
  --stage analyze --state running --completed 0 --total 3

python3 scripts/workflow/status.py ./outputs/run-001 \
  --stage image-plan --state complete --completed 3 --total 3

python3 scripts/workflow/status.py ./outputs/run-001 \
  --stage image-build --state blocked --completed 0 --total 1
```

Only allowlisted stage/state names and integer counters are accepted.
There are no arbitrary textual status or free-form log fields. This
status stream is advisory and does not approve modification, flashing,
image writes or boot.

## Safety details

- Listening address is fixed to loopback and Host is restricted to
  `localhost` / `127.0.0.1`.
- No CORS, POST command endpoint, WebSocket command channel or file-serving.
- No third-party dependencies or CDN. HTML uses a restrictive CSP.
- Page updates every two seconds (polling, **not** server push).
- Never publish, reverse-proxy or expose this local service to a network.
- If a session cannot be read or the browser is not available, report
  the limitation and continue working via Agent text updates.
- Status files alone do not establish actual success: the Agent must
  verify execution outcomes from evidence, tests and build logs.

## Agent-managed lifecycle (recommended)

After the user approves a plan explicitly including the local viewer,
the Agent passes `--preview-approved` to the read-only collector.
Both the staged and managed interactive collectors create the session,
start the observer before collection, and report any startup failure while
preserving the approved read-only collection scope.

```bash
# Internal Agent helper: only after reviewing/approving the connection plan:
python3 scripts/workflow/adaptive.py \
  --transport ssh --target trusted-host-alias \
  --output ./outputs/run-002 --yes --preview-approved

# The command prints the actual preview URL and session path.
# Check status later without starting a second server:
python3 scripts/workflow/preview_control.py status ./outputs/run-002

# Stop the preview when the user is finished:
python3 scripts/workflow/preview_control.py stop ./outputs/run-002
```

For interactive SSH/ADB/TTL, use the persistent device-session adapter;
it supports the same approved viewer and emits a live `preview_ready`
JSON event BEFORE the first fixed probe:

```bash
# Internal example, never run without plan approval:
python3 scripts/workflow/adaptive.py \
  --transport adb --target AUTHORIZED_SERIAL \
  --output ./outputs/managed-001 \
  --interactive-shell-approved --preview-approved --yes
```

Only the *actual returned* `preview_ready.url` may be presented to the
user. Tooling that buffers stdout may deliver the event to the Agent only
when collection ends; do not claim earlier user visibility in that case.
A failed local observer must be disclosed and is not a reason to invent a
remote-accessible link.

For a session that already exists, the Agent can start the observer separately:

```bash
python3 scripts/workflow/preview_control.py start ./outputs/run-002 --approved
python3 scripts/workflow/preview_control.py status ./outputs/run-002
python3 scripts/workflow/preview_control.py stop ./outputs/run-002
```

A random available port is selected by default and the actual URL is
reported after a successful local readiness check. The child process
stays on the **controlling/build host**, never on the target device unless
the user deliberately runs the Skill there. The Agent must not claim a
preview is running until the start command confirms success.

The runtime record `preview-runtime.json` is stored privately in the
session directory. To stop, the local helper first matches the HTTP
instance nonce and PID against that record. If the record is stale, it
refuses to signal the PID. In that case, after checking no preview is
running, call:

```bash
python3 scripts/workflow/preview_control.py clear-stale ./outputs/run-002
```

The control helper terminates **only the preview observer**; collection,
image planning or other Skill steps are not stopped. When the user expressly opts out of
the viewer, no browser server is started, and read-only work continues
after the rest of the plan is approved.

The status URL is loopback-only. A separate device (including a phone)
cannot access that address without a deliberately configured, reviewed
tunnel; this Skill does not automatically create tunnels or network exposure.

## Limitations

- The preview lives beyond the completion of a collection until explicitly
  stopped, which is useful for reviewing final results.
- On systems that disallow background child processes or localhost sockets,
  preview may be unavailable. This never blocks core Skill work.
- The HTTP service has no remote-control endpoint. `stop` is implemented
  locally via a verified process signal, not an HTTP command.
- A stale record must be handled explicitly; no unchecked PID-kill behavior
  is permitted.
- The observer is not a test result and does not establish image bootability.

## Automatic progress for image operations

When preview is enabled and its local process identity is verified, these
scripts update the original session's `skill-status.json` automatically:

| Script | Stage | Actual milestones | Outcomes |
| --- | --- | --- | --- |
| `image_plan.py` | `image-plan` | Source checksum, manifest integrity, compatibility result | `complete`, `blocked`, `failed` |
| `build_image.py` | `image-build` | Input check, format check, offline conversion, output hash, manifest | `complete`, `blocked`, `failed` |
| `nocloud.py` | `first-boot` | NoCloud seed, optional ISO, final manifest | `complete`, `blocked`, `failed` |
| `verify_vm.py` | `verify` | Output hash, QEMU metadata, optional boot attempt | `complete`, `blocked`, `failed` |

The image plan carries `discovery.session`. The image-build result
propagates it as `discovery_session`, so later stages can update the
same session. `nocloud.py` reads the plan directly. Older reports without
this field simply cannot auto-report to the same viewer.

A **blocked** image plan is the expected safe outcome for incompatible or
unverified physical hardware. A failed source checksum, image conversion
or output validation is **failed**. Static VM verification can be
`complete` without proving a guest boot. A QEMU timeout or clean exit
with no confirmed boot is `blocked`; a nonzero QEMU process exit is
`failed`. These labels concern the stage outcome, not the overall
device or image portability.

Image-stage counters have their own denominators: old collection skips are
not added to new image progress. Updates contain only allowlisted stage,
state and numeric counts. No errors, paths, passwords or image contents are
sent to the browser. If preview is not running, no automatic status file
is written and no step is blocked. Closing the preview stops further
automatic updates even if image work continues.

Existing manual `status.py` commands remain available to the Agent for
other workflow stages; they are no longer necessary for the four image
scripts above.
