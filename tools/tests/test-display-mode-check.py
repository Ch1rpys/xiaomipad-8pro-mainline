#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline parser checks only: no bus, debugfs, device or fake acceptance run."""
import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'piano-display-mode-check.py'
spec = importlib.util.spec_from_file_location('display_mode_check', SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def variant(kind, data):
    return {'type': kind, 'data': data}


def state_reply():
    panel = ['DSI-1', 'fixture-vendor', 'fixture-panel', 'fixture-only']
    modes = [[f'3200x2136@{hz}.000', 3200, 2136, float(hz), 2.0, [1.0, 2.0],
              {'is-current': variant('b', hz == 144), 'refresh-rate-mode': variant('s', 'fixed')}]
             for hz in check.RATES]
    return {'type': 'ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv}',
            'data': [27, [[panel, modes, {'color-mode': variant('u', 0)}]],
                     [[0, 0, 2.0, 1, True, [panel], {}]],
                     {'layout-mode': variant('u', 1), 'supports-changing-layout-mode': variant('b', True)}]}


def samples(hz=120, frozen=False, half_frozen=False, frames=(0x10, 0x88, 0x100)):
    lines = [f'0x{frame:08x} 0x{(1 if frozen else i + 1):08x} '
             f'0x{(2 if frozen or half_frozen else i + 2):08x}' for i, frame in enumerate(frames)]
    parsed = [check.parse_crc_line(line) for line in lines]
    return [{'time': 10.0 + i * 120 / hz, 'frame': frame, 'values': values}
            for i, (frame, values) in enumerate(parsed)]


class Parsers(unittest.TestCase):
    def test_dbus_mode_selection_and_temporary_apply(self):
        original = check.parse_state(state_reply())
        modes = check.choose_modes(original)
        self.assertEqual(original['current']['id'], '3200x2136@144.000')
        self.assertEqual({rate: mode['hz'] for rate, mode in modes.items()},
                         {60: 60.0, 90: 90.0, 120: 120.0, 144: 144.0})
        args = check.apply_arguments(original, 28, modes[90]['id'])
        self.assertEqual(args, ['28', '1', '1', '0', '0', '2.0', '1', 'true',
                                '1', 'DSI-1', '3200x2136@90.000', '1',
                                'color-mode', 'u', '0', '1', 'layout-mode', 'u', '1'])
        # busctl get-property is bare data; call replies have an outer array.
        self.assertEqual(check.unwrap(variant('i', 3)), 3)
        self.assertEqual(check.unwrap(variant('b', [True])), [True])

    def test_unavailable_ambiguous_or_wrong_scale_mode(self):
        state = check.parse_state(state_reply())
        for change in ('missing', 'ambiguous', 'scale', 'variable'):
            with self.subTest(change=change):
                altered = copy.deepcopy(state)
                if change == 'missing':
                    altered['modes'] = altered['modes'][1:]
                elif change == 'ambiguous':
                    altered['modes'].append(copy.deepcopy(altered['modes'][0]))
                elif change == 'scale':
                    altered['modes'][0]['scales'] = [1.0]
                else:
                    altered['modes'][0]['properties']['refresh-rate-mode'] = 'variable'
                with self.assertRaises(check.Unsupported):
                    check.choose_modes(altered)

    def test_crc_hex_rate_and_content(self):
        result = check.crc_metrics(samples(), 120)
        self.assertEqual((result['status'], result['fps'], result['unique_crc']), ('PASS', 120.0, 3))
        self.assertEqual(result['unique_per_lm'], [3, 3])
        # Three lines span 240 frames: rate is not a count of read() calls.
        self.assertEqual(result['frames'], 240)
        self.assertEqual(check.crc_metrics(samples(hz=138), 120)['status'], 'PASS')
        self.assertEqual(check.crc_metrics(samples(hz=102), 120)['status'], 'PASS')
        self.assertEqual(check.crc_metrics(samples(hz=140), 120)['status'], 'FAIL')
        self.assertEqual(check.crc_metrics(samples(frozen=True), 120)['status'], 'FAIL')
        self.assertEqual(check.crc_metrics(samples(half_frozen=True), 120)['status'], 'FAIL')
        with self.assertRaises(check.Unsupported):
            check.parse_crc_line('XXXXXXXXXX 0x00000000 0x00000001')
        with self.assertRaises(ValueError):
            check.parse_crc_line('0x00000001 invalid')

    def test_crc_counter_wrap_reset_and_missing(self):
        wrap = samples(frames=(0xffffff90, 0x8, 0x80))
        self.assertEqual(check.crc_metrics(wrap, 120)['status'], 'PASS')
        self.assertEqual(check.crc_metrics(samples(frames=(120, 0, 120)), 120)['status'], 'FAIL')
        self.assertEqual(check.crc_metrics([], 120)['status'], 'FAIL')
        one_lm = samples()
        for sample in one_lm:
            sample['values'] = sample['values'][:1]
        self.assertEqual(check.crc_metrics(one_lm, 120)['status'], 'INCOMPLETE')

    def test_kernel_error_filter(self):
        failures = ['dsi_err_worker: status=4', 'DSI VID_MDP FIFO overflow',
                    'INTF1_UNDERRUN', 'frame_done timeout', 'frame done wait timed out',
                    'WARNING: CPU: 0', 'Call trace:',
                    'dsi0_phy_pll: lock failed', 'disp_cc clock stuck',
                    'clk_rcg2: rcg didn\'t update its configuration',
                    'arm-smmu: Unhandled context fault', 'Overflow of CRC buffer, userspace reads too slow.',
                    'REGDMA ctl=1 timeout', 'REGDMA fault status=0x10',
                    'REGDMA ctl=1 stop unconfirmed after 2 s; leaking DMA resources',
                    'GC REGDMA submission failed: -110', 'lutdma reset timed out']
        clean = ['msm_dpu hardware revision: 0xc0000000', 'GC2 REGDMA completed ctl=1 status=0x8']
        self.assertEqual(check.filter_kernel(clean + failures), failures)

    def test_stationary_encoder_endpoints(self):
        off = check.crc_metrics(samples(frozen=True), 120, 'encoder', stationary=True)
        self.assertEqual((off['status'], off['fps'], off['unique_crc']), ('PASS', 120, 1))
        self.assertEqual(off['unique_per_encoder'], [1, 1])
        self.assertEqual(off['stable_crc'], [1, 2])
        on_samples = samples(frozen=True)
        for sample in on_samples:
            sample['values'] = (0x12345678, 0xabcdef01)
        on = check.crc_metrics(on_samples, 120, 'encoder', stationary=True)
        self.assertTrue(check.nightlight_crc_matches(on, True, off['stable_crc']))
        self.assertTrue(check.nightlight_crc_matches(off, False, off['stable_crc']))
        self.assertFalse(check.nightlight_crc_matches(off, True, off['stable_crc']))
        self.assertFalse(check.nightlight_crc_matches(on, False, off['stable_crc']))
        moving = check.crc_metrics(samples(), 120, 'encoder', stationary=True)
        self.assertEqual(moving['status'], 'FAIL')
        self.assertIsNone(moving['stable_crc'])
        self.assertFalse(check.nightlight_crc_matches(moving, True, off['stable_crc']))
        self.assertEqual(check.crc_metrics(samples(hz=60, frozen=True), 120,
                                           'encoder', stationary=True)['status'], 'FAIL')
        self.assertEqual(check.crc_metrics(samples(), 120, 'encoder')['status'], 'PASS')

    def test_manual_schedule_and_color_reply(self):
        for hour in (0.0, 5.5, 12.0, 23.999):
            schedule = check.nightlight_schedule(hour)
            start, end = (float(schedule['night-light-schedule-' + key]) for key in ('from', 'to'))
            self.assertAlmostEqual((hour - start) % 24, 6)
            self.assertAlmostEqual((end - hour) % 24, 6)
            self.assertEqual(schedule['night-light-schedule-automatic'], 'false')
            self.assertEqual(schedule['night-light-temperature'], 'uint32 4000')
        reply = variant('a{sv}', [{'NightLightActive': variant('b', True),
                                  'Temperature': variant('u', 4000)}])
        self.assertEqual(check.unwrap(reply)[0], {'NightLightActive': True, 'Temperature': 4000})

    def test_drm_crtc_is_index_not_object_id(self):
        state = ('plane[44]: plane-0\n\tcrtc=crtc-2\n'
                 'crtc[83]: crtc-2\n\tenable=1\n\tactive=1\n'
                 'connector[98]: DSI-1\n\tcrtc=crtc-2\n')
        self.assertEqual(check.active_crtc(state), 'crtc-2')
        with self.assertRaises(RuntimeError):
            check.active_crtc(state.replace('active=1', 'active=0'))


if __name__ == '__main__':
    unittest.main()
