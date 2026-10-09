# SPDX-License-Identifier: GPL-2.0-only
"""piano-boot-update rotates the store and rewrites slot A only on a persistent piano boot."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import fakepiano as fp

SCRIPT = fp.BOOT.parents[1] / 'packaging/piano-device-support/usr/sbin/piano-boot-update'
RELEASE = '7.2.6-piano1'


def load():
    loader = importlib.machinery.SourceFileLoader('piano_boot_update', str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Update(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'etc/piano').mkdir(parents=True)
        (self.root / 'etc/piano/layout.json').write_text(json.dumps({'root_partuuid': fp.ROOT_UUID}))
        for name in ('ubuntu', 'ubuntu.prev'):
            d = self.root / 'var/lib/piano/switch' / name
            d.mkdir(parents=True)
            (d / 'SHA256SUMS').write_text(name + '\n')
        (self.root / 'proc').mkdir()
        (self.root / 'sys/firmware/devicetree/base').mkdir(parents=True)
        self.calls = []
        self.installed = []
        self.switch_rc = 0
        self.tool = load()

    def tearDown(self):
        self.tmp.cleanup()

    def run_fake(self, argv, check=False, **kw):
        self.calls.append(argv)
        if argv[0] == 'python3':  # the image builder
            out = Path(argv[argv.index('--output') + 1])
            out.mkdir()
            (out / 'SHA256SUMS').write_text('new\n')
            release = argv[argv.index('--kernel-release') + 1]
            (out / 'manifest.json').write_text(json.dumps({'kernel_release': release}))
            return subprocess.CompletedProcess(argv, 0)
        if argv[:2] == ['linux-version', 'list']:
            return subprocess.CompletedProcess(argv, 0, stdout=''.join(r + '\n' for r in self.installed))
        if argv[:2] == ['linux-version', 'sort']:  # numeric ABI order, as linux-version sorts piano<N>
            key = lambda r: [int(x) if x.isdigit() else x for x in re.split(r'([0-9]+)', r)]
            return subprocess.CompletedProcess(argv, 0, stdout=''.join(
                r + '\n' for r in sorted(kw['input'].split(), key=key)))
        return subprocess.CompletedProcess(argv, self.switch_rc)

    def update(self, cmdline, compatible=b'xiaomi,piano\0qcom,sm8750\0'):
        (self.root / 'proc/cmdline').write_text(cmdline + '\n')
        (self.root / 'sys/firmware/devicetree/base/compatible').write_bytes(compatible)
        with contextlib.redirect_stdout(io.StringIO()):
            return self.tool.main(['piano-boot-update', RELEASE], root=self.root, run=self.run_fake)

    def store(self, name):
        return (self.root / 'var/lib/piano/switch' / name / 'SHA256SUMS').read_text()

    def test_persistent_piano_rewrites_slot_after_rotation(self):
        self.assertEqual(self.update(fp.UBUNTU_CMDLINE), 0)
        self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), ('new\n', 'ubuntu\n'))
        self.assertEqual(self.calls[-1], [str(self.root / 'usr/sbin/piano-boot-switch'), 'to-ubuntu',
                                          '--only-if-ubuntu'])
        self.assertIn(str(self.root / f'boot/initrd.img-{RELEASE}'), self.calls[0])

    def test_wlan_address_is_passed_only_when_configured(self):
        self.update(fp.UBUNTU_CMDLINE)
        self.assertNotIn('--wlan-address-file', self.calls[0])
        (self.root / 'etc/piano/wlan-address').write_text('02:00:00:00:00:01\n')
        self.calls.clear()
        self.update(fp.UBUNTU_CMDLINE)
        builder = self.calls[0]
        self.assertEqual(builder[builder.index('--wlan-address-file') + 1],
                         str(self.root / 'etc/piano/wlan-address'))

    def test_other_environments_only_update_the_store(self):
        for cmdline, compatible in ((fp.ABL_APPEND, b'xiaomi,piano\0'),          # RAM root
                                    (fp.UBUNTU_CMDLINE, b'linux,dummy-virt\0'),  # QEMU
                                    (fp.UBUNTU_CMDLINE, b'')):                   # chroot, other host
            self.calls.clear()
            self.assertEqual(self.update(cmdline, compatible), 0)
            self.assertEqual(len(self.calls), 1, self.calls)
        (self.root / 'sys/firmware/devicetree/base/compatible').unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            self.tool.main(['piano-boot-update', RELEASE], root=self.root, run=self.run_fake)

    def test_switch_failure_fails_the_hook(self):
        self.switch_rc = 1
        with self.assertRaises(SystemExit) as ctx:
            self.update(fp.UBUNTU_CMDLINE)
        self.assertIn('piano-boot-switch status', str(ctx.exception.code))
        self.assertEqual(self.store('ubuntu'), 'new\n')

    def boots(self, name, release):
        (self.root / 'var/lib/piano/switch' / name / 'manifest.json').write_text(
            json.dumps({'kernel_release': release}))

    def remove(self, release):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.tool.main(['piano-boot-update', '--removed', release], root=self.root, run=self.run_fake)

    def test_removed_owner_is_replaced_by_the_newest_remaining_kernel(self):
        self.boots('ubuntu', '7.2.6-piano2')
        self.boots('ubuntu.prev', RELEASE)
        self.installed = ['7.0.0-14-generic', '7.2.6-piano+', RELEASE]
        (self.root / 'boot').mkdir()
        (self.root / f'boot/initrd.img-{RELEASE}').touch()
        (self.root / 'proc/cmdline').write_text(fp.UBUNTU_CMDLINE + '\n')
        (self.root / 'sys/firmware/devicetree/base/compatible').write_bytes(b'xiaomi,piano\0qcom,sm8750\0')
        self.assertEqual(self.remove('7.2.6-piano2'), 0)
        self.assertIn(str(self.root / f'boot/vmlinuz-{RELEASE}'), self.calls[2])
        self.assertEqual(self.store('ubuntu'), 'new\n')
        self.assertFalse((self.root / 'var/lib/piano/switch/ubuntu.prev').exists())  # was piano2's set
        self.assertEqual(self.calls[-1][1:], ['to-ubuntu', '--only-if-ubuntu'])

    def test_removed_rollback_kernel_drops_only_the_rollback_set(self):
        self.boots('ubuntu', '7.2.6-piano2')
        self.boots('ubuntu.prev', RELEASE)
        self.assertEqual(self.remove(RELEASE), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store('ubuntu'), 'ubuntu\n')
        self.assertFalse((self.root / 'var/lib/piano/switch/ubuntu.prev').exists())

    def test_removed_unrelated_kernel_changes_nothing(self):
        self.boots('ubuntu', '7.2.6-piano2')
        (self.root / 'var/lib/piano/switch/ubuntu.prev/boot.img').write_bytes(
            b'\0Linux version 7.2.6-piano+ (piano@builder) (gcc)\0')  # set built before manifests had a release
        self.assertEqual(self.remove(RELEASE), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), ('ubuntu\n', 'ubuntu.prev\n'))
        self.assertEqual(self.tool.set_release(self.root / 'var/lib/piano/switch/ubuntu.prev'), '7.2.6-piano+')

    def test_removed_legacy_kernel_drops_its_rollback_set(self):
        self.boots('ubuntu', RELEASE)
        (self.root / 'var/lib/piano/switch/ubuntu.prev/boot.img').write_bytes(
            b'\0Linux version 7.2.6-piano+ (piano@builder) (gcc)\0')
        self.assertEqual(self.remove('7.2.6-piano+'), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store('ubuntu'), 'ubuntu\n')
        self.assertFalse((self.root / 'var/lib/piano/switch/ubuntu.prev').exists())

    def test_removed_rejects_other_kernels(self):
        with self.assertRaises(SystemExit):
            self.remove('7.0.0-14-generic')
        self.assertEqual(self.calls, [])

    def test_rejects_other_releases(self):
        with self.assertRaises(SystemExit):
            self.tool.main(['piano-boot-update', '7.0.0-14-generic'], root=self.root, run=self.run_fake)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
