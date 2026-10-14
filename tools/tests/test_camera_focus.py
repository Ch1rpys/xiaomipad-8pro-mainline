# SPDX-License-Identifier: MIT
"""Offline only: synthetic Bayer/NV12 evidence and mocked control failures.

Run: python3 -m unittest discover -s tools/tests -p test_camera_focus.py -v
"""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

spec = importlib.util.spec_from_file_location('camera_test', Path(__file__).resolve().parents[1] / 'piano-camera-test.py')
camera = importlib.util.module_from_spec(spec)
spec.loader.exec_module(camera)


def bayer_pair():
    h, w = 192, 256
    row, col = np.indices((h, w))
    sharp = 128 + 65 * np.sin(col * np.pi / 4) + 15 * np.cos(row * np.pi / 8)
    blurred = sharp.copy()
    for _ in range(4):
        padded = np.pad(blurred, ((0, 0), (2, 2)), mode='edge')
        blurred = sum(k * padded[:, i:i+w] for i, k in enumerate([1, 4, 6, 4, 1])) / 16
    result = []
    for green in (sharp, blurred):
        raw = np.full((h*2, w*2), 96, dtype=np.uint8)  # RGGB; red/blue do not enter the metric
        raw[0::2, 1::2] = raw[1::2, 0::2] = np.rint(green).astype(np.uint8)
        result.append(raw)
    return result


def samples(values):
    return [dict(position=i, readback=i, readback_after=i, sharpness=v)
            for i, v in enumerate(values)]


class FocusMetric(unittest.TestCase):
    def test_synthetic_bayer_sharp_and_blurred(self):
        sharp, blurred = bayer_pair()
        for rows, cols in ((slice(0, None, 2), slice(1, None, 2)),
                           (slice(1, None, 2), slice(0, None, 2))):
            high = camera.focus_sharpness(sharp[rows, cols])
            low = camera.focus_sharpness(blurred[rows, cols])
            self.assertGreater(high, camera.FOCUS_TEXTURE_FLOOR)
            self.assertGreater(high / low, 1.3)
            self.assertEqual(camera.focus_verdict(samples([low, low, high, low, low]))['status'], 'PASS')

    def test_matches_community_scalar_formula_without_uint8_wrap(self):
        y = bayer_pair()[0][0::2, 1::2]
        h, w = y.shape
        grad = luma = 0
        for r in range(h//3, 2*h//3, 4):
            for x in range(w//3, 2*w//3, 2):
                grad += (int(y[r, x+2])-int(y[r, x])) ** 2
                luma += int(y[r, x])
        self.assertAlmostEqual(camera.focus_sharpness(y), grad/luma)

    def test_flat_and_low_noise_are_incomplete(self):
        rng = np.random.default_rng(9764)
        flat = np.full((192, 256), 128, dtype=np.uint8)
        noise = np.rint(flat + rng.normal(0, 2, flat.shape)).astype(np.uint8)
        for plane in (flat, noise, np.zeros_like(flat)):
            score = camera.focus_sharpness(plane)
            self.assertEqual(camera.focus_verdict(samples([score]*5))['status'], 'INCOMPLETE')
        # A large ratio entirely below the noise floor must never pass.
        self.assertEqual(camera.focus_verdict(samples([0.001, .9, .2, .3, .4]))['status'], 'INCOMPLETE')

    def test_verdict_boundaries_and_zero_denominator(self):
        self.assertEqual(camera.focus_verdict(samples([10, 10, 13, 11, 12]))['status'], 'PASS')
        failure = camera.focus_verdict(samples([10, 10, 12.9, 11, 12]))
        self.assertEqual(failure['status'], 'FAIL')
        self.assertEqual(failure['reason'], '执行器写入被接受但图像无变化')
        result = camera.focus_verdict(samples([0, 0, 4, 0, 0]))
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['ratio_is_infinite'])
        json.dumps(result, allow_nan=False)

    def test_failed_controls_override_texture(self):
        for key, value in [('readback', 999), ('readback_after', 999), ('error', 'I2C failed')]:
            evidence = samples([0]*5)
            evidence[2][key] = value
            self.assertEqual(camera.focus_verdict(evidence)['status'], 'FAIL')
        self.assertEqual(camera.focus_verdict(samples([2]*4))['status'], 'FAIL')
        self.assertEqual(camera.focus_verdict(samples([float('nan')]*5))['status'], 'FAIL')

    def test_positions_obey_min_max_and_step(self):
        self.assertEqual(camera.focus_positions(10, 90, 4), [10, 30, 50, 70, 90])
        self.assertEqual(camera.focus_positions(10, 99, 3), [10, 31, 55, 76, 97])
        for limits in [(0, 3, 1), (0, 100, 0), (10, 0, 1)]:
            with self.assertRaises(ValueError):
                camera.focus_positions(*limits)


class FocusCapture(unittest.TestCase):
    def run_sweep(self, failure=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'rear').mkdir()
            lens = root / 'lens'
            lens.touch()  # Ordinary temporary file, never a device.
            table = {'dw9768 7-000c': str(lens), 's5kjn1 7-0010': '/fake/sensor',
                     'msm_vfe0_pix': '/fake/vfe', 'msm_vfe0_video3': '/fake/video'}
            state = {'controls': [[str(lens), camera.FOCUS, 30]], 'formats': [], 'ccm': []}
            position, writes, captures = 30, [], []
            sharp, blurred = [b[0::2, 1::2] for b in bayer_pair()]
            h, w = sharp.shape
            # Include padding to ensure the metric ignores it.
            stride = w + 16
            size = stride*h*3//2
            fmt = camera.request(208, 9)
            struct.pack_into('=III', fmt, 8, w, h, int.from_bytes(b'NV12', 'little'))
            struct.pack_into('=II', fmt, 28, size, stride)
            fmt[188] = 1

            def control(dev, cid, value=None):
                nonlocal position
                if cid != camera.FOCUS:
                    return 123
                if value is not None:
                    writes.append(value)
                    if failure == 'write' and value != 30:
                        raise OSError('CCI write failed')
                    position = value
                return position

            def ioctl(dev, nr, data):
                if nr == 36:
                    if failure == 'missing':
                        raise OSError('No focus control')
                    return struct.pack('=II32siiiiI2I', camera.FOCUS, 1, b'Focus Absolute', 10, 90, 4, 10, 0, 0, 0)
                return bytes(fmt)

            def stream(args, **kwargs):
                captures.append(position)
                self.assertIn('--stream-count=7', args)
                if failure == 'capture':
                    raise subprocess.TimeoutExpired(args, 15)
                plane = np.full((h, stride), 255, dtype=np.uint8)
                plane[:, :w] = sharp if position == 50 else blurred
                frame = plane.tobytes() + bytes([128])*(stride*h//2)
                return subprocess.CompletedProcess(args, 0, frame*7)

            with patch.object(camera, 'WIDTH', w), patch.object(camera, 'HEIGHT', h), \
                 patch.object(camera, 'ioctl', side_effect=ioctl), \
                 patch.object(camera, 'ctrl', side_effect=control), \
                 patch.object(camera, 'exclusive'), patch.object(camera.time, 'sleep') as sleep, \
                 patch.object(camera.subprocess, 'run', side_effect=stream):
                result = camera.focus_sweep(root, table, state)
                if failure is None:
                    self.assertEqual(writes, [10, 30, 50, 70, 90])
                    self.assertEqual(captures, writes)
                    self.assertEqual(sleep.call_count, 5)
                    for row in result['samples']:
                        self.assertEqual(len(row['frames']), 3)
                        for frame in row['frames']:
                            self.assertEqual(camera.sha(Path(frame['path'])), frame['sha256'])
                # The common restore must restore the pre-daemon value, also on
                # partial sweep errors. No new focus-specific cleanup path.
                with patch.object(camera, 'command', return_value=''):
                    camera.restore(state, '/fake/media', [])
                self.assertEqual(position, 30)
            json.dumps(result, allow_nan=False)
            return result

    def test_five_positions_frames_and_original_restore(self):
        self.assertEqual(self.run_sweep()['status'], 'PASS')

    def test_absent_control_is_fail(self):
        self.assertEqual(self.run_sweep('missing')['status'], 'FAIL')

    def test_write_failure_is_fail_and_restored(self):
        # Reject sweep writes while allowing the original focus value to restore.
        self.assertEqual(self.run_sweep('write')['status'], 'FAIL')

    def test_capture_failure_is_fail_and_restored(self):
        self.assertEqual(self.run_sweep('capture')['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
