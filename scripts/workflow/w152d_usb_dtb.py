#!/usr/bin/env python3
"""Patch only the three verified W152D USB-enable default states in an FDT."""
import argparse
import hashlib
import json
import struct

import project_workspace as workspace

ORIGINAL_SHA256 = "8ef504f8be18e95db9a4c442723ae10ac91a465f934aa3f5c963c58cc90e2dff"
PINS = {f"/gpio_leds/usb2_{n}_enable": 29 + n for n in (1, 2, 3)}


def patch(blob, *, extra_space=0):
    if (isinstance(extra_space, bool) or not isinstance(extra_space, int)
            or not 0 <= extra_space <= 65536 or extra_space % 4 != 0):
        raise ValueError("Invalid extra FDT space")
    if hashlib.sha256(blob).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Unexpected source DTB")
    data = bytearray(blob)
    fields = struct.unpack_from(">10I", data)
    magic, total, structure, strings, _, _, _, _, strings_size, structure_size = fields
    if magic != 0xd00dfeed or total != len(data) or structure + structure_size > total or strings + strings_size > total:
        raise ValueError("Invalid FDT header")
    names = data[strings:strings + strings_size]
    position = structure
    end = structure + structure_size
    stack = []
    found = {}
    while position + 4 <= end:
        token = struct.unpack_from(">I", data, position)[0]
        position += 4
        if token == 1:
            stop = data.index(0, position, end)
            stack.append(bytes(data[position:stop]).decode("ascii"))
            position = (stop + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, name_offset = struct.unpack_from(">II", data, position)
            position += 8
            if name_offset >= len(names) or position + size > end:
                raise ValueError("Invalid FDT property")
            name_end = names.index(0, name_offset)
            key = bytes(names[name_offset:name_end]).decode("ascii")
            path = "/" + "/".join(part for part in stack if part)
            if path in PINS and key in ("gpios", "default-state"):
                props = found.setdefault(path, {})
                if key in props:
                    raise ValueError("Duplicate USB GPIO property")
                props[key] = (position, bytes(data[position:position + size]))
            position = (position + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            break
        else:
            raise ValueError("Unknown FDT token")
    if set(found) != set(PINS):
        raise ValueError("Missing W152D USB power nodes")
    for path, pin in PINS.items():
        props = found[path]
        if props.get("gpios", (None, None))[1] != struct.pack(">III", 0x1d, pin, 0):
            raise ValueError("USB GPIO identity changed")
        offset, previous = props.get("default-state", (None, None))
        if previous != b"off\0":
            raise ValueError("USB GPIO default state changed")
        # The FDT property length is three bytes; its four-byte storage slot
        # retains one padding byte, so no later offsets need to move.
        struct.pack_into(">I", data, offset - 8, 3)
        data[offset:offset + 4] = b"on\0\0"
    if extra_space:
        # Leave aligned tail slack inside totalsize so U-Boot ft_board_setup
        # can populate chosen/memory/ethernet RMII internal-PHY properties
        # without failing fdt_setprop() with FDT_ERR_NOSPACE.
        new_total = (total + extra_space + 3) & ~3
        struct.pack_into(">I", data, 4, new_total)
        data.extend(b"\x00" * (new_total - total))
    return bytes(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--extra-space", type=int, default=0,
                        help="4-byte-aligned FDT tail slack bytes for U-Boot ft_board_setup")
    args = parser.parse_args(argv)
    source = workspace.checked_input(args.source, max_bytes=4 * 1024 * 1024)
    target = workspace.checked_output(args.output)
    if target.exists():
        raise ValueError("Output already exists")
    result = patch(source.read_bytes(), extra_space=args.extra_space)
    target.write_bytes(result)
    print(json.dumps({"file": str(target), "bytes": len(result),
                      "sha256": hashlib.sha256(result).hexdigest(),
                      "extra_space": len(result) - source.stat().st_size,
                      "changed_nodes": sorted(PINS)}))


if __name__ == "__main__":
    main()
