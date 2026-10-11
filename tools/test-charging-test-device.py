#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the finite experiment against local files; no device commands."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('charging_test', Path(__file__).with_name('charging-test-device.py'))
charging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(charging)


class ExperimentTest(unittest.TestCase):
    def experiment(self, fault=None):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp)
            supplies = root / 'sys/class/power_supply'
            usb = supplies / 'xiaomi-mca-usb'
            usb.mkdir(parents=True)
            for k, v in {'usb_type': '[DCP] SDP CDP', 'online': '1', 'voltage_now': '5000000',
                         'current_now': '394000', 'input_current_limit': '100000',
                         'constant_charge_current': '0'}.items():
                (usb / k).write_text(v)
            if fault == 'unknown':
                (usb / 'usb_type').write_text('[Unknown] SDP DCP')
            gauges = [supplies / ('bq27z561-' + str(i)) for i in range(2)]
            for g in gauges:
                g.mkdir()
                for k, v in {'capacity': 60, 'current_now': -200000, 'voltage_now': 4000000,
                             'temp': 250}.items():
                    (g / k).write_text(str(v))
            mask = root / 'run/udev/rules.d/80-piano-charging.rules'
            mask.parent.mkdir(parents=True)
            mask.symlink_to('/dev/null')
            for p, v in {'proc/uptime': '42 0', 'proc/sys/kernel/random/boot_id': 'test-boot-id'}.items():
                f = root / p
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(v)
            debug = root / 'sys/kernel/debug/pmic_glink.xiaomi-mca.0'
            debug.mkdir(parents=True)
            for name in ('status', 'stats', 'frames'):
                (debug / name).write_text('fixture only\n')
            clock = [0]

            def sleep(seconds):
                clock[0] += seconds
                if (usb / 'constant_charge_current').read_text().strip() == '2000000':
                    for g in gauges:
                        (g / 'current_now').write_text('300000')
                        if clock[0] >= 400:
                            (g / 'capacity').write_text('61')

            def path(name):
                p = Path(name)
                return root / p.relative_to('/') if p.is_absolute() and not p.is_relative_to(root) else p

            def observed_sample(gs):
                s = original_sample(gs)
                if s['usb']['input_current_limit'] == 1500000:
                    if fault == 'icl-readback':
                        s['usb']['input_current_limit'] = 100000
                    elif fault == 'detach-after-icl':
                        s['usb']['online'] = 0
                return s

            original_sample = charging.sample
            fake_host = types.SimpleNamespace(require_root=lambda: None)
            identity = types.SimpleNamespace(Host=lambda: fake_host, require_piano=lambda h: None,
                                             firmware_serial=lambda h: 'test-unit')
            output = root / 'evidence'
            argv = ['test', '--serial', 'test-unit', '--output', str(output), '--attended-wall-charger']
            original_path = list(sys.path)
            try:
                with patch.dict(sys.modules, piano_bootslot=identity), \
                     patch.object(charging, 'USB', usb), patch.object(charging, 'SUPPLIES', supplies), \
                     patch.object(charging, 'Path', side_effect=path), \
                     patch.object(charging, 'sample', side_effect=observed_sample), \
                     patch.object(charging.time, 'monotonic', side_effect=lambda: clock[0]), \
                     patch.object(charging.time, 'sleep', side_effect=sleep), \
                     patch.object(charging.os, 'sync'), patch.object(charging.subprocess, 'run') as run, \
                     patch.object(sys, 'argv', argv):
                    rc = charging.main()
            finally:
                sys.path[:] = original_path
            result = json.loads((output / 'result.json').read_text())
            rows = [json.loads(l) for l in (output / 'samples.jsonl').read_text().splitlines()]
            reboot = any(c.args[0] == ['systemctl', 'reboot'] for c in run.call_args_list)
            return rc, result, rows, reboot, (usb / 'constant_charge_current').read_text().strip()

    def test_full_window_and_pass(self):
        rc, result, rows, reboot, fcc = self.experiment()
        self.assertEqual((rc, result['status'], reboot, fcc), (0, 'PASS', True, '2000000'))
        for phase, seconds in [('baseline', 120), ('written', 300)]:
            phase_rows = [r for r in rows if r['phase'] == phase]
            self.assertGreaterEqual(phase_rows[-1]['monotonic'] - phase_rows[0]['monotonic'], seconds)
        phases = [r['phase'] for r in rows]
        self.assertLess(phases.index('after-icl'), phases.index('after-fcc'))

    def test_unknown_source_never_writes(self):
        rc, result, rows, reboot, fcc = self.experiment('unknown')
        self.assertEqual((rc, result['status'], reboot, fcc), (1, 'ABORT', False, '0'))
        self.assertTrue(all(r['usb']['input_current_limit'] == 100000 for r in rows))

    def test_readback_failure_prevents_fcc_and_reboots(self):
        rc, result, rows, reboot, fcc = self.experiment('icl-readback')
        self.assertEqual((rc, result['status'], reboot, fcc), (1, 'ABORT', True, '0'))
        self.assertIn('readback mismatch', result['error'])

    def test_detach_prevents_fcc_and_reboots(self):
        rc, result, rows, reboot, fcc = self.experiment('detach-after-icl')
        self.assertEqual((rc, result['status'], reboot, fcc), (1, 'ABORT', True, '0'))
        self.assertIn('detached', result['error'])


if __name__ == '__main__':
    unittest.main()
