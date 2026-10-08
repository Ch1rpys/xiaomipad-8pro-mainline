#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""The empty init_boot ramdisk is fixed bytes, independent of Python's gzip module."""
import gzip
import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

TOOL = Path(__file__).with_name('build-persistent-boot.py')
# empty.cpio.gz of the 2026-10-08 release set (init_boot.img decc6d5a...), built
# with Python 3.12; Python 3.14's gzip.compress() would write OS byte 0xff.
RELEASE_EMPTY_SHA256 = 'af39e1c19af478aef7a03be98efa9d9baa228fb9f93e3842d6d7b14a1465a459'


def load():
    loader = importlib.machinery.SourceFileLoader('build_persistent_boot', str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class EmptyRamdisk(unittest.TestCase):
    def test_known_bytes_without_gzip_module(self):
        tool = load()
        with mock.patch.object(gzip, 'compress', side_effect=AssertionError('gzip.compress used')):
            data = tool.empty_ramdisk()
        self.assertEqual(hashlib.sha256(data).hexdigest(), RELEASE_EMPTY_SHA256)
        self.assertEqual(data[:10], b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\x03')

    def test_decompresses_to_the_newc_trailer(self):
        raw = gzip.decompress(load().empty_ramdisk())
        self.assertTrue(raw.startswith(b'070701'))
        self.assertIn(b'TRAILER!!!\0', raw)
        self.assertEqual(len(raw) % 4, 0)


if __name__ == '__main__':
    unittest.main()
