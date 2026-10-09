#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""The empty init_boot ramdisk is fixed bytes, independent of Python's gzip module; the root and
serial options of unit-independent sets.  The image test needs AOSP mkbootimg in tools/local
(fetch-aosp-mkbootimg.sh) and AVBTOOL=<avbtool.py>."""
import gzip
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOL = Path(__file__).with_name('build-persistent-boot.py')
MKBOOTIMG = Path(__file__).with_name('local') / 'aosp-mkbootimg/mkbootimg.py'
AVBTOOL = os.environ.get('AVBTOOL')
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


def fake_inputs(d, serial=None):
    (d / 'Image').write_bytes(b'\0' * 4096 + b'Linux version 7.2.6-piano9 (test@host) (gcc)\0' + b'\0' * 4096)
    (d / 'dtb').write_bytes(b'\xd0\x0d\xfe\xed' + b'\0' * 60)
    (d / 'initrd').write_bytes(b'070701' + b'\0' * 1024)
    image = {'header_version': 4, 'capacity': 4 << 20, 'rollback_index': 0, 'avb_properties': {}}
    profile = {'boot': dict(image, avb_properties={'com.android.build.boot.os_version': '15',
                                                   'com.android.build.boot.security_patch': '2026-02-01'}),
               'init_boot': dict(image), 'vendor_boot': dict(image, page_size=4096, kernel_addr=0x8000,
                                                             ramdisk_addr=0x1000000, tags_addr=0x100,
                                                             dtb_addr=0x1f00000)}
    if serial:
        profile['serial'] = serial
    (d / 'profile.json').write_text(json.dumps(profile))
    subprocess.run(['openssl', 'genrsa', '-out', str(d / 'key.pem'), '4096'], check=True, capture_output=True)


def build(d, *options, output='out'):
    return subprocess.run([sys.executable, str(TOOL), '--kernel', str(d / 'Image'), '--dtb', str(d / 'dtb'),
                           '--initrd', str(d / 'initrd'), '--profile', str(d / 'profile.json'),
                           '--mkbootimg', str(MKBOOTIMG), '--avbtool', str(AVBTOOL), '--key', str(d / 'key.pem'),
                           '--output', str(d / output), *options], capture_output=True, text=True)


class RootAndSerial(unittest.TestCase):
    def test_root_options_are_exclusive_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            fake_inputs(d)
            both = build(d, '--root-partlabel', 'linux_rootfs',
                         '--root-partuuid', '00000000-0000-0000-0000-000000000001')
            self.assertIn('not allowed with argument', both.stderr)
            bad = build(d, '--root-partlabel', 'linux rootfs', '--no-serial')
            self.assertIn('GPT partition name', bad.stderr)
            self.assertFalse((d / 'out').exists())

    @unittest.skipUnless(MKBOOTIMG.is_file() and AVBTOOL, 'needs tools/local/aosp-mkbootimg and AVBTOOL')
    def test_unit_independent_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            fake_inputs(d)
            refused = build(d, '--root-partlabel', 'linux_rootfs')
            self.assertIn('Profile requires the verified device serial', refused.stderr)
            done = build(d, '--root-partlabel', 'linux_rootfs', '--no-serial', output='set')
            self.assertEqual(done.returncode, 0, done.stderr)
            manifest = json.loads((d / 'set/manifest.json').read_text())
            self.assertTrue(manifest['cmdline'].startswith('root=PARTLABEL=linux_rootfs rootfstype=ext4 '))
            self.assertNotIn('androidboot.serialno', manifest['cmdline'])
            self.assertEqual((manifest['root'], manifest['root_partuuid'], manifest['serial_in_cmdline']),
                             ('PARTLABEL=linux_rootfs', None, False))
            header = (d / 'set/boot.img').read_bytes()[:4096]
            self.assertIn(manifest['cmdline'].encode(), header)

    @unittest.skipUnless(MKBOOTIMG.is_file() and AVBTOOL, 'needs tools/local/aosp-mkbootimg and AVBTOOL')
    def test_unit_set_keeps_partuuid_and_serial(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            fake_inputs(d, serial='abc1234')
            done = build(d, '--root-partuuid', '00000000-0000-0000-0000-000000000001')
            self.assertEqual(done.returncode, 0, done.stderr)
            manifest = json.loads((d / 'out/manifest.json').read_text())
            self.assertTrue(manifest['cmdline'].startswith(
                'root=PARTUUID=00000000-0000-0000-0000-000000000001 '))
            self.assertTrue(manifest['cmdline'].endswith(' androidboot.serialno=abc1234'))
            self.assertTrue(manifest['serial_in_cmdline'])


if __name__ == '__main__':
    unittest.main()
