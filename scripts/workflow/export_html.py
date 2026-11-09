#!/usr/bin/env python3
"""Render a self-contained offline HTML hardware explorer from verified evidence.

Offline only. No HTTP server, remote access or external JavaScript. Source data
is inserted as JSON in an inert script tag; UI uses textContent, never innerHTML.
"""
import argparse
import html
import importlib.util
import json
from pathlib import Path
import sys

SPEC = importlib.util.spec_from_file_location("uc_explore", Path(__file__).with_name("explore.py"))
explore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(explore)

MAX_NODES = 6000
MAX_EDGES = 30000

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'">
<title>Ubuntu Customizer | Offline Hardware Explorer</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif;background:#101521;color:#eef3f8}
*{box-sizing:border-box}body{margin:0}header{padding:20px 24px;border-bottom:1px solid #304153}
h1{font-size:22px;margin:0 0 5px}h2{font-size:16px;margin:0 0 12px}p{line-height:1.5}
.muted,small{color:#a4b6c6}.summary{display:flex;flex-wrap:wrap;gap:15px;margin-top:10px;font-size:13px}
main{display:grid;grid-template-columns:minmax(260px,360px) 1fr;min-height:75vh}
aside{border-right:1px solid #304153;padding:20px;overflow:auto;max-height:80vh}
article{padding:24px;overflow:auto}input,select{width:100%;padding:10px;margin-bottom:10px;background:#202b39;border:1px solid #405469;border-radius:8px;color:inherit}
button{font:inherit;color:inherit;background:#182536;border:1px solid #405469;cursor:pointer;border-radius:8px;text-align:left;padding:10px;width:100%;margin-bottom:6px;overflow-wrap:anywhere}
button:focus-visible{outline:2px solid #8fbbf0}button[aria-pressed=true]{background:#294563;border-color:#99c9ed}
.card{background:#1a2534;border:1px solid #34475c;padding:15px;border-radius:10px;margin-bottom:14px;overflow-wrap:anywhere}
pre{overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:12px;line-height:1.5}
.pill{display:inline-block;margin:4px 8px 4px 0;padding:3px 8px;border-radius:30px;background:#304357;font-size:12px}
section{margin:18px 0}a{color:#a6d1fa}
@media(max-width:750px){main{grid-template-columns:1fr}aside{max-height:45vh;border-right:0;border-bottom:1px solid #304153}article{padding:16px}}
</style>
</head>
<body>
<header><h1>Hardware Explorer</h1><div class="muted">Offline evidence viewer · read-only · no device commands</div><div class="summary" id="summary"></div></header>
<main>
<aside><h2>Device topology</h2>
<label for="query">Search nodes</label><input id="query" type="search" placeholder="Name, ID, driver or bus">
<label for="type">Node category</label><select id="type"><option value="">All categories</option><option value="device">Device</option><option value="driver">Driver</option><option value="device-tree-node">Device tree</option></select>
<small id="count"></small><div id="nodes"></div></aside>
<article><h2 id="heading">Select a node</h2><div class="card" id="info">Choose a node on the left to inspect its properties and relationships.</div>
<section><h2>Evidence gaps</h2><div id="gaps" class="card"></div></section>
<section><h2>Safety</h2><p class="muted">Linux sysfs and device-tree evidence describe software bindings, not PCB wiring, electrical voltage or functional hardware. Missing probes do not establish absent hardware. This offline viewer cannot modify a device.</p></section>
</article></main>
<script type="application/json" id="payload">__PAYLOAD__</script>
<script>
"use strict";
const data = JSON.parse(document.getElementById("payload").textContent);
const index = new Map(data.nodes.map(n => [n.id,n]));
const query = document.getElementById("query");
const type = document.getElementById("type");
const nodes = document.getElementById("nodes");
const heading = document.getElementById("heading");
const info = document.getElementById("info");
let selected = null;
function element(tag, value, parent, className) {
  const e = document.createElement(tag);
  if (value != null) e.textContent = typeof value === "string" ? value : JSON.stringify(value,null,2);
  if (className) e.className = className;
  if (parent) parent.appendChild(e);
  return e;
}
function show(nodeId) {
  selected = nodeId;
  const node = index.get(nodeId);
  heading.textContent = node ? node.name || node.id : "Select a node";
  info.replaceChildren();
  if (!node) return;
  element("div",node.id,info,"muted");
  element("pre",node,info);
  const links = data.edges.filter(e => e.from === nodeId || e.to === nodeId);
  element("h2","Relationships (" + links.length + ")",info);
  if (!links.length) element("p","No relationships observed in this collection.",info,"muted");
  for (const edge of links.slice(0,1000)) {
    const card = element("div",null,info,"card");
    element("span",edge.relation || "related",card,"pill");
    const other = edge.from === nodeId ? edge.to : edge.from;
    const btn = element("button",other,card);
    btn.addEventListener("click",() => {show(other);render();});
    element("small",edge.source ? "Evidence: " + edge.source + (edge.line ? ":" + edge.line : "") : "No source recorded",card);
    if (edge.confidence) element("small"," · " + edge.confidence,card);
  }
  if (links.length > 1000) element("p","Additional relationships omitted for readability.",info,"muted");
}
function render() {
  const q = query.value.toLowerCase().trim();
  const t = type.value;
  const filtered = data.nodes.filter(n => (!t || n.type === t) &&
    (!q || [n.id,n.name,n.bus,n.type].some(v => String(v || "").toLowerCase().includes(q))));
  document.getElementById("count").textContent = filtered.length + " nodes";
  nodes.replaceChildren();
  const sorted = filtered.slice().sort((a,b) => {
    const ka = a.type + ":" + (a.bus || "") + ":" + a.id;
    const kb = b.type + ":" + (b.bus || "") + ":" + b.id;
    return ka.localeCompare(kb);
  });
  let lastGroup = "";
  for (const node of sorted.slice(0,1500)) {
    const group = node.type + (node.bus ? " / " + node.bus : "");
    if (group !== lastGroup) {
      element("h2",group,nodes);
      lastGroup = group;
    }
    const label = node.type === "device-tree-node" ? node.id.slice(3) : (node.name || node.id);
    const b = element("button", label, nodes);
    if (node.type === "device-tree-node") {
      const depth = Math.max(0,(node.id.match(/\\//g) || []).length - 1);
      b.style.paddingLeft = (10 + Math.min(depth,6)*13) + "px";
    }
    b.setAttribute("aria-pressed",String(selected === node.id));
    b.addEventListener("click",()=>{show(node.id);render();});
  }
  if (filtered.length > 1500) element("p","Showing first 1,500 matches. Refine your search.",nodes,"muted");
}
document.getElementById("summary").textContent = data.nodes.length + " nodes · " +
  data.edges.length + " relations · " + data.gaps.length + " gaps · " +
  (data.target_label || "unidentified target");
const gapBox = document.getElementById("gaps");
element("p",data.gaps.length + " unavailable, unresolved or incomplete observations",gapBox);
for (const gap of data.gaps.slice(0,120)) element("pre",gap,gapBox);
if (data.gaps.length > 120) element("p","Additional gaps omitted.",gapBox,"muted");
query.addEventListener("input",render);
type.addEventListener("change",render);
render();
</script>
</body></html>
"""

def render(graph):
    if not isinstance(graph, dict) or graph.get("type") != "ubuntu-customizer/linked-hardware-graph":
        raise ValueError("Unexpected graph format")
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        raise ValueError("Graph too large for offline HTML")
    safe = {"nodes": nodes, "edges": edges, "gaps": graph.get("gaps", []),
            "target_label": graph.get("target_label")}
    payload = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    # The JSON script tag is inert, but literal </script> would close it.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return HTML.replace("__PAYLOAD__", payload)

def export(session, output):
    # Evidence hashes are revalidated before display content is derived.
    _, _, _, graph = explore.load_session(session)
    path = Path(output)
    if path.exists() or path.is_symlink() or path.suffix.lower() != ".html":
        raise ValueError("Output must be a new .html path")
    with path.open("x", encoding="utf-8") as f:
        f.write(render(graph))
    path.chmod(0o600)
    return path

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session")
    p.add_argument("--output", required=True, help="new local .html file")
    args = p.parse_args(argv)
    try:
        path = export(args.session, args.output)
        print("Offline hardware browser: " + str(path))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
