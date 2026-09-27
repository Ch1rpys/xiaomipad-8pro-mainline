#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private firmware injection in build-initramfs.sh and its build-boot.py record.

Needs the pinned ARM64 BusyBox and gen_init_cpio (see docs/build.zh-CN.md):
BUSYBOX=... GEN_INIT_CPIO=... python3 tools/test-build-initramfs.py
Uses a synthetic fixture only; no firmware bytes are read.
"""
import gzip
import hashlib
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
BUSYBOX, GEN_INIT_CPIO = os.environ.get('BUSYBOX'), os.environ.get('GEN_INIT_CPIO')
FIXTURE = {'qcom/gen80000_sqe.fw': b'sqe' * 100, 'qcom/sm8750/vendor/board/zap.mbn': b'\x7fELF zap',
           'top.bin': b''}


def newc(data):
    """Parse a newc cpio archive into {name: (mode, bytes)}."""
    entries, pos = {}, 0
    while True:
        assert data[pos:pos + 6] == b'070701'
        field = lambda i: int(data[pos + 6 + 8 * i:pos + 14 + 8 * i], 16)
        mode, size, namesize = field(1), field(6), field(11)
        name_start = pos + 110
        name = data[name_start:name_start + namesize - 1].decode()
        body = (name_start + namesize + 3) & ~3
        if name == 'TRAILER!!!':
            return entries
        entries[name] = (mode, data[body:body + size])
        pos = (body + size + 3) & ~3


def build(out, firmware=None):
    env = dict(os.environ, BUSYBOX=BUSYBOX, GEN_INIT_CPIO=GEN_INIT_CPIO, OUT_DIR=str(out))
    env.pop('FIRMWARE_DIR', None)
    if firmware is not None:
        env['FIRMWARE_DIR'] = str(firmware)
    return subprocess.run(['bash', str(TOOLS / 'build-initramfs.sh')], env=env, capture_output=True, text=True)


def fixture(root, files):
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    return root


class GpuPairingTest(unittest.TestCase):
    def test_gpu_dtb_needs_msm_and_firmware(self):
        boot = runpy.run_path(str(TOOLS / 'build-boot.py'))
        check, gpu = boot['gpu_errors'], boot['GPU_DTB']
        row = [{'path': 'qcom/x', 'size': 1, 'sha256': '0' * 64}]
        self.assertEqual(check(['CONFIG_DRM_MSM=y'], gpu, row), [])
        self.assertEqual(len(check(['CONFIG_DRM_MSM=m'], gpu, [])), 2)
        self.assertEqual(check([], boot['DEFAULT_DTB'], []), [])


@unittest.skipUnless(BUSYBOX and GEN_INIT_CPIO, 'set BUSYBOX and GEN_INIT_CPIO')
class FirmwareInjectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def archive(self, out):
        return gzip.decompress((out / 'initramfs.cpio.gz').read_bytes())

    def test_files_manifest_and_identity(self):
        plain = build(self.tmp / 'plain')
        self.assertEqual(plain.returncode, 0, plain.stderr)
        fw = fixture(self.tmp / 'fw', FIXTURE)
        with_fw = build(self.tmp / 'with', fw)
        self.assertEqual(with_fw.returncode, 0, with_fw.stderr)
        entries = newc(self.archive(self.tmp / 'with'))
        expected = ''.join(f'{rel} {len(data)} {hashlib.sha256(data).hexdigest()}\n'
                           for rel, data in sorted(FIXTURE.items()))
        self.assertEqual(entries['etc/piano-firmware'][1].decode(), expected)
        self.assertEqual((self.tmp / 'with/firmware-manifest').read_text(), expected)
        for rel, data in FIXTURE.items():
            mode, body = entries[f'lib/firmware/{rel}']
            self.assertEqual((mode & 0o170000, mode & 0o777, body), (0o100000, 0o644, data))
        for d in ('lib', 'lib/firmware', 'lib/firmware/qcom', 'lib/firmware/qcom/sm8750',
                  'lib/firmware/qcom/sm8750/vendor', 'lib/firmware/qcom/sm8750/vendor/board'):
            self.assertEqual(entries[d][0] & 0o170000, 0o040000, d)
        plain_entries = newc(self.archive(self.tmp / 'plain'))
        self.assertFalse(any(n.startswith('lib/') or n == 'etc/piano-firmware' for n in plain_entries))
        self.assertFalse((self.tmp / 'plain/firmware-manifest').exists())
        ids = {plain_entries['etc/build-id'][1], entries['etc/build-id'][1]}
        (fw / 'top.bin').write_bytes(b'x')
        self.assertEqual(build(self.tmp / 'with', fw).returncode, 0)
        ids.add(newc(self.archive(self.tmp / 'with'))['etc/build-id'][1])
        self.assertEqual(len(ids), 3, 'firmware content must change the build-id')
        # Rebuilding without FIRMWARE_DIR drops the stale mirror.
        self.assertEqual(build(self.tmp / 'with').returncode, 0)
        self.assertFalse((self.tmp / 'with/firmware-manifest').exists())
        # build-boot.py reads back exactly this manifest.
        text, rows = runpy.run_path(str(TOOLS / 'build-boot.py'))['firmware_manifest'](
            self.archive(self.tmp / 'plain'))
        self.assertEqual((text, rows), ('', []))
        self.assertEqual(build(self.tmp / 'with', fw).returncode, 0)
        text, rows = runpy.run_path(str(TOOLS / 'build-boot.py'))['firmware_manifest'](
            self.archive(self.tmp / 'with'))
        self.assertEqual(text, (self.tmp / 'with/firmware-manifest').read_text())
        self.assertEqual([r['path'] for r in rows], sorted(FIXTURE))

    def test_refusals(self):
        empty = self.tmp / 'empty'
        empty.mkdir()
        spaced = fixture(self.tmp / 'spaced', {'qcom/a b.fw': b'1'})
        linked = fixture(self.tmp / 'linked', {'a.fw': b'1'})
        (linked / 'b.fw').symlink_to('a.fw')
        for case in (empty, spaced, linked, self.tmp / 'missing'):
            result = build(self.tmp / 'out', case)
            self.assertNotEqual(result.returncode, 0, case)
            self.assertFalse((self.tmp / 'out/firmware-manifest').exists(), case)


if __name__ == '__main__':
    unittest.main()
