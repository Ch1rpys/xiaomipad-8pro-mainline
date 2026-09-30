# SPDX-License-Identifier: GPL-2.0-only
"""Read the single uncompressed newc archive emitted by our RAM builder.

This is deliberately not a general cpio implementation: no CRC variant,
concatenated overlays or hard-link data reconstruction. GNU cpio stops at a
trailer, while Linux init/initramfs.c can continue, so record boundaries must
be checked before treating verified bytes as the eventual root contents.
"""
import stat
from pathlib import PurePosixPath


def read_newc(data):
    entries = {}
    offset = 0
    while True:
        if len(data) - offset < 110 or data[offset:offset + 6] != b'070701':
            raise ValueError('Expected a complete newc header')
        if any(c not in b'0123456789abcdefABCDEF' for c in data[offset + 6:offset + 110]):
            raise ValueError('Invalid newc hexadecimal field')
        fields = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        mode, size, links, namesize = fields[1], fields[6], fields[4], fields[11]
        start = offset + 110
        name_end = start + namesize
        body = (name_end + 3) & ~3
        next_offset = (body + size + 3) & ~3
        if namesize < 1 or next_offset > len(data) or data[name_end - 1] != 0:
            raise ValueError('Truncated newc name/data')
        raw_name = data[start:name_end - 1]
        if b'\0' in raw_name:
            raise ValueError('Embedded NUL in newc name')
        name = raw_name.decode('utf-8')
        if name == 'TRAILER!!!':
            if size or any(data[next_offset:]):
                raise ValueError('Trailing or concatenated initramfs archive is not supported')
            return entries
        # Older gen_init_cpio lists used '/' for the root, yielding an empty name.
        name = name or '.'
        if (name.startswith('/') or '..' in name.split('/') or
                name != str(PurePosixPath(name)) or name in entries):
            raise ValueError(f'Unsafe or duplicate newc member: {name}')
        if stat.S_ISREG(mode) and links != 1:
            raise ValueError('Hard-linked newc files are not supported')
        entries[name] = (mode, data[body:body + size])
        offset = next_offset


def regular_file(entries, name):
    if name not in entries or not stat.S_ISREG(entries[name][0]):
        raise ValueError(f'Required regular initramfs file missing: {name}')
    for parent in PurePosixPath(name).parents:
        key = str(parent)
        if key not in entries or not stat.S_ISDIR(entries[key][0]):
            raise ValueError(f'Initramfs file parent is not a directory: {key}')
    return entries[name][1]
