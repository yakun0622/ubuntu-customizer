#!/usr/bin/env python3
"""Summarize project-local FDT nodes/properties relevant to W152D USB power."""
import argparse
import json
import struct

import project_workspace as workspace


def summary(blob):
    data = workspace.checked_input(blob, max_bytes=4 * 1024 * 1024).read_bytes()
    if len(data) < 40:
        raise ValueError("Short FDT")
    magic, total, structure, strings, _, _, _, _, strings_size, structure_size = struct.unpack_from(">10I", data)
    if magic != 0xd00dfeed or total > len(data) or structure + structure_size > total or strings + strings_size > total:
        raise ValueError("Invalid FDT bounds")
    names = data[strings:strings + strings_size]
    end = structure + structure_size
    position = structure
    stack = []
    nodes = {}
    while position + 4 <= end:
        token = struct.unpack_from(">I", data, position)[0]
        position += 4
        if token == 1:
            stop = data.index(0, position, end)
            name = data[position:stop].decode("ascii", "replace")
            stack.append(name)
            position = (stop + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, name_offset = struct.unpack_from(">II", data, position)
            position += 8
            if name_offset >= len(names) or position + length > end:
                raise ValueError("FDT property out of bounds")
            name_end = names.index(0, name_offset)
            key = names[name_offset:name_end].decode("ascii", "replace")
            value = data[position:position + length]
            position = (position + length + 3) & ~3
            path = "/" + "/".join(x for x in stack if x)
            relevant = any(word in (path + "/" + key).lower() for word in
                           ("usb", "gpio", "vbus", "regulator", "power", "reset", "phy"))
            if relevant:
                if value and all(x == 0 or 32 <= x < 127 for x in value):
                    rendered = value.rstrip(b"\0").replace(b"\0", b"|").decode("ascii", "replace")
                else:
                    rendered = value[:64].hex() + ("..." if len(value) > 64 else "")
                nodes.setdefault(path, {})[key] = rendered
        elif token == 4:
            continue
        elif token == 9:
            break
        else:
            raise ValueError("Unknown FDT token")
    return nodes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb")
    parser.add_argument("report")
    args = parser.parse_args()
    out = workspace.checked_output(args.report)
    if out.exists():
        raise ValueError("Report already exists")
    result = summary(args.dtb)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"report": str(out), "relevant_nodes": len(result)}))
