#!/usr/bin/env python3
"""Opt-in localhost-only, read-only progress preview for an Agent Skill session.

Reads only a checkpointed manifest.json and emits a REDACTED summary. Never
serves raw evidence, credentials, command stdout, errors or target addresses.
No remote listening and no write-capable HTTP routes.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import os
import re
import sys

MAX_MANIFEST = 2 * 1024 * 1024
STAGES = ("bootstrap", "capability", "detail", "image-plan", "image-build", "verify")
STATES = ("pending", "running", "complete", "incomplete", "failed")
STATUSES = ("ok", "error", "unavailable", "truncated", "empty")

HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; form-action 'none'">
<title>Ubuntu Customizer | Skill 运行预览</title>
<style>
:root{font-family:system-ui,sans-serif;color-scheme:dark;background:#111827;color:#e8edf5}
body{max-width:920px;margin:0 auto;padding:24px}h1{font-size:23px}
p,small{color:#9cb0c5}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px}
.card{border:1px solid #344155;border-radius:12px;padding:14px;background:#1d2939}
.value{font-size:26px;font-weight:650}.bar{height:9px;background:#344155;border-radius:20px;overflow:hidden}
#progress{height:100%;width:0;background:#82bfed;transition:width .3s}
table{width:100%;border-collapse:collapse;text-align:left}td,th{border-bottom:1px solid #344155;padding:9px}
#status{font-weight:600}footer{padding-top:20px}
</style></head><body>
<h1>Ubuntu Customizer · Skill 运行预览</h1>
<p>仅本机查看 · 页面只展示脱敏摘要 · Skill 可独立于页面运行</p>
<div class="cards">
<div class="card"><small>阶段</small><div id="stage" class="value">—</div></div>
<div class="card"><small>状态</small><div id="status" class="value">—</div></div>
<div class="card"><small>完成探测</small><div id="done" class="value">0</div></div>
<div class="card"><small>跳过探测</small><div id="skipped" class="value">0</div></div>
</div>
<h2>采集进度</h2><div class="bar"><div id="progress"></div></div><p id="percentage">等待会话…</p>
<h2>分类汇总</h2><table><thead><tr><th>类别</th><th>成功</th><th>异常</th></tr></thead><tbody id="categories"></tbody></table>
<footer><small id="update">数据来自本地采集清单，每 2 秒刷新一次；不会执行命令。</small></footer>
<script>
const $ = id => document.getElementById(id);
function set(id,value){$(id).textContent=String(value);}
async function refresh(){
 try {
  const response=await fetch('/api/status',{cache:'no-store'});
  if(!response.ok) throw new Error('status unavailable');
  const s=await response.json();
  set('stage',s.stage);set('status',s.state);
  set('done',s.completed);set('skipped',s.skipped);
  const total=Math.max(1,s.total);
  const pct=Math.min(100,Math.round(100*(s.completed+s.skipped)/total));
  $('progress').style.width=pct+'%';
  set('percentage',pct+'% · '+s.total+' 项');
  $('categories').replaceChildren();
  for(const [category,info] of Object.entries(s.categories)){
    const tr=document.createElement('tr');
    for(const value of [category,info.ok,info.other]){
      const td=document.createElement('td');td.textContent=String(value);tr.appendChild(td);
    }
    $('categories').appendChild(tr);
  }
  set('update','最近检查：'+new Date().toLocaleTimeString()+' · 无设备操作');
 } catch {
  set('status','等待数据');set('update','暂无法读取会话状态，稍后自动重试');
 }
}
refresh();setInterval(refresh,2000);
</script></body></html>"""

def load_status(session):
    root = Path(session).resolve()
    manifest = root / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        return {"schema_version": 1, "state": "pending", "stage": "bootstrap",
                "total": 0, "completed": 0, "skipped": 0, "categories": {}}
    if manifest.stat().st_size > MAX_MANIFEST:
        raise ValueError("Session manifest too large")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError("Unsupported manifest")
    items = data["items"][:10000]
    skipped = data.get("skipped", [])
    if not isinstance(skipped, list):
        skipped = []
    grouped = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = it.get("category", "other")
        if kind not in ("identity","hardware","drivers","pins","network","storage","boot","serial"):
            kind = "other"
        grouped.setdefault(kind, {"ok": 0, "other": 0})
        grouped[kind]["ok" if it.get("status") == "ok" else "other"] += 1
    stage = "bootstrap"
    if items:
        stage = next((it["stage"] for it in reversed(items)
                      if isinstance(it,dict) and it.get("stage") in STAGES), "detail")
    if data.get("state") == "complete":
        stage = "complete"
    expected = len(items) + len(skipped)
    selected = data.get("selected_modules", [])
    if isinstance(selected, list):
        # This is a lower-bound estimate. Unknown pending probes are not fabricated.
        expected += max(0, int(data.get("expected_probes", 0)) - expected)
    state = data.get("state", "running")
    if state not in STATES:
        state = "incomplete"
    return {"schema_version": 1, "state": state, "stage": stage,
            "total": expected, "completed": len(items),
            "skipped": len(skipped), "categories": grouped}

def effective_status(session):
    report = load_status(session)
    status_file = Path(session) / "skill-status.json"
    if status_file.is_symlink() or not status_file.is_file():
        return report
    if status_file.stat().st_size > 4096:
        return report
    try:
        status = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return report
    allowed_stage = ("connect", "bootstrap", "capability", "collect", "analyze",
                     "image-plan", "image-build", "first-boot", "verify", "finish")
    allowed_state = ("pending", "running", "complete", "failed", "blocked")
    if (status.get("schema_version") != 1 or
            status.get("stage") not in allowed_stage or
            status.get("state") not in allowed_state):
        return report
    done = status.get("completed")
    total = status.get("total")
    if type(done) is not int or type(total) is not int or not 0 <= done <= total <= 1000000:
        return report
    # User-selected Agent stage supersedes collector stage; category counters
    # still summarize only the local manifest and never leak source values.
    report.update({"stage": status["stage"], "state": status["state"],
                   "completed": done, "total": total})
    return report

def make_handler(session, instance_id=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Reject DNS rebinding / unexpected Host headers even on loopback.
            host = self.headers.get("Host", "")
            host_name = host.split(":", 1)[0].lower()
            if host_name not in ("localhost", "127.0.0.1"):
                self.send_error(403, "Localhost host only")
                return
            if self.path == "/":
                body = HTML.encode("utf-8")
                mime = "text/html; charset=utf-8"
                code = 200
            elif self.path == "/api/identity" and instance_id is not None:
                # Identity is used only to verify a locally managed preview
                # process before signaling it; never exposes session contents.
                body = json.dumps({"instance_id": instance_id, "pid": os.getpid()}).encode()
                mime = "application/json; charset=utf-8"
                code = 200
            elif self.path == "/api/status":
                try:
                    body = json.dumps(effective_status(session), ensure_ascii=False).encode()
                    code = 200
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    body = b'{"state":"incomplete","message":"status unreadable"}'
                    code = 503
                mime = "application/json; charset=utf-8"
            else:
                body = b"not found"
                mime = "text/plain"
                code = 404
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            self.send_error(405)
        def log_message(self, fmt, *args):
            pass
    return Handler

def serve(session, port, instance_id=None):
    path = Path(session).expanduser()
    if not path.is_dir() or path.is_symlink():
        raise ValueError("Session directory must exist and not be a symlink")
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be 1024–65535")
    if instance_id is not None and not re.fullmatch(r"[a-f0-9]{32}", instance_id):
        raise ValueError("Invalid preview instance ID")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(path, instance_id))
    print("Preview: http://127.0.0.1:%d/ (Ctrl+C to stop)" % port, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session", help="existing or about-to-start session directory")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--instance-id", help="internal managed-instance correlation ID")
    args = p.parse_args(argv)
    try:
        serve(args.session, args.port, args.instance_id)
        return 0
    except (OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
