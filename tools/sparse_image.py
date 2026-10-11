#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Android sparse images: what Fastboot writes, and ext4 images that write only used blocks.

Fastboot writes every RAW and FILL block of a sparse image.  The piano
bootloader answers OKAY once the data has arrived and then commits FILL at
about 30 MB/s in the background, holding off every later command.  DONT_CARE
blocks are not written: the partition keeps whatever it held before.

summary   chunk totals of each image (a non-sparse image is written in full)
          and the device write bytes; --max-fill-mib fails above a FILL limit,
          --ext4-raw checks DONT_CARE against the ext4 block bitmap.
encode-ext4
          make the holes of a raw ext4 file exactly its zero free blocks,
          encode img2simg -s-compatible bytes and check the result.  Allocated
          blocks stay written even when zero: ext4 trusts its zeroed inode
          tables (ITABLE_ZEROED) and replays journal blocks whose sequence and
          checksum match, so neither may keep stale content from the partition.
          The raw file's bytes do not change.
expand    a sparse image to a raw file with zero blocks as holes, and its sha256.
"""
import argparse
import bisect
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

MAGIC = 0xed26ff3a
RAW, FILL, DONT_CARE, CRC32 = 0xcac1, 0xcac2, 0xcac3, 0xcac4
NAMES = {RAW: 'raw', FILL: 'fill', DONT_CARE: 'dont_care', CRC32: 'crc32'}
DEFAULT_MAX_FILL_MIB = 64
STEP = 8 << 20


def is_sparse(path):
    with Path(path).open('rb') as f:
        head = f.read(4)
    return len(head) == 4 and struct.unpack('<I', head)[0] == MAGIC


def chunks(path):
    """Header and (type, first output byte, bytes, fill word, data offset) of each chunk."""
    with Path(path).open('rb') as f:
        magic, major, _, file_hdr, chunk_hdr, block, blocks, count, _ = struct.unpack('<IHHHHIIII', f.read(28))
        if magic != MAGIC or major != 1:
            raise ValueError(f'{path}: not a version 1 Android sparse image')
        header = {'block_size': block, 'blocks': blocks, 'chunks': count}
        rows, pos, offset = [], file_hdr, 0
        for _ in range(count):
            f.seek(pos)
            kind, _, size, total = struct.unpack('<HHII', f.read(12))
            if kind not in NAMES:
                raise ValueError(f'{path}: unknown chunk type {kind:#x} at {pos}')
            f.seek(pos + chunk_hdr)
            fill = struct.unpack('<I', f.read(4))[0] if kind == FILL else None
            length = 0 if kind == CRC32 else size * block
            rows.append((kind, offset, length, fill, pos + chunk_hdr))
            offset += length
            pos += total
        if offset != blocks * block:
            raise ValueError(f'{path}: chunks cover {offset} bytes, header says {blocks * block}')
    return header, rows


def overlap(start, end, ranges):
    """Bytes of [start, end) inside the sorted, disjoint ranges."""
    total, i = 0, max(bisect.bisect_right(ranges, (start,)) - 1, 0)
    while i < len(ranges) and ranges[i][0] < end:
        a, b = ranges[i]
        if b > start:
            total += min(b, end) - max(a, start)
        i += 1
    return total


def summary(path, free=None):
    """What Fastboot writes for one image; with free (ext4 free byte ranges) also where it lands."""
    path = Path(path)
    if not is_sparse(path):
        size = path.stat().st_size
        return {'file': path.name, 'sparse': False, 'file_bytes': size, 'expanded_bytes': size,
                'device_write_bytes': size}
    header, rows = chunks(path)
    out = {'file': path.name, 'sparse': True, 'file_bytes': path.stat().st_size, 'block_size': header['block_size'],
           'expanded_bytes': header['blocks'] * header['block_size']}
    for kind, name in NAMES.items():
        out[name] = {'chunks': sum(1 for r in rows if r[0] == kind), 'bytes': sum(r[2] for r in rows if r[0] == kind)}
    out['fill']['nonzero_bytes'] = sum(r[2] for r in rows if r[0] == FILL and r[3])
    out['device_write_bytes'] = out['raw']['bytes'] + out['fill']['bytes']
    if free is not None:
        out['ext4'] = {
            'free_bytes': sum(b - a for a, b in free),
            'dont_care_on_used_bytes': sum(r[2] - overlap(r[1], r[1] + r[2], free) for r in rows if r[0] == DONT_CARE),
            'fill_on_free_bytes': sum(overlap(r[1], r[1] + r[2], free) for r in rows if r[0] == FILL),
            'raw_on_free_bytes': sum(overlap(r[1], r[1] + r[2], free) for r in rows if r[0] == RAW),
        }
    return out


def problems(row, max_fill):
    """Release rules: no DONT_CARE on used ext4 blocks; FILL (on free blocks when known) within the limit."""
    found = []
    ext4 = row.get('ext4')
    if ext4 and ext4['dont_care_on_used_bytes']:
        found.append(f'{row["file"]}: {ext4["dont_care_on_used_bytes"]} bytes of used ext4 blocks are DONT_CARE')
    if row['sparse'] and max_fill is not None:
        fill = ext4['fill_on_free_bytes'] if ext4 else row['fill']['bytes']
        what = 'FILL on free ext4 blocks' if ext4 else 'FILL'
        if fill > max_fill:
            found.append(f'{row["file"]}: {fill} bytes of {what} exceed the limit of {max_fill} '
                         '(img2simg without -s, or a raw file without holes)')
    return found


def ext4_free(raw, dumpe2fs):
    """Free byte ranges of an ext4 file from its block bitmaps; bytes past the file system count as free."""
    text = subprocess.run([str(dumpe2fs), str(raw)], capture_output=True, text=True, check=True,
                          env=dict(os.environ, LC_ALL='C')).stdout
    block = int(re.search(r'^Block size:\s+(\d+)$', text, re.M)[1])
    count = int(re.search(r'^Block count:\s+(\d+)$', text, re.M)[1])
    ranges = []
    for line in re.findall(r'^[ \t]+Free blocks: ?(.*)$', text, re.M):
        for part in filter(None, (p.strip() for p in line.split(','))):
            a, _, b = part.partition('-')
            ranges.append((int(a) * block, (int(b or a) + 1) * block))
    size = Path(raw).stat().st_size
    if size > count * block:
        ranges.append((count * block, size))
    ranges.sort()
    merged = []
    for a, b in ranges:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return block, merged


def data_extents(fd, start, end):
    """Data (non-hole) byte ranges of [start, end)."""
    pos = start
    while pos < end:
        try:
            data = os.lseek(fd, pos, os.SEEK_DATA)
        except OSError:
            return
        if data >= end:
            return
        hole = min(os.lseek(fd, data, os.SEEK_HOLE), end)
        yield data, hole
        pos = hole


LIBC = ctypes.CDLL(None, use_errno=True)
LIBC.fallocate.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_int64, ctypes.c_int64)


def punch(fd, offset, length):
    if LIBC.fallocate(fd, 0x03, offset, length):  # FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE
        raise OSError(ctypes.get_errno(), 'fallocate punch hole failed')


def match_holes(raw, block, free):
    """Holes := zero free blocks.  Writes zeros into holes of used blocks and punches zero free blocks.

    SEEK_DATA reports an unwritten extent (mke2fs zeroes with FALLOC_FL_ZERO_RANGE) as a hole only
    while none of its pages is cached, so the page cache is dropped first and every unwritten extent
    is either written (used) or punched (free): img2simg then sees the same holes whatever it caches."""
    size = Path(raw).stat().st_size
    used, pos = [], 0
    for a, b in free:
        if a > pos:
            used.append((pos, a))
        pos = b
    if pos < size:
        used.append((pos, size))
    stats = {'zeros_written_bytes': 0, 'free_zero_punched_bytes': 0, 'free_nonzero_bytes': 0}
    fd = os.open(raw, os.O_RDWR)
    try:
        os.fsync(fd)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        zero = bytes(STEP)
        for a, b in used:
            pos = a
            for d, h in list(data_extents(fd, a, b)) + [(b, b)]:
                while pos < d:
                    n = min(STEP, d - pos)
                    os.pwrite(fd, zero[:n], pos)
                    stats['zeros_written_bytes'] += n
                    pos += n
                pos = h
        free_runs = re.compile(rb'(?:\x00{%d})+|(?:(?!\x00{%d}).{%d})+' % (block, block, block), re.S)
        for a, b in free:
            pos = a
            for d, h in list(data_extents(fd, a, b)) + [(b, b)]:
                if pos < d:
                    punch(fd, pos, d - pos)
                pos = h
            for d, h in list(data_extents(fd, a, b)):
                d, h = d // block * block, -(-h // block) * block
                run = None
                for pos in range(d, h, STEP):
                    buf = os.pread(fd, min(STEP, h - pos), pos)
                    for match in free_runs.finditer(buf):
                        start, end = pos + match.start(), pos + match.end()
                        if not any(buf[match.start():match.start() + block]):
                            run = run if run is not None else start
                            continue
                        stats['free_nonzero_bytes'] += end - start
                        if run is not None:
                            punch(fd, run, start - run)
                            stats['free_zero_punched_bytes'] += start - run
                            run = None
                if run is not None:
                    punch(fd, run, h - run)
                    stats['free_zero_punched_bytes'] += h - run
        os.fsync(fd)
    finally:
        os.close(fd)
    return stats


def write_sparse(raw, output):
    """img2simg -s's 4096-byte RAW/FILL/DONT_CARE bytes, in one 8 MiB pass.

    The regex engine groups whole blocks in C; Python visits runs, not each
    block. Adjacent runs merge across reads. Chunk lengths and the file header
    are filled in after streaming the payload, without rereading the source.
    """
    block = 4096  # img2simg's default, independent of the ext4 block size
    words = block // 4
    runs = re.compile(
        rb'(?P<fill>.{4})(?P=fill){%d}(?:(?P=fill){%d})*'
        rb'|(?:(?!(.{4})\2{%d}).{%d})+' % (words - 1, words, words - 1, block), re.S)
    with Path(raw).open('rb') as src, Path(output).open('wb', buffering=0) as dst:
        fd, outfd = src.fileno(), dst.fileno()
        size = os.fstat(fd).st_size
        if size % block:
            raise ValueError('ext4 image size must be a multiple of 4096')
        current, count = None, 0

        def write(*buffers):
            views = [memoryview(buf) for buf in buffers if len(buf)]
            while views:
                n = os.writev(outfd, views)
                if not n:
                    raise OSError('short write of sparse image')
                while views and n >= len(views[0]):
                    n -= len(views.pop(0))
                if views:
                    views[0] = views[0][n:]

        def finish_chunk():
            if current is not None:
                kind, length, _, header_offset = current
                payload = length if kind == RAW else 4 if kind == FILL else 0
                header = struct.pack('<HHII', kind, 0, length // block, 12 + payload)
                if os.pwrite(outfd, header, header_offset) != len(header):
                    raise OSError('short write of sparse chunk header')

        def add(kind, length, fill=None, payload=None):
            nonlocal current, count
            # libsparse sparse_file_write: MAX_BACKED_BLOCK_SIZE (RAW and FILL).
            # DONT_CARE is a gap, not a backed block.
            limit = ((1 << 32) - 1) * block if kind == DONT_CARE else 64 << 20
            while length:
                if current is None or current[0] != kind or current[2] != fill or current[1] == limit:
                    finish_chunk()
                    current = [kind, 0, fill, dst.tell()]
                    write(bytes(12), fill or b'')
                    count += 1
                n = min(length, limit - current[1])
                if kind == RAW:
                    write(payload[:n])
                    payload = payload[n:]
                current[1] += n
                length -= n

        write(bytes(28))
        pos = 0
        for a, b in data_extents(fd, 0, size):
            a, b = a // block * block, min(size, -(-b // block) * block)
            add(DONT_CARE, a - pos)
            for offset in range(a, b, STEP):
                buf = os.pread(fd, min(STEP, b - offset), offset)
                if len(buf) != min(STEP, b - offset):
                    raise OSError('short read of ext4 data extent')
                view = memoryview(buf)
                for match in runs.finditer(buf):
                    fill = match.group('fill')
                    add(FILL if fill is not None else RAW, match.end() - match.start(),
                        fill, view[match.start():match.end()] if fill is None else None)
            pos = b
        add(DONT_CARE, size - pos)
        finish_chunk()
        dst.seek(0)
        write(struct.pack('<IHHHHIIII', MAGIC, 1, 0, 28, 12, block, size // block, count, 0))


def encode_ext4(raw, output, dumpe2fs, max_fill):
    block, free = ext4_free(raw, dumpe2fs)
    stats = match_holes(raw, block, free)
    write_sparse(raw, output)
    row = summary(output, free)
    row['holes'] = stats
    return row, problems(row, max_fill)


def expand(image, raw):
    """Write the image to a new raw file, zero FILL and DONT_CARE as holes; return its sha256."""
    header, rows = chunks(image)
    digest, zero = hashlib.sha256(), bytes(STEP)
    with Path(image).open('rb') as src, Path(raw).open('xb') as dst:
        for kind, offset, length, fill, data in rows:
            if kind == RAW:
                src.seek(data)
                dst.seek(offset)
                for pos in range(0, length, STEP):
                    buf = src.read(min(STEP, length - pos))
                    dst.write(buf)
                    digest.update(buf)
            elif kind == FILL and fill:
                buf = struct.pack('<I', fill) * (STEP // 4)
                dst.seek(offset)
                for pos in range(0, length, STEP):
                    dst.write(buf[:min(STEP, length - pos)])
                    digest.update(buf[:min(STEP, length - pos)])
            elif kind != CRC32:
                for pos in range(0, length, STEP):
                    digest.update(zero[:min(STEP, length - pos)])
        dst.truncate(header['blocks'] * header['block_size'])
    return digest.hexdigest()


def mib(value):
    return round(value / (1 << 20), 1)


def describe(row):
    line = f'{row["file"]}: device writes {mib(row["device_write_bytes"])} MiB of {mib(row["expanded_bytes"])} MiB'
    if row['sparse']:
        line += (f' (RAW {mib(row["raw"]["bytes"])}, FILL {mib(row["fill"]["bytes"])}, '
                 f'DONT_CARE {mib(row["dont_care"]["bytes"])} MiB)')
    return line


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='command', required=True)
    s = sub.add_parser('summary', help='What Fastboot writes for each image')
    s.add_argument('images', type=Path, nargs='+')
    s.add_argument('--max-fill-mib', type=int, help='Fail above this much FILL (on free blocks with --ext4-raw)')
    s.add_argument('--ext4-raw', type=Path, help='The raw ext4 the (single) image encodes: check DONT_CARE '
                                                 'against its block bitmap')
    s.add_argument('--dumpe2fs', type=Path, default=Path('dumpe2fs'))
    s.add_argument('--json', action='store_true')
    e = sub.add_parser('encode-ext4', help='Sparse image of a raw ext4 with only used blocks written')
    e.add_argument('raw', type=Path)
    e.add_argument('output', type=Path)
    e.add_argument('--dumpe2fs', type=Path, default=Path('dumpe2fs'))
    e.add_argument('--max-fill-mib', type=int, default=DEFAULT_MAX_FILL_MIB, help='FILL limit on free blocks')
    e.add_argument('--allow-fill', action='store_true', help='Report FILL above the limit without failing')
    e.add_argument('--json', action='store_true')
    x = sub.add_parser('expand', help='Sparse image to a raw file with holes, and its sha256')
    x.add_argument('image', type=Path)
    x.add_argument('raw', type=Path)
    a = ap.parse_args()
    if a.command == 'expand':
        print(json.dumps({'image': str(a.image), 'raw': str(a.raw), 'sha256': expand(a.image, a.raw)}, indent=2))
        return
    if a.command == 'encode-ext4':
        row, found = encode_ext4(a.raw, a.output, a.dumpe2fs, None if a.allow_fill else a.max_fill_mib << 20)
        rows = [row]
    else:
        if a.ext4_raw and len(a.images) != 1:
            ap.error('--ext4-raw checks one image')
        free = ext4_free(a.ext4_raw, a.dumpe2fs)[1] if a.ext4_raw else None
        rows = [summary(p, free) for p in a.images]
        limit = None if a.max_fill_mib is None else a.max_fill_mib << 20
        found = [f for r in rows for f in problems(r, limit)]
    print(json.dumps(rows, indent=2) if a.json else '\n'.join(describe(r) for r in rows))
    for f in found:
        print('FAIL ' + f, file=sys.stderr)
    sys.exit(1 if found else 0)


if __name__ == '__main__':
    main()
