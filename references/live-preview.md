# Optional live Skill execution preview

Ubuntu Customizer is an **AI Agent Skill**, not a web management product.
This optional page displays **only execution status**. It must not schedule,
authorize or execute operations. The Agent remains responsible for all
decisions, consent, evidence interpretation and execution controls.

## Consent and lifecycle

Before connecting or collecting, the Agent should ask:

> 是否开启本地实时运行预览页面？默认关闭，开启后可以查看采集和镜像构建进度。

If the user declines, do not start a server. The Skill continues normally.
If the user agrees and execution access is available, the Agent starts the
preview after the session directory is created:

```bash
# Terminal 1: launch evidence collection; a new session directory is created
python3 scripts/workflow/adaptive.py --transport local --target local \
  --output ./sessions/run-001 --yes

# Terminal 2, while Terminal 1 is running or after it completes:
python3 scripts/workflow/preview.py ./sessions/run-001 --port 8765
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
python3 scripts/workflow/status.py ./sessions/run-001 \
  --stage analyze --state running --completed 0 --total 3

python3 scripts/workflow/status.py ./sessions/run-001 \
  --stage image-plan --state complete --completed 3 --total 3

python3 scripts/workflow/status.py ./sessions/run-001 \
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
