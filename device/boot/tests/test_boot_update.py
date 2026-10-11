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
from unittest import mock

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
        self.images = {n: fp.image_set('ubuntu', n) for n in ('ubuntu', 'ubuntu.prev', 'new')}
        (self.root / 'etc/piano').mkdir(parents=True)
        (self.root / 'etc/piano/layout.json').write_text(json.dumps({'root_partuuid': fp.ROOT_UUID}))
        for name in ('boot-profile.json', 'boot-signing.pem', 'bluetooth-address', 'boot-partitions.json'):
            (self.root / 'etc/piano' / name).write_text(name + '\n')
        for name in ('ubuntu', 'ubuntu.prev'):
            d = self.root / 'var/lib/piano/switch' / name
            d.mkdir(parents=True)
            self.image_dir(d, name)
        (self.root / 'proc').mkdir()
        (self.root / 'sys/firmware/devicetree/base').mkdir(parents=True)
        self.calls = []
        self.installed = []
        self.switch_rc = 0
        self.tool = load()

    def tearDown(self):
        self.tmp.cleanup()

    def sum_text(self, name):
        return ''.join(f'{fp.sha(self.images[name][n])}  {n}.img\n' for n in sorted(fp.slot.NAMES))

    def image_dir(self, directory, name):
        for n, data in self.images[name].items():
            (directory / (n + '.img')).write_bytes(data)
        (directory / 'SHA256SUMS').write_text(self.sum_text(name))

    def run_fake(self, argv, check=False, **kw):
        self.calls.append(argv)
        if argv[0] == 'python3':  # the image builder
            out = Path(argv[argv.index('--output') + 1])
            out.mkdir()
            self.image_dir(out, 'new')
            release = argv[argv.index('--kernel-release') + 1]
            (out / 'manifest.json').write_text(json.dumps({'kernel_release': release}))
            return subprocess.CompletedProcess(argv, 0)
        if argv[:2] == ['linux-version', 'list']:
            return subprocess.CompletedProcess(argv, 0, stdout=''.join(r + '\n' for r in self.installed))
        if argv[:2] == ['linux-version', 'sort']:  # numeric ABI order, as linux-version sorts piano<N>
            key = lambda r: [int(x) if x.isdigit() else x for x in re.split(r'([0-9]+)', r)]
            return subprocess.CompletedProcess(argv, 0, stdout=''.join(
                r + '\n' for r in sorted(kw['input'].split(), key=key)))
        if argv[-1] == 'status':
            current = self.root / 'var/lib/piano/switch/ubuntu'
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({
                'occupant': 'ubuntu', 'slot': 'gpt', 'slot_sha256': fp.slot.read_sums(current)}))
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
        self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), (self.sum_text('new'), self.sum_text('ubuntu')))
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
            self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), (self.sum_text('ubuntu'), self.sum_text('ubuntu.prev')))

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
        self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), (self.sum_text('ubuntu'), self.sum_text('ubuntu.prev')))

    def test_partition_map_is_needed_only_where_slot_a_is_written(self):
        (self.root / 'etc/piano/boot-partitions.json').unlink()
        self.assertEqual(self.update(fp.ABL_APPEND, b'xiaomi,piano\0'), 0)  # RAM root: store only
        self.assertEqual(len(self.calls), 1, self.calls)
        self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), (self.sum_text('new'), self.sum_text('ubuntu')))

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
        self.assertEqual(self.store('ubuntu'), self.sum_text('new'))

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
        self.assertEqual(self.store('ubuntu'), self.sum_text('new'))
        self.assertFalse((self.root / 'var/lib/piano/switch/ubuntu.prev').exists())  # was piano2's set
        self.assertEqual(self.calls[-2][1:], ['to-ubuntu', '--only-if-ubuntu'])

    def test_removed_rollback_kernel_drops_only_the_rollback_set(self):
        self.boots('ubuntu', '7.2.6-piano2')
        self.boots('ubuntu.prev', RELEASE)
        self.assertEqual(self.remove(RELEASE), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store('ubuntu'), self.sum_text('ubuntu'))
        self.assertFalse((self.root / 'var/lib/piano/switch/ubuntu.prev').exists())

    def test_removed_unrelated_kernel_changes_nothing(self):
        self.boots('ubuntu', '7.2.6-piano2')
        (self.root / 'var/lib/piano/switch/ubuntu.prev/boot.img').write_bytes(
            b'\0Linux version 7.2.6-piano+ (piano@builder) (gcc)\0')  # set built before manifests had a release
        self.assertEqual(self.remove(RELEASE), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual((self.store('ubuntu'), self.store('ubuntu.prev')), (self.sum_text('ubuntu'), self.sum_text('ubuntu.prev')))
        self.assertEqual(self.tool.set_release(self.root / 'var/lib/piano/switch/ubuntu.prev'), '7.2.6-piano+')

    def test_removed_legacy_kernel_drops_its_rollback_set(self):
        self.boots('ubuntu', RELEASE)
        (self.root / 'var/lib/piano/switch/ubuntu.prev/boot.img').write_bytes(
            b'\0Linux version 7.2.6-piano+ (piano@builder) (gcc)\0')
        self.assertEqual(self.remove('7.2.6-piano+'), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store('ubuntu'), self.sum_text('ubuntu'))
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
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = self.switch.main(argv[1:], host=self.p.host)
        if check and rc:
            raise subprocess.CalledProcessError(rc, argv, output=out.getvalue())
        return subprocess.CompletedProcess(argv, rc, stdout=out.getvalue())

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

    def test_rotation_preserves_the_previous_set_actually_in_slot(self):
        self.p.fill_slot(self.p.sets['ubuntu.prev'])
        rc, out = self.hook()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.p.slot_content(), self.new)
        previous = self.root / 'var/lib/piano/switch/ubuntu.prev/SHA256SUMS'
        self.assertEqual(previous.read_text(), self.sums(self.p.sets['ubuntu.prev']))
        self.assertEqual(self.status()[1]['occupant'], 'ubuntu')

    def test_mid_write_failure_rolls_back_and_repeated_updates_keep_the_occupant(self):
        write_set = self.switch.write_set
        original = self.p.sets['ubuntu']

        def fail_new(parts, directory, sums):
            if directory.name == 'ubuntu':
                # The first partition has already changed when the next write fails.
                parts['init_boot'].node.write_bytes(self.new['init_boot'])
                raise OSError('injected second-partition write failure')
            return write_set(parts, directory, sums)

        with mock.patch.object(self.switch, 'write_set', side_effect=fail_new):
            for tag in ('failed-1', 'failed-2'):
                self.new = fp.image_set('ubuntu', tag)
                with self.assertRaises(SystemExit):
                    self.hook()
                self.assertEqual(self.p.slot_content(), original)
                self.assertEqual(self.status()[1]['occupant'], 'ubuntu.prev')
                self.assertEqual(self.status()[1]['last']['result'], 'rolled-back')
        for tag in ('success-1', 'success-2', 'success-3'):
            self.new = fp.image_set('ubuntu', tag)
            self.assertEqual(self.hook()[0], 0)
            self.assertEqual(self.p.slot_content(), self.new)
            previous = self.root / 'var/lib/piano/switch/ubuntu.prev/SHA256SUMS'
            self.assertEqual(previous.read_text(), self.sums(original))
            self.assertEqual(self.status()[1]['occupant'], 'ubuntu')
            original = self.new

    def test_unknown_slot_refuses_before_store_rotation(self):
        self.p.fill_slot(fp.image_set('ubuntu', 'unknown'))
        (self.root / 'var/lib/piano/switch/.lock').touch()
        before = self.store()
        with self.assertRaises((SystemExit, fp.slot.Refusal)):
            self.hook()
        self.assertEqual({k: fp.sha(v) for k, v in self.store().items()},
                         {k: fp.sha(v) for k, v in before.items()})
        self.assertEqual(self.status()[1]['occupant'], 'unknown')

    def test_android_occupant_is_left_unchanged(self):
        self.p.fill_slot(self.p.sets['android'])
        self.assertEqual(self.hook()[0], 0)
        self.assertEqual(self.p.slot_content(), self.p.sets['android'])
        self.assertEqual(self.status()[1]['occupant'], 'android')

    def test_invalid_new_store_copy_is_rejected_before_rotation_or_slot_write(self):
        original = self.run_fake

        def corrupt_copy(argv, **kw):
            result = original(argv, **kw)
            if argv[0] == 'python3':
                path = Path(argv[argv.index('--output') + 1]) / 'boot.img'
                path.write_bytes(path.read_bytes()[:-1] + b'X')
            return result

        with mock.patch.object(self, 'run_fake', side_effect=corrupt_copy):
            with self.assertRaises(fp.slot.Refusal):
                self.hook()
        self.assertEqual(self.p.slot_content(), self.p.sets['ubuntu'])
        self.assertEqual(self.status()[1]['occupant'], 'ubuntu')
        self.assertEqual(fp.slot.read_sums(self.root / 'var/lib/piano/switch/ubuntu.prev'),
                         {n + '.img': fp.sha(data) for n, data in self.p.sets['ubuntu.prev'].items()})

    def test_switch_precondition_failure_can_be_followed_by_another_update(self):
        original = self.run_fake

        def refuse_switch(argv, **kw):
            if 'to-ubuntu' in argv:
                return subprocess.CompletedProcess(argv, 1)
            return original(argv, **kw)

        with mock.patch.object(self, 'run_fake', side_effect=refuse_switch):
            for tag in ('refused-1', 'refused-2'):
                self.new = fp.image_set('ubuntu', tag)
                with self.assertRaises(SystemExit):
                    self.hook()
                self.assertEqual(self.status()[1]['occupant'], 'ubuntu.prev')
                self.assertEqual(self.p.slot_content(), self.p.sets['ubuntu'])
        self.assertEqual(self.hook()[0], 0)
        self.assertEqual(self.p.slot_content(), self.new)

    def test_rotation_rename_failure_still_reports_and_retains_occupant(self):
        rename = Path.rename

        def fail_install(path, destination):
            if path.name == 'images':
                raise OSError('injected new set rename failure')
            return rename(path, destination)

        with mock.patch.object(Path, 'rename', fail_install):
            with self.assertRaises(OSError):
                self.hook()
        self.assertEqual(self.p.slot_content(), self.p.sets['ubuntu'])
        self.assertEqual(self.status()[1]['occupant'], 'ubuntu.prev')
        self.assertEqual(self.hook()[0], 0)
        self.assertEqual(self.p.slot_content(), self.new)

    def test_removed_kernel_does_not_delete_the_slot_occupant(self):
        self.p.fill_slot(self.p.sets['ubuntu.prev'])
        directory = self.root / 'var/lib/piano/switch/ubuntu.prev'
        (directory / 'manifest.json').write_text(json.dumps({'kernel_release': RELEASE}))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = self.tool.main(['piano-boot-update', '--removed', RELEASE],
                                root=self.root, run=self.run_fake)
        self.assertEqual(rc, 0)
        self.assertTrue(directory.is_dir())
        self.assertEqual(self.status()[1]['occupant'], 'ubuntu.prev')


if __name__ == '__main__':
    unittest.main()
