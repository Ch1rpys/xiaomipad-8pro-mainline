#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The release checks: FDT property names, identifier patterns and the chunked byte scan."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

TOOL = Path(__file__).with_name('build-release.py')


def load():
    loader = importlib.machinery.SourceFileLoader('build_release', str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def fdt(properties):
    """A one-node devicetree with the given property names (4-byte values)."""
    strings = b''
    body = struct.pack('>I', 1) + b'\0\0\0\0'  # FDT_BEGIN_NODE "" (root)
    for name in properties:
        body += struct.pack('>III', 3, 4, len(strings)) + b'\0\0\0\1'
        strings += name.encode() + b'\0'
    body += struct.pack('>II', 2, 9)
    off_struct = 40 + 16
    header = struct.pack('>10I', 0xd00dfeed, off_struct + len(body) + len(strings), off_struct,
                         off_struct + len(body), 40, 17, 16, 0, len(strings), len(body))
    return header + b'\0' * 16 + body + strings


class Release(unittest.TestCase):
    def setUp(self):
        self.tool = load()

    def test_fdt_property_names(self):
        names = self.tool.fdt_property_names(fdt(['compatible', 'local-mac-address']))
        self.assertEqual(names, {'compatible', 'local-mac-address'})
        with self.assertRaises(ValueError):
            self.tool.fdt_property_names(b'\0' * 64)

    def test_identity_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / 'bt').write_text('02:11:22:33:44:5A\n')
            patterns = self.tool.identity_patterns(d / 'bt')
            for p in (b'02:11:22:33:44:5a', b'02:11:22:33:44:5A', b'5a:44:33:22:11:02', b'02112233445a',
                      bytes.fromhex('02112233445a'), bytes.fromhex('5a4433221102')):
                self.assertIn(p, patterns)
            (d / 'wlan').write_text('wlan0=0211223344ab\n')
            self.assertIn(bytes.fromhex('0211223344ab'), self.tool.identity_patterns(d / 'wlan'))
            (d / 'profile.json').write_text(json.dumps({'serial': 'abc1234', 'boot': {}}))
            self.assertEqual(self.tool.identity_patterns(d / 'profile.json'), {b'abc1234', b'ABC1234'})
            (d / 'other').write_text('not an identifier')
            with self.assertRaises(ValueError):
                self.tool.identity_patterns(d / 'other')

    def test_scan_finds_a_pattern_across_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'blob'
            f.write_bytes(b'x' * 1000 + b'abc1234' + b'y' * 1000)
            for chunk in (1003, 1004, 1006, 4096):
                self.assertTrue(self.tool.scan(f, {b'abc1234'}, chunk=chunk), chunk)
            self.assertFalse(self.tool.scan(f, {b'abc1235'}, chunk=1003))


if __name__ == '__main__':
    unittest.main()
