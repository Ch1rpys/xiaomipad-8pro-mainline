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
        for name in ('boot-profile.json', 'boot-signing.pem', 'bluetooth-address', 'boot-partitions.json'):
            (self.root / 'etc/piano' / name).write_text(name + '\n')
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

    def test_bluetooth_address_is_passed_only_when_configured(self):
        self.update(fp.UBUNTU_CMDLINE)
        builder = self.calls[0]
        self.assertEqual(builder[builder.index('--bt-address-file') + 1],
                         str(self.root / 'etc/piano/bluetooth-address'))
        (self.root / 'etc/piano/bluetooth-address').unlink()
        self.calls.clear()
        self.update(fp.UBUNTU_CMDLINE)
        self.assertNotIn('--bt-address-file', self.calls[0])

    def test_release_layout_selects_the_root_by_partition_name(self):
        builder = lambda: self.calls[0]
        self.update(fp.UBUNTU_CMDLINE)
        self.assertEqual(builder()[builder().index('--root-partuuid') + 1], fp.ROOT_UUID)
        (self.root / 'etc/piano/layout.json').write_text(json.dumps({'root_partlabel': 'linux_rootfs'}))
        self.calls.clear()
        self.update(fp.UBUNTU_CMDLINE)
        self.assertEqual(builder()[builder().index('--root-partlabel') + 1], 'linux_rootfs')
        self.assertNotIn('--root-partuuid', builder())

    def test_release_root_without_owner_inputs_keeps_the_store(self):
        for name in ('boot-profile.json', 'boot-signing.pem'):
            (self.root / 'etc/piano' / name).unlink()
            self.calls.clear()
            self.assertEqual(self.update(fp.UBUNTU_CMDLINE), 0)
            self.assertEqual(self.calls, [])
            self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), ('ubuntu\n', 'ubuntu.prev\n'))

    def test_persistent_boot_without_partition_map_keeps_the_store(self):
        (self.root / 'etc/piano/boot-partitions.json').unlink()
        out = io.StringIO()
        (self.root / 'proc/cmdline').write_text(fp.UBUNTU_CMDLINE + '\n')
        (self.root / 'sys/firmware/devicetree/base/compatible').write_bytes(b'xiaomi,piano\0qcom,sm8750\0')
        with contextlib.redirect_stdout(out):
            rc = self.tool.main(['piano-boot-update', RELEASE], root=self.root, run=self.run_fake)
        self.assertEqual((rc, self.calls), (0, []))
        self.assertIn('/etc/piano/boot-partitions.json', out.getvalue())
        self.assertIn(f'piano-boot-update {RELEASE}', out.getvalue())
        self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), ('ubuntu\n', 'ubuntu.prev\n'))

    def test_partition_map_is_needed_only_where_slot_a_is_written(self):
        (self.root / 'etc/piano/boot-partitions.json').unlink()
        self.assertEqual(self.update(fp.ABL_APPEND, b'xiaomi,piano\0'), 0)  # RAM root: store only
        self.assertEqual(len(self.calls), 1, self.calls)
        self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), ('new\n', 'ubuntu\n'))

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


class UpdateWithSwitch(unittest.TestCase):
    """The kernel/initrd hook path on a synthetic piano with the real piano-boot-switch.

    Initial Setup's keyboard page reruns update-initramfs, whose post-update hook
    execs piano-boot-update; its exit status is the hook's, and a failure leaves
    dracut half-configured."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = fp.FakePiano(self.tmp.name)  # persistent piano boot, slot A holds store/ubuntu
        self.root = self.p.root
        (self.root / 'etc/piano/boot-signing.pem').write_text('key\n')
        self.map = self.root / 'etc/piano/boot-partitions.json'
        self.switch = fp.load_tool('piano-boot-switch')
        self.tool = load()
        self.new = fp.image_set('ubuntu', 'u2')
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_fake(self, argv, check=False, **kw):
        self.calls.append(argv)
        if argv[0] == 'python3':  # the image builder: a valid Ubuntu set of partition size
            out = Path(argv[argv.index('--output') + 1])
            self.p.image_dir(out, self.new)
            (out / 'manifest.json').write_text(json.dumps({'kernel_release': RELEASE}))
            return subprocess.CompletedProcess(argv, 0)
        self.assertEqual(argv[0], str(self.root / 'usr/sbin/piano-boot-switch'))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return subprocess.CompletedProcess(argv, self.switch.main(argv[1:], host=self.p.host))

    def hook(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = self.tool.main(['piano-boot-update', RELEASE], root=self.root, run=self.run_fake)
        return rc, out.getvalue()

    def status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = self.switch.main(['status'], host=self.p.host)
        return rc, json.loads(out.getvalue())

    def store(self):
        base = self.root / 'var/lib/piano/switch'
        return {str(f.relative_to(base)): f.read_bytes() for f in sorted(base.rglob('*')) if f.is_file()}

    def sums(self, images):
        return ''.join(f'{fp.sha(images[n])}  {n}.img\n' for n in sorted(images))

    def test_without_partition_map_the_hook_succeeds_and_nothing_changes(self):
        saved = self.map.read_text()
        self.map.unlink()
        before = self.store()
        rc, out = self.hook()
        self.assertEqual((rc, self.calls), (0, []), out)
        self.assertIn('/etc/piano/boot-partitions.json', out)
        self.assertEqual(self.store(), before)
        self.assertEqual(self.p.slot_content(), self.p.sets['ubuntu'])
        # INSTALL step 10: with the map installed, status names the slot occupant...
        self.map.write_text(saved)
        rc, report = self.status()
        self.assertEqual((rc, report['occupant'], report['store']['ubuntu']['equals_slot']), (0, 'ubuntu', True))
        # ...and the documented piano-boot-update rotates and writes slot A.
        rc, out = self.hook()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.p.slot_content(), self.new)
        self.assertEqual(self.status()[1]['occupant'], 'ubuntu')

    def test_with_every_input_the_hook_rotates_and_writes_slot_a(self):
        android = {k: v for k, v in self.store().items() if k.startswith('android/')}
        rc, out = self.hook()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls[-1][1:], ['to-ubuntu', '--only-if-ubuntu'])
        store = self.root / 'var/lib/piano/switch'
        self.assertEqual((store / 'ubuntu/SHA256SUMS').read_text(), self.sums(self.new))
        self.assertEqual((store / 'ubuntu.prev/SHA256SUMS').read_text(), self.sums(self.p.sets['ubuntu']))
        self.assertEqual(self.p.slot_content(), self.new)
        rc, report = self.status()
        self.assertEqual((rc, report['occupant'], report['store']['ubuntu']['equals_slot']), (0, 'ubuntu', True))
        self.assertEqual({k: v for k, v in self.store().items() if k.startswith('android/')}, android)


if __name__ == '__main__':
    unittest.main()
