#!/usr/bin/env python3
"""Decode a project-local, independent-block LZ4 frame to an ARM64 Image."""
import argparse
import hashlib
import json

import project_workspace as workspace


def xxh32(data):
    mask = 0xffffffff
    p1, p2, p3, p4, p5 = 2654435761, 2246822519, 3266489917, 668265263, 374761393
    def rol(x, n):
        return ((x << n) | (x >> (32 - n))) & mask
    def step(v, word):
        return rol((v + word * p2) & mask, 13) * p1 & mask
    i = 0
    if len(data) >= 16:
        v = [(p1 + p2) & mask, p2, 0, (-p1) & mask]
        while i + 16 <= len(data):
            for j in range(4):
                v[j] = step(v[j], int.from_bytes(data[i + 4*j:i + 4*j + 4], "little"))
            i += 16
        h = sum(rol(v[j], (1, 7, 12, 18)[j]) for j in range(4)) & mask
    else:
        h = p5
    h = (h + len(data)) & mask
    while i + 4 <= len(data):
        h = rol((h + int.from_bytes(data[i:i + 4], "little") * p3) & mask, 17) * p4 & mask
        i += 4
    while i < len(data):
        h = rol((h + data[i] * p5) & mask, 11) * p1 & mask
        i += 1
    h ^= h >> 15
    h = h * p2 & mask
    h ^= h >> 13
    h = h * p3 & mask
    return h ^ (h >> 16)


def block_decode(source):
    out = bytearray()
    i = 0
    while i < len(source):
        token = source[i]
        i += 1
        literal = token >> 4
        if literal == 15:
            while True:
                n = source[i]
                i += 1
                literal += n
                if n != 255:
                    break
        if i + literal > len(source):
            raise ValueError("Truncated LZ4 literals")
        out.extend(source[i:i + literal])
        i += literal
        if i == len(source):
            break
        if i + 2 > len(source):
            raise ValueError("Truncated LZ4 offset")
        offset = int.from_bytes(source[i:i + 2], "little")
        i += 2
        if offset == 0 or offset > len(out):
            raise ValueError("Invalid LZ4 offset")
        match = (token & 15) + 4
        if token & 15 == 15:
            while True:
                n = source[i]
                i += 1
                match += n
                if n != 255:
                    break
        while match:
            chunk = out[-offset:]
            take = min(len(chunk), match)
            out.extend(chunk[:take])
            match -= take
    return bytes(out)


def decode_frame(source):
    if source[:4] != b"\x04\x22\x4d\x18":
        raise ValueError("Not a standard LZ4 frame")
    flags, descriptor = source[4:6]
    if flags & 0xC0 != 0x40 or not flags & 0x20 or flags & 0x19:
        raise ValueError("Unsupported LZ4 frame options")
    maximum = {4: 64 << 10, 5: 256 << 10, 6: 1 << 20, 7: 4 << 20}.get(descriptor >> 4)
    if maximum is None:
        raise ValueError("Invalid LZ4 block maximum")
    offset = 7
    output = bytearray()
    while True:
        if offset + 4 > len(source):
            raise ValueError("Missing LZ4 end mark")
        size = int.from_bytes(source[offset:offset + 4], "little")
        offset += 4
        if size == 0:
            break
        raw = bool(size & 0x80000000)
        size &= 0x7fffffff
        if size > maximum or offset + size > len(source):
            raise ValueError("Invalid LZ4 block size")
        block = source[offset:offset + size]
        offset += size
        output.extend(block if raw else block_decode(block))
        if len(output) > 128 << 20:
            raise ValueError("Decoded kernel exceeds limit")
    if flags & 4:
        if offset + 4 > len(source):
            raise ValueError("Missing LZ4 content checksum")
        expected = int.from_bytes(source[offset:offset + 4], "little")
        if xxh32(output) != expected:
            raise ValueError("LZ4 content checksum mismatch")
        offset += 4
    if len(source) - offset == 4:
        if int.from_bytes(source[offset:], "little") != len(output):
            raise ValueError("Android kernel length trailer mismatch")
    elif any(source[offset:]):
        raise ValueError("Unexpected trailing LZ4 data")
    image = bytes(output)
    if len(image) < 64 or image[56:60] != b"ARM\x64":
        raise ValueError("Decoded payload is not an ARM64 Image")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    source = workspace.checked_input(args.source, max_bytes=128 << 20)
    output = workspace.checked_output(args.output)
    if output.exists():
        raise ValueError("Output already exists")
    image = decode_frame(source.read_bytes())
    output.write_bytes(image)
    print(json.dumps({"file": str(output), "bytes": len(image),
                      "sha256": hashlib.sha256(image).hexdigest()}))


if __name__ == "__main__":
    main()
