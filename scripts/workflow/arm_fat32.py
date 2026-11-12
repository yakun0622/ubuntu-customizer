#!/usr/bin/env python3
"""Minimal deterministic FAT32 disk-file writer for ARM USB boot candidates.

No mounts, device nodes, subprocesses or host filesystem discovery. Operates
only on an already-created regular file and files from a validated directory.
Not a bootloader; W152D USB boot requires separate physical verification.
"""
from pathlib import Path
import importlib.util
import hashlib
import math
import re
import struct

SPEC = importlib.util.spec_from_file_location(
    'uc_workspace_arm_fat32', Path(__file__).with_name('project_workspace.py'))
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)

SECTOR = 512
RESERVED = 32
FATS = 2
FAT32_MIN_CLUSTERS = 65525
MAX_INPUTS = 2048
MAX_DEPTH = 8
MAX_BOOT_FILES_BYTES = 256 * 1024 * 1024
ALLOWED_SHORT = re.compile(r"^[A-Z0-9$%'-_@~`!(){}^#&]+$")


class Entry:
    def __init__(self, name, path=None, parent=None, short=b'', lfn=b''):
        self.name = name
        self.path = path
        self.parent = parent
        self.children = []
        self.size = 0
        self.clusters = []
        self.short = short
        self.lfn = lfn

    @property
    def directory(self):
        return self.path is None or self.path.is_dir()


def _short(name, used):
    """Generate unique FAT short names. Write LFN when spelling isn't 8.3."""
    if not name or name in ('.', '..') or '/' in name or '\\' in name:
        raise ValueError('Unsafe FAT filename')
    base, dot, ext = name.rpartition('.')
    if not dot:
        base, ext = name, ''
    if not base or name.startswith('.') or name.endswith('.'):
        raise ValueError('Unsupported FAT filename')
    upper_base, upper_ext = base.upper(), ext.upper()
    natural = (len(upper_base) <= 8 and len(upper_ext) <= 3 and
               bool(ALLOWED_SHORT.fullmatch(upper_base)) and
               (not upper_ext or bool(ALLOWED_SHORT.fullmatch(upper_ext))))
    direct = (upper_base.ljust(8) + upper_ext.ljust(3)).encode('ascii') if natural else None
    if direct and direct not in used:
        used.add(direct)
        return direct, (name != name.upper())
    # Unambiguous, deterministic ~n aliases for long names and collisions.
    filtered = ''.join(c for c in upper_base if c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    extpart = ''.join(c for c in upper_ext if c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")[:3]
    for counter in range(1, 100000):
        tail = '~' + str(counter)
        raw = (filtered[:8-len(tail)] + tail).ljust(8) + extpart.ljust(3)
        encoded = raw.encode('ascii')
        if encoded not in used:
            used.add(encoded)
            return encoded, True
    raise ValueError('Too many short filename collisions')


def _lfn_checksum(short):
    value = 0
    for byte in short:
        value = ((value & 1) << 7) + (value >> 1) + byte
        value &= 255
    return value


def _lfn_entries(name, short):
    encoded = name.encode('utf-16le')
    units = [encoded[i:i+2] for i in range(0, len(encoded), 2)]
    if len(units) > 255:
        raise ValueError('FAT filename exceeds 255 UTF-16 units')
    units.append(b'\x00\x00')
    while len(units) % 13:
        units.append(b'\xff\xff')
    checksum = _lfn_checksum(short)
    chunks = [units[n:n+13] for n in range(0, len(units), 13)]
    if len(chunks) > 20:
        raise ValueError('FAT LFN directory entry limit exceeded')
    entries = []
    for index in range(len(chunks), 0, -1):
        chunk = b''.join(chunks[index-1])
        row = bytearray(32)
        row[0] = index | (0x40 if index == len(chunks) else 0)
        row[1:11] = chunk[:10]
        row[11] = 0x0f
        row[12] = 0
        row[13] = checksum
        row[14:26] = chunk[10:22]
        row[26:28] = b'\0\0'
        row[28:32] = chunk[22:26]
        entries.append(bytes(row))
    return b''.join(entries)


def _scan(source):
    if source.is_symlink() or not source.is_dir():
        raise ValueError('FAT source must be a real directory')
    root = Entry('', source)
    count = [0]
    total = [0]

    def descend(node, depth):
        if depth > MAX_DEPTH:
            raise ValueError('FAT directory depth exceeded')
        used = set()
        for path in sorted(node.path.iterdir(), key=lambda p: p.name.casefold()):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError('FAT boot tree must contain only regular files and directories')
            count[0] += 1
            if count[0] > MAX_INPUTS:
                raise ValueError('Too many FAT boot files')
            short, need_lfn = _short(path.name, used)
            entry = Entry(path.name, path, node, short=short,
                          lfn=_lfn_entries(path.name, short) if need_lfn else b'')
            if path.is_dir():
                descend(entry, depth+1)
            else:
                entry.size = path.stat().st_size
                total[0] += entry.size
                if entry.size > 0xffffffff or total[0] > MAX_BOOT_FILES_BYTES:
                    raise ValueError('Boot data exceeds FAT32 input limit')
            node.children.append(entry)
    descend(root, 1)
    return root, count[0], total[0]


def _layout(total_sectors):
    # FAT32 requires >= 65525 data clusters. Use small clusters for small
    # boot volumes rather than creating a mislabeled FAT16 volume.
    spc = 1 if total_sectors <= 131072 else 2 if total_sectors <= 524288 else 4
    # Start from an upper bound, then shrink monotonically; a naive fixed
    # point iteration can oscillate between adjacent FAT sizes at 64 MiB.
    fat_sectors = ((total_sectors // spc + 2) * 4 + SECTOR - 1) // SECTOR
    while fat_sectors > 1:
        smaller = fat_sectors - 1
        possible_clusters = (total_sectors - RESERVED - FATS * smaller) // spc
        if (possible_clusters + 2) * 4 > smaller * SECTOR:
            break
        fat_sectors = smaller
    clusters = (total_sectors - RESERVED - FATS * fat_sectors) // spc
    if clusters < FAT32_MIN_CLUSTERS or clusters >= 0x0ffffff5:
        raise ValueError('FAT32 size outside supported cluster-count bounds')
    return spc, fat_sectors, clusters


def _short_entry(entry, cluster, *, attr):
    item = bytearray(32)
    item[:11] = entry.short
    item[11] = attr
    struct.pack_into('<H', item, 20, (cluster >> 16) & 0xffff)
    struct.pack_into('<H', item, 26, cluster & 0xffff)
    struct.pack_into('<I', item, 28, entry.size)
    return bytes(item)


def write_fat32(source_directory, image_file, *, volume_label='UCBOOT'):
    """Populate an existing zeroed FAT32 regular file; return validation data."""
    source = workspace.checked_project_dir(source_directory)
    target = workspace.checked_input(image_file)
    workspace.checked_output(target)  # never modify project source files
    if target.is_symlink() or not target.is_file() or target.stat().st_size % SECTOR:
        raise ValueError('FAT target must be a sector-aligned ordinary file')
    if not re.fullmatch('[A-Z0-9 ]{1,11}', volume_label):
        raise ValueError('Invalid volume label')
    if source.resolve() == target.resolve() or target.resolve().is_relative_to(source.resolve()):
        raise ValueError('FAT image cannot be inside source boot tree')
    root, count, payload_bytes = _scan(source)
    total_sectors = target.stat().st_size // SECTOR
    spc, fatsz, nclusters = _layout(total_sectors)
    size = SECTOR * spc
    entries = []
    def visit(node):
        entries.append(node)
        for child in node.children:
            visit(child)
    visit(root)
    # Reserve one directory entry for a terminating zero at end.
    def dir_bytes(node):
        prefix = 32 if node is root else 64  # FAT volume label in root, dot entries otherwise
        return prefix + sum(len(child.lfn)+32 for child in node.children) + 32
    next_cluster = 2
    for entry in entries:
        length = dir_bytes(entry) if entry.directory else entry.size
        required = max(1, (length + size - 1)//size) if entry.directory else (length + size - 1)//size
        entry.clusters = list(range(next_cluster, next_cluster+required))
        next_cluster += required
    if next_cluster-2 > nclusters:
        raise ValueError('Boot tree does not fit the FAT32 data area')
    fat = bytearray((nclusters+2)*4)
    struct.pack_into('<II', fat, 0, 0x0ffffff8, 0x0fffffff)
    for entry in entries:
        for index, cluster in enumerate(entry.clusters):
            following = entry.clusters[index+1] if index+1<len(entry.clusters) else 0x0fffffff
            struct.pack_into('<I', fat, 4*cluster, following)
    boot = bytearray(SECTOR)
    boot[:3] = b'\xeb\x58\x90'
    boot[3:11] = b'MSWIN4.1'
    struct.pack_into('<HBHBHHBHHHII', boot, 11,
                     SECTOR, spc, RESERVED, FATS, 0, 0, 0xf8, 0, 63, 255, 0, total_sectors)
    struct.pack_into('<IHHIHH', boot, 36, fatsz, 0, 0, 2, 1, 6)
    boot[64:66] = b'\x80\x00'
    boot[66] = 0x29
    struct.pack_into('<I', boot, 67, 0x55c0abcd)
    boot[71:82] = volume_label.ljust(11).encode('ascii')
    boot[82:90] = b'FAT32   '
    boot[510:512] = b'\x55\xaa'
    fsinfo = bytearray(SECTOR)
    struct.pack_into('<I', fsinfo, 0, 0x41615252)
    struct.pack_into('<I', fsinfo, 484, 0x61417272)
    struct.pack_into('<I', fsinfo, 488, nclusters-(next_cluster-2))
    struct.pack_into('<I', fsinfo, 492, next_cluster if next_cluster<nclusters+2 else 0xffffffff)
    struct.pack_into('<I', fsinfo, 508, 0xaa550000)
    fat_bytes = fat.ljust(fatsz*SECTOR,b'\0')
    data_start = (RESERVED+FATS*fatsz)*SECTOR
    def offset(cluster):
        return data_start+(cluster-2)*size
    def write_chain(stream, chain, source):
        for c in chain:
            stream.seek(offset(c))
            block = source.read(size)
            stream.write(block)
            if len(block)<size:
                stream.write(b'\0'*(size-len(block)))
        if source.read(1):
            raise ValueError('File grew during FAT image generation')
    with target.open('r+b') as disk:
        disk.seek(0);disk.write(boot)
        disk.seek(SECTOR);disk.write(fsinfo)
        disk.seek(6*SECTOR);disk.write(boot)
        disk.seek(7*SECTOR);disk.write(fsinfo)
        for n in range(FATS):
            disk.seek((RESERVED+n*fatsz)*SECTOR);disk.write(fat_bytes)
        for entry in entries:
            if entry.directory:
                rows = bytearray()
                if entry is root:
                    label_row = bytearray(32)
                    label_row[:11] = volume_label.ljust(11).encode('ascii')
                    label_row[11] = 0x08
                    rows += label_row
                else:
                    dot = Entry('.',short=b'.          ')
                    dotdot = Entry('..',short=b'..         ')
                    rows += _short_entry(dot,entry.clusters[0],attr=0x10)
                    parent = entry.parent
                    rows += _short_entry(dotdot,0 if parent is root else parent.clusters[0],attr=0x10)
                for child in entry.children:
                    rows += child.lfn
                    rows += _short_entry(child,child.clusters[0] if child.clusters else 0,
                                         attr=0x10 if child.directory else 0x20)
                rows += bytes(32)
                import io
                write_chain(disk, entry.clusters, io.BytesIO(rows))
            else:
                with entry.path.open('rb') as data:
                    write_chain(disk,entry.clusters,data)
    with target.open('rb') as disk:
        if disk.read(3)!=b'\xeb\x58\x90':
            raise RuntimeError('FAT boot sector corrupt')
        disk.seek(510)
        if disk.read(2)!=b'\x55\xaa':
            raise RuntimeError('FAT boot signature corrupt')
        disk.seek((RESERVED)*SECTOR+8)
        if struct.unpack('<I',disk.read(4))[0] == 0:
            raise RuntimeError('FAT root cluster missing')
    return {'filesystem':'fat32','files_and_directories':count,'file_bytes':payload_bytes,
            'clusters':nclusters,'allocated_clusters':next_cluster-2,
            'fat_sectors':fatsz,'sectors_per_cluster':spc,
            'volume_label':volume_label}
