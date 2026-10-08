# SPDX-License-Identifier: GPL-2.0-only
"""piano-boot-update rotates the store and rewrites slot A only on a persistent piano boot."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import fakepiano as fp

SCRIPT = fp.BOOT.parents[1] / 'packaging/piano-device-support/usr/sbin/piano-boot-update'
RELEASE = '7.2.6-piano+'


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
            return subprocess.CompletedProcess(argv, 0)
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

    def test_rejects_other_releases(self):
        with self.assertRaises(SystemExit):
            self.tool.main(['piano-boot-update', '7.0.0-14-generic'], root=self.root, run=self.run_fake)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
