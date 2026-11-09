#!/usr/bin/env python3
"""Evidence-backed DTS structural graph. No register access or physical pin claims.

Understands standard dtc-generated node/property blocks and explicit phandle
references. This is not a full dtc compiler; unsupported syntax yields gaps.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("uc_dossier", Path(__file__).with_name("dossier.py"))
dossier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dossier)

REF_PROPS = {"clocks", "resets", "power-domains", "iommus", "phys",
             "phy-handle", "interrupt-parent", "interrupts-extended",
             "dmas", "pwms", "gpios", "cs-gpios", "enable-gpios",
             "reset-gpios", "vdd-supply"}
REF_PATTERN = re.compile(r"&([A-Za-z_][A-Za-z0-9_]*)|\b0x([0-9a-fA-F]+)\b")
NODE_HEADER = re.compile(r"^(?:(?P<label>[A-Za-z_][\w-]*):\s*)?(?P<name>[/\w,.*+@-]+)$")
PROPERTY = re.compile(r"^(?P<name>[\w,+#.-]+)(?:\s*=\s*(?P<value>.*))?$", re.S)

def strip_comments(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)

def tokenize(text):
    # dtc output commonly emits /dts-v1/; and /memreserve/ ...;
    # preserve delimiters outside strings and <cell groups>.
    tokens, buf, quote, escaped = [], [], False, False
    for char in strip_comments(text):
        if quote:
            buf.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            continue
        if char == '"':
            quote = True
            buf.append(char)
        elif char in "{};":
            if "".join(buf).strip():
                tokens.append(("text", "".join(buf).strip()))
            buf = []
            tokens.append((char, char))
        else:
            buf.append(char)
    if "".join(buf).strip():
        tokens.append(("text", "".join(buf).strip()))
    return tokens

def parse_dts(text, source):
    nodes, edges, gaps = {}, [], []
    stack, labels, handles, pending = [], {}, {}, None
    tokens = tokenize(text)
    for kind, val in tokens:
        if kind == "text":
            pending = val
        elif kind == "{":
            header = (pending or "").strip()
            pending = None
            match = NODE_HEADER.fullmatch(header)
            if not match:
                gaps.append({"kind": "unparsed_node", "expression": header[:100]})
                stack.append(None)
                continue
            name = match.group("name")
            parent = next((v for v in reversed(stack) if v is not None), "")
            path = "/" if name == "/" and not parent else (parent.rstrip("/") + "/" + name)
            if parent and parent != path:
                edges.append({"from": parent, "to": path, "relation": "contains", "source": source})
            stack.append(path)
            nodes[path] = {"id": path, "name": name, "properties": {}, "source": source}
            if match.group("label"):
                labels[match.group("label")] = path
        elif kind == "}":
            if stack:
                stack.pop()
            else:
                gaps.append({"kind": "unmatched_close"})
            pending = None
        elif kind == ";":
            if pending and stack and stack[-1] is not None:
                parsed = PROPERTY.fullmatch(pending)
                if parsed:
                    key, value = parsed.group("name"), parsed.group("value")
                    node = nodes[stack[-1]]
                    if key in ("compatible", "status", "device_type", "reg", "pinctrl-names",
                               "phy-mode", "phandle", "linux,phandle") or key.startswith("pinctrl-"):
                        node["properties"][key] = value if value is not None else True
                    if key in ("phandle", "linux,phandle") and value is not None:
                        matches = re.findall(r"0x([\da-fA-F]+)", value)
                        if len(matches) == 1:
                            handles[int(matches[0], 16)] = stack[-1]
                    if value is not None and (key in REF_PROPS or key.startswith("pinctrl-") or key.endswith("-supply")):
                        node.setdefault("_references", []).append((key, value))
                else:
                    gaps.append({"kind": "unparsed_property", "node": stack[-1], "expression": pending[:100]})
            pending = None
    if stack:
        gaps.append({"kind": "unterminated_nodes", "count": len(stack)})
    for path, node in nodes.items():
        for prop, raw in node.pop("_references", []):
            # Only resolve explicit &labels, or a uniquely resolvable first cell.
            named = re.findall(r"&([A-Za-z_][\w-]*)", raw)
            for label in named:
                if label in labels:
                    edges.append({"from": path, "to": labels[label],
                                  "relation": prop, "source": source, "confidence": "explicit_label"})
                else:
                    gaps.append({"kind": "unresolved_label", "node": path, "property": prop, "label": label})
            if not named:
                # Numeric cells are ambiguous: for properties with specifier arguments,
                # only first cell is a candidate; never guess subsequent cell boundaries.
                match = re.search(r"<\s*0x([\da-fA-F]+)", raw)
                if match:
                    number = int(match.group(1), 16)
                    if number in handles:
                        edges.append({"from": path, "to": handles[number],
                                      "relation": prop, "source": source,
                                      "confidence": "candidate_numeric_phandle"})
                    else:
                        gaps.append({"kind": "unresolved_numeric_reference", "node": path, "property": prop})
    return {"nodes": list(nodes.values()), "edges": edges, "gaps": gaps}

def build(session):
    manifest, entries = dossier.verify_session(session)
    match = [(item, raw) for item, raw in entries if item.get("category") == "pins" and item.get("name") == "dt-source"]
    if not match:
        return {"schema_version": 1, "type": "ubuntu-customizer/device-tree-graph",
                "nodes": [], "edges": [], "gaps": [{"kind": "not_collected", "probe": "pins/dt-source"}],
                "limitations": "No DTS source available. No physical pin mapping inferred."}
    item, source = match[0]
    if item.get("status") != "ok" or "dtc or device tree unavailable" in source:
        return {"schema_version": 1, "type": "ubuntu-customizer/device-tree-graph",
                "nodes": [], "edges": [], "gaps": [{"kind": "unavailable", "probe": "pins/dt-source"}],
                "limitations": "No verified DTS source available."}
    result = parse_dts(source, item["file"])
    return {"schema_version": 1, "type": "ubuntu-customizer/device-tree-graph",
            **result, "limitations": "DTS references express software configuration, not observed pin voltage, physical routing or functional peripheral state."}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session")
    p.add_argument("--output")
    args = p.parse_args(argv)
    try:
        output = Path(args.output) if args.output else Path(args.session) / "device-tree.json"
        if output.exists() or output.is_symlink():
            raise ValueError("Refusing to overwrite existing output")
        result = build(args.session)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        output.chmod(0o600)
        print(f"Device tree graph: {output}; nodes={len(result['nodes'])}; edges={len(result['edges'])}; gaps={len(result['gaps'])}")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
