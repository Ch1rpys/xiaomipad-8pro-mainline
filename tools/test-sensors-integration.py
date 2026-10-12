#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline registry/privacy and readiness checks; never contacts a tablet."""
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
