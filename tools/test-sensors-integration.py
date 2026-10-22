#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline registry/privacy and readiness checks; never contacts a tablet."""
from datetime import datetime, timezone
import importlib.machinery
import importlib.util
from pathlib import Path
import socket
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'device/sensors'))
from qrtr import lookup


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


prepare = load('prepare', REPO / 'packaging/piano-sensors/usr/libexec/piano/sensors-prepare')
stage = load('stage', REPO / 'tools/stage-sensor-registry.py')


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.share = self.root / 'share'
        (self.share / 'registry/registry').mkdir(parents=True)
        self.state = self.root / 'state'; self.state.mkdir()

    def test_default_calibration_and_persistent_reopen(self):
        self.assertEqual(prepare.seed_registry(self.share, self.state), 'stock-default-calibration')
        learned = self.state / 'registry/registry/learned'
        learned.write_text('new data')
        self.assertEqual(prepare.seed_registry(self.share, self.state), 'existing-state')
        self.assertEqual(learned.read_text(), 'new data')
        self.assertEqual(list((self.share / 'registry/registry').iterdir()), [])

    def test_private_staging_preserves_pristine(self):
        source = self.root / 'backup'; (source / 'registry').mkdir(parents=True)
        (source / 'registry/test.fac_cal').write_text('synthetic calibration')
        (source / 'sns_reg_version').write_text('synthetic version')
        staged = self.root / 'payload'
        stage.stage(source, staged)
        private = staged / 'usr/share/piano/sensors/registry-private'
        shutil.copytree(private, self.share / 'registry-private')
        self.assertEqual(prepare.seed_registry(self.share, self.state), 'private-calibration')
        (self.state / 'registry/registry/test.fac_cal').write_text('updated')
        self.assertEqual((self.share / 'registry-private/registry/test.fac_cal').read_text(), 'synthetic calibration')
        self.assertEqual((self.state / 'registry/sns_reg_version').read_text(), 'synthetic version')

    def test_late_private_seed_does_not_overwrite_state(self):
        prepare.seed_registry(self.share, self.state)
        (self.share / 'registry-private/registry').mkdir(parents=True)
        (self.share / 'registry-private/registry/late').write_text('late')
        self.assertEqual(prepare.seed_registry(self.share, self.state), 'existing-state')
        self.assertFalse((self.state / 'registry/registry/late').exists())

    def test_interrupted_copy_is_not_used(self):
        (self.state / 'registry.new').mkdir()
        (self.state / 'registry.new/partial').write_text('partial')
        prepare.seed_registry(self.share, self.state)
        self.assertFalse((self.state / 'registry/partial').exists())

    def test_state_link_rejected(self):
        (self.state / 'registry').symlink_to(self.share / 'registry')
        with self.assertRaises(ValueError): prepare.seed_registry(self.share, self.state)

    def test_private_link_rejected(self):
        (self.share / 'registry/registry/escape').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError): stage.stage(self.share / 'registry', self.root / 'payload')
        with self.assertRaises(ValueError): prepare.seed_registry(self.share, self.state)


# /dev/kmsg records: "prio,seq,usec,flags;message" plus indented key=value lines.
SENSOR_CRASH = (b'3,%d,16000000,-;qcom_q6v5_pas 6800000.remoteproc: fatal error received: '
                b'err_qdi.c:1215:EF:qsh_process:0x4:UTIMER_CLIENT_4:0x1000002f:sns_watchdog.c:84:'
                b'thread idx 1 exceeded processing time-limit curr_time=1ec2ec69\n'
                b' SUBSYSTEM=platform\n DEVICE=+platform:6800000.remoteproc\n')
# Same-boot neighbours that must not count: the PDM line of the same crash, the crash
# notice, a charger PD fatal error and the following watchdog bites.
OTHER_ADSP = (b"3,%d,16000001,-;PDM: service 'qsh_process' crash: "
              b"'EF:qsh_process:0x4:UTIMER_CLIENT_4:0x1000002f:sns_watchdo'\n"
              b'3,%d,16000002,-;remoteproc remoteproc0: crash detected in adsp: type fatal error\n'
              b'3,%d,16000003,-;qcom_q6v5_pas 6800000.remoteproc: fatal error received: '
              b'err_qdi.c:1215:EX:charger_process:0x3:TCPC_0:0x8c:PC=0x6000ad10:LR=0x6010deb8\n'
              b'3,%d,16000004,-;qcom_q6v5_pas 6800000.remoteproc: watchdog received: '
              b'SFR Init: wdog or kernel error suspected.\n')


class RegistryQuarantine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.share = self.root / 'share'
        (self.share / 'registry/registry').mkdir(parents=True)
        (self.share / 'registry/registry/seed').write_text('seed')
        self.state = self.root / 'state'; self.state.mkdir()
        self.boot = self.root / 'boot_id'; self.boot.write_text('boot-1\n')
        self.assertEqual(prepare.seed_registry(self.share, self.state), 'stock-default-calibration')
        # What the DSP leaves behind in the live state.
        (self.state / 'registry/fstempfile').write_text('wedged')
        (self.state / 'registry/sns_reg_version').write_text('version')
        self.now = datetime(2026, 10, 22, 8, 30, 0, tzinfo=timezone.utc)

    def kmsg(self, crashes):
        records = b''.join(OTHER_ADSP % (4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3) for i in range(4))
        records += b''.join(SENSOR_CRASH % (100 + i) for i in range(crashes))
        path = self.root / 'kmsg'
        path.write_bytes(records)
        return path

    def boot_pass(self, crashes, now=None):
        """One sensors-prepare run: kernel-log check, quarantine, then the normal seed step."""
        count = prepare.sensor_watchdog_crashes(self.kmsg(crashes))
        self.assertEqual(count, crashes)
        moved = prepare.quarantine_registry(self.state, count, self.boot, now or self.now)
        return moved, prepare.seed_registry(self.share, self.state)

    def snapshot(self):
        return sorted((str(p.relative_to(self.state)), p.read_text() if p.is_file() else None)
                      for p in self.state.rglob('*'))

    def test_no_sensor_crash_keeps_state(self):
        before = self.snapshot()
        self.assertEqual(self.boot_pass(0), (None, 'existing-state'))
        self.assertEqual(self.snapshot(), before)

    def test_two_sensor_crashes_keep_state(self):
        before = self.snapshot()
        self.assertEqual(self.boot_pass(2), (None, 'existing-state'))
        self.assertEqual(self.snapshot(), before)

    def test_three_sensor_crashes_quarantine_and_reseed(self):
        moved, calibration = self.boot_pass(3)
        self.assertEqual(moved, self.state / 'registry.quarantine-20261022T083000Z')
        self.assertEqual(calibration, 'stock-default-calibration')
        self.assertEqual((moved / 'fstempfile').read_text(), 'wedged')
        self.assertFalse((self.state / 'registry/fstempfile').exists())
        self.assertEqual((self.state / 'registry/registry/seed').read_text(), 'seed')

    def test_private_seed_is_used_for_the_new_state(self):
        (self.share / 'registry-private/registry').mkdir(parents=True)
        (self.share / 'registry-private/registry/factory').write_text('own unit')
        moved, calibration = self.boot_pass(5)
        self.assertIsNotNone(moved)
        self.assertEqual(calibration, 'private-calibration')

    def test_once_per_boot(self):
        first, _ = self.boot_pass(3)
        (self.state / 'registry/fstempfile').write_text('wedged again')
        later = datetime(2026, 10, 22, 8, 31, 0, tzinfo=timezone.utc)
        self.assertEqual(self.boot_pass(4, later), (None, 'existing-state'))
        self.assertEqual(sorted(self.state.glob('registry.quarantine-*')), [first])
        self.boot.write_text('boot-2\n')
        second, _ = self.boot_pass(3, later)
        self.assertEqual(sorted(self.state.glob('registry.quarantine-*')), [first, second])

    def test_keeps_the_three_newest_copies(self):
        for stamp in ('20261019T080000Z', '20261020T080000Z', '20261021T080000Z'):
            (self.state / f'registry.quarantine-{stamp}/registry').mkdir(parents=True)
        moved, _ = self.boot_pass(3)
        self.assertEqual([p.name for p in sorted(self.state.glob('registry.quarantine-*'))],
                         ['registry.quarantine-20261020T080000Z', 'registry.quarantine-20261021T080000Z',
                          moved.name])

    def test_missing_state_is_seeded_normally(self):
        shutil.rmtree(self.state / 'registry')
        self.assertEqual(self.boot_pass(3), (None, 'stock-default-calibration'))
        self.assertEqual(list(self.state.glob('registry.quarantine-*')), [])


class QRTR(unittest.TestCase):
    def query(self, packets, wait):
        fake = unittest.mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.getsockname.return_value = (1, 7)
        fake.recvfrom.side_effect = [*( (p, (1, 0xfffffffe)) for p in packets), socket.timeout()]
        with patch('qrtr.socket.socket', return_value=fake):
            return lookup(seconds=0.01, wait_for_service=wait)

    def test_late_service_after_initial_empty_lookup(self):
        result = self.query([struct.pack('<5I', 4, 0, 0, 0, 0), struct.pack('<5I', 4, 400, 1, 2, 9)], True)
        self.assertEqual(result[0]['service'], 400)

    def test_bounded_absence(self):
        self.assertEqual(self.query([struct.pack('<5I', 4, 0, 0, 0, 0)], True), [])

    def test_incomplete_lookup_is_not_absence(self):
        with self.assertRaises(TimeoutError): self.query([], False)


if __name__ == '__main__':
    unittest.main()
