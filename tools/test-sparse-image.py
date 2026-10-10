#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""sparse_image.py: chunk totals, the release rules, and encode-ext4 on a real small ext4."""
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sparse_image as si  # noqa: E402

B = 4096


def sparse(chunks):
    """A version 1.0 sparse image from (type, blocks, payload) rows."""
    body = b''
    for kind, blocks, payload in chunks:
        body += struct.pack('<HHII', kind, 0, blocks, 12 + len(payload)) + payload
    total = sum(blocks for kind, blocks, _ in chunks if kind != si.CRC32)
    return struct.pack('<IHHHHIIII', si.MAGIC, 1, 0, 28, 12, B, total, len(chunks), 0) + body


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


class Summary(unittest.TestCase):
    def test_totals_rules_and_expand(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / 'x.img'
            data = bytes(range(256)) * 16
            img.write_bytes(sparse([(si.RAW, 1, data), (si.FILL, 2, b'\0\0\0\0'), (si.DONT_CARE, 3, b''),
                                    (si.FILL, 1, b'\xff\xff\xff\xff'), (si.CRC32, 0, b'\0\0\0\0')]))
            row = si.summary(img)
            self.assertEqual((row['raw']['bytes'], row['fill']['bytes'], row['dont_care']['bytes']), (B, 3 * B, 3 * B))
            self.assertEqual((row['fill']['nonzero_bytes'], row['device_write_bytes'], row['expanded_bytes']),
                             (B, 4 * B, 7 * B))
            self.assertEqual(si.problems(row, 3 * B), [])
            self.assertEqual(len(si.problems(row, 3 * B - 1)), 1)
            # Free: blocks 2-5; then blocks 4-6, which leaves DONT_CARE block 3 on a used block.
            free = [(2 * B, 6 * B)]
            ext4 = si.summary(img, free)['ext4']
            self.assertEqual(ext4, {'free_bytes': 4 * B, 'dont_care_on_used_bytes': 0,
                                    'fill_on_free_bytes': B, 'raw_on_free_bytes': 0})
            ext4 = si.summary(img, [(4 * B, 7 * B)])['ext4']
            self.assertEqual((ext4['dont_care_on_used_bytes'], ext4['fill_on_free_bytes']), (B, B))
            found = si.problems(si.summary(img, [(4 * B, 7 * B)]), 0)
            self.assertEqual(len(found), 2)
            raw = Path(tmp) / 'x.raw'
            digest = si.expand(img, raw)
            expected = data + bytes(5 * B) + b'\xff' * B
            self.assertEqual(digest, hashlib.sha256(expected).hexdigest())
            self.assertEqual(raw.read_bytes(), expected)
            self.assertFalse(si.is_sparse(raw))
            self.assertEqual(si.summary(raw)['device_write_bytes'], 7 * B)


TOOLS = ('mkfs.ext4', 'dumpe2fs', 'img2simg', 'simg2img')


@unittest.skipUnless(all(shutil.which(t) for t in TOOLS), 'needs ' + ', '.join(TOOLS))
class Ext4(unittest.TestCase):
    def test_encode_writes_used_zero_blocks_and_skips_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tree = d / 'tree'
            tree.mkdir()
            (tree / 'zeros').write_bytes(bytes(64 * B))
            (tree / 'data').write_bytes(os.urandom(64 * B))
            raw = d / 'fs.ext4'
            with raw.open('wb') as f:
                f.truncate(64 << 20)
            subprocess.run(['mkfs.ext4', '-q', '-F', '-b', '4096', '-d', str(tree), str(raw)], check=True,
                           env=dict(os.environ, LC_ALL='C'))
            block, free = si.ext4_free(raw, 'dumpe2fs')
            # A deleted file's leftovers: nonzero and zero data on free blocks.
            fd = os.open(raw, os.O_RDWR)
            os.pwrite(fd, os.urandom(B), free[-1][0])
            os.pwrite(fd, bytes(B), free[-1][0] + B)
            os.close(fd)
            before = sha(raw)
            # Plain img2simg -s keeps mke2fs's holes in used blocks (inode tables) as DONT_CARE.
            subprocess.run(['img2simg', '-s', str(raw), str(d / 'plain.img')], check=True)
            self.assertGreater(si.summary(d / 'plain.img', free)['ext4']['dont_care_on_used_bytes'], 0)
            row, found = si.encode_ext4(raw, d / 'fs.img', 'dumpe2fs', 0)
            self.assertEqual(found, [])
            self.assertEqual(sha(raw), before)
            self.assertEqual(row['ext4']['dont_care_on_used_bytes'], 0)
            self.assertEqual(row['ext4']['fill_on_free_bytes'], 0)
            self.assertEqual(row['ext4']['raw_on_free_bytes'], B)
            self.assertEqual(row['holes']['free_nonzero_bytes'], B)
            self.assertGreaterEqual(row['holes']['free_zero_punched_bytes'], B)
            self.assertGreater(row['holes']['zeros_written_bytes'], 0)
            self.assertGreater(row['dont_care']['bytes'], 0)
            subprocess.run(['simg2img', str(d / 'fs.img'), str(d / 'back.ext4')], check=True)
            self.assertEqual(sha(d / 'back.ext4'), before)
            self.assertEqual(si.expand(d / 'fs.img', d / 'expanded.ext4'), before)


if __name__ == '__main__':
    unittest.main()
