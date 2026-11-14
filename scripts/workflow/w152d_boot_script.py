#!/usr/bin/env python3
"""Create a fixed, experimental W152D USB script for the observed U-Boot path.

The script executes only after U-Boot has found aml_autoscript on USB FAT.
It does not write U-Boot environment or internal storage.
"""
import argparse
import hashlib
import json
import struct
import zlib

import project_workspace as workspace


SCRIPT = (b"echo W152D Ubuntu USB candidate\n"
          b"if fatload usb 0:1 0x0a000000 Image; then\n"
          b"  if fatload usb 0:1 0x01000000 w152d.dtb; then\n"
          b"    setenv bootargs console=ttyS0,921600 earlycon=aml_uart,0xfe07a000 root=LABEL=UCROOT rootwait rw init=/bin/sh\n"
          b"    booti 0x0a000000 - 0x01000000\n"
          b"  fi\n"
          b"fi\n")


def script_for_root(root, *, serial_init=False):
    if root not in ("LABEL=UCROOT", "/dev/sda2"):
        raise ValueError("Unverified W152D root device")
    if serial_init and root != "/dev/sda2":
        raise ValueError("Serial init requires the physically verified root path")
    result = SCRIPT.replace(b"root=LABEL=UCROOT", b"root=" + root.encode("ascii"))
    return result.replace(b" init=/bin/sh", b"") if serial_init else result


def legacy_script(text=SCRIPT):
    """U-Boot legacy script: 64-byte header, size table, text."""
    if not text or len(text) > 4096 or b"\x00" in text:
        raise ValueError("Invalid fixed U-Boot script")
    payload = struct.pack(">II", len(text), 0) + text
    name = b"W152D Ubuntu USB".ljust(32, b"\x00")
    fields = (0x27051956, 0, 0, len(payload), 0, 0,
              zlib.crc32(payload), 5, 22, 6, 0, name)
    header = struct.pack(">7I4B32s", *fields)
    fields = (fields[0], zlib.crc32(header), *fields[2:])
    return struct.pack(">7I4B32s", *fields) + payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", choices=("LABEL=UCROOT", "/dev/sda2"),
                        default="LABEL=UCROOT")
    parser.add_argument("--serial-init", action="store_true",
                        help="Boot the staged /sbin/init instead of the rescue shell")
    parser.add_argument("--output", default="outputs/w152d-uboot-capture-01/aml_autoscript")
    parser.add_argument("--text-output", default="outputs/w152d-uboot-capture-01/boot-script.txt")
    args = parser.parse_args()
    out = workspace.checked_output(args.output)
    text = workspace.checked_output(args.text_output)
    if out.exists() or text.exists():
        raise ValueError("Boot script artifacts already exist")
    source = script_for_root(args.root, serial_init=args.serial_init)
    text.write_bytes(source)
    blob = legacy_script(source)
    out.write_bytes(blob)
    print(json.dumps({"script": str(out), "sha256": hashlib.sha256(blob).hexdigest(),
                      "bytes": len(blob), "root": args.root,
                      "serial_init": args.serial_init,
                      "root_mount_and_shell_observed": args.root == "/dev/sda2"}))


if __name__ == "__main__":
    main()
