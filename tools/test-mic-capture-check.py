#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run mic-capture-check.py on synthetic WAV captures generated here (no fixture files)."""
import importlib.util
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

TOOL = Path(__file__).with_name('mic-capture-check.py')
spec = importlib.util.spec_from_file_location('mic_capture_check', TOOL)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

RATE, SECONDS = 48000, 5
N = RATE * SECONDS


def scaled(x, dbfs):
    mean = sum(x) / len(x)
    rms = math.sqrt(sum((v - mean) ** 2 for v in x) / len(x))
    gain = 32768 * 10 ** (dbfs / 20) / rms
    return [(v - mean) * gain for v in x]


def white(seed):
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(N)]


def pink(seed):
    """Paul Kellet's refined pink filter on Gaussian white noise."""
    rng = random.Random(seed)
    b = [0.0] * 7
    out = []
    for _ in range(N):
        w = rng.gauss(0, 1)
        b[0] = 0.99886 * b[0] + w * 0.0555179
        b[1] = 0.99332 * b[1] + w * 0.0750759
        b[2] = 0.96900 * b[2] + w * 0.1538520
        b[3] = 0.86650 * b[3] + w * 0.3104856
        b[4] = 0.55000 * b[4] + w * 0.5329522
        b[5] = -0.7616 * b[5] - w * 0.0168980
        out.append(sum(b[:6]) + b[6] + w * 0.5362)
        b[6] = w * 0.115926
    return out


def write(path, channels, rate=RATE):
    frames = bytearray()
    for frame in zip(*channels):
        frames += struct.pack('<' + 'h' * len(frame),
                              *(max(-32768, min(32767, round(v))) for v in frame))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(len(channels))
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


class Analyse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.pink_a, cls.pink_b = scaled(pink(1), -40), scaled(pink(2), -40)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def judge(self, name, channels, *extra, rate=RATE):
        path = self.root / f'{name}.wav'
        write(path, channels, rate)
        out = self.root / f'{name}.json'
        proc = subprocess.run([sys.executable, '-I', str(TOOL), str(path), '--json', str(out), *extra],
                              capture_output=True, text=True, timeout=120)
        result = json.loads(out.read_text()) if out.exists() else None
        return proc.returncode, result, proc.stderr

    def test_zeros_fail(self):
        code, r, _ = self.judge('zeros', [[0] * N, [0] * N])
        self.assertEqual((code, r['verdict'], r['path_alive']), (1, 'FAIL', False))
        self.assertIn('silent-or-constant', r['per_channel'][0]['failures'])
        self.assertTrue(r['identical_channels'])

    def test_dc_fails(self):
        code, r, _ = self.judge('dc', [[1200] * N, [-800] * N])
        self.assertEqual((code, r['verdict']), (1, 'FAIL'))
        for c in r['per_channel']:
            self.assertIn('silent-or-constant', c['failures'])
            self.assertFalse(c['path_alive'])

    def test_quiet_noise_fails_on_level_but_is_alive(self):
        code, r, _ = self.judge('quiet', [scaled(white(3), -70), scaled(white(4), -70)])
        self.assertEqual((code, r['verdict'], r['path_alive']), (1, 'FAIL', True))
        for c in r['per_channel']:
            self.assertIn('level', c['failures'])
            self.assertAlmostEqual(c['ac_rms_dbfs'], -70, delta=0.5)

    def test_white_noise_is_flat(self):
        code, r, _ = self.judge('white', [scaled(white(5), -40), scaled(white(6), -40)])
        self.assertEqual((code, r['verdict'], r['path_alive']), (1, 'FAIL', True))
        for c in r['per_channel']:
            self.assertEqual(c['failures'], ['flat-spectrum'])
            self.assertGreater(c['spectral_flatness'], 0.9)
            self.assertAlmostEqual(c['spectral_slope_db_per_octave'], 0, delta=0.5)

    def test_pink_noise_passes(self):
        code, r, err = self.judge('pink', [self.pink_a, self.pink_b])
        self.assertEqual((code, r['verdict']), (0, 'PASS'), err)
        for c in r['per_channel']:
            self.assertLess(c['spectral_flatness'], 0.7)
            self.assertAlmostEqual(c['spectral_slope_db_per_octave'], -3, delta=0.6)
            self.assertEqual(c['warnings'], [])
        self.assertFalse(r['identical_channels'])
        self.assertLess(abs(r['channel_correlation']), 0.1)

    def test_clipped_fails(self):
        loud = [max(-32768, min(32767, v * 300)) for v in self.pink_a]
        code, r, _ = self.judge('clipped', [loud, loud])
        self.assertEqual((code, r['verdict'], r['path_alive']), (1, 'FAIL', False))
        self.assertIn('clipped', r['per_channel'][0]['failures'])
        self.assertIn('both channels carry identical samples', r['per_channel'][0]['warnings'])

    def test_startup_transient_is_skipped_and_reported(self):
        start = [32767] * 75 + [int(20000 * math.exp(-i / 50)) for i in range(600)]
        x = start + self.pink_a[len(start):]
        code, r, _ = self.judge('startup', [x, self.pink_b])
        self.assertEqual((code, r['verdict']), (0, 'PASS'))
        self.assertEqual(r['per_channel'][0]['startup']['clipped_samples'], 75)

    def test_mains_line_warns(self):
        hum = [v + 3000 * math.sin(2 * math.pi * 100 * i / RATE) for i, v in enumerate(self.pink_a)]
        code, r, _ = self.judge('hum', [hum, self.pink_b])
        self.assertEqual(code, 0)
        lines = r['per_channel'][0]['tonal_lines']
        self.assertTrue(lines and lines[0]['mains_related'] and abs(lines[0]['hz'] - 100) < 6)
        self.assertTrue(any(w.startswith('mains-related') for w in r['per_channel'][0]['warnings']))

    def test_line_off_mains_is_not_mains_related(self):
        tone = [v + 3000 * math.sin(2 * math.pi * 1234 * i / RATE) for i, v in enumerate(self.pink_a)]
        code, r, _ = self.judge('line', [tone, self.pink_b])
        self.assertEqual(code, 0)
        line = r['per_channel'][0]['tonal_lines'][0]
        self.assertLess(abs(line['hz'] - 1234), 6)
        self.assertFalse(line['mains_related'])
        self.assertEqual(r['per_channel'][1]['tonal_lines'], [])

    def test_known_tone(self):
        tone = [v + 2000 * math.sin(2 * math.pi * 1000 * i / RATE) for i, v in enumerate(self.pink_a)]
        code, r, _ = self.judge('tone', [tone, tone[:]], '--tone', '1000')
        self.assertEqual((code, r['verdict']), (0, 'PASS'))
        code, r, _ = self.judge('no-tone', [self.pink_a, self.pink_b], '--tone', '1000')
        self.assertEqual(code, 1)
        self.assertIn('tone-1000.0-missing', r['per_channel'][0]['failures'])

    def test_format_is_checked(self):
        code, r, err = self.judge('mono', [self.pink_a])
        self.assertEqual((code, r), (2, None))
        self.assertIn('2 channels', err)
        code, r, err = self.judge('rate', [self.pink_a[:44100 * 3], self.pink_b[:44100 * 3]], rate=44100)
        self.assertEqual((code, r), (2, None))

    def test_print_command(self):
        proc = subprocess.run([sys.executable, '-I', str(TOOL), '--print-command'],
                              capture_output=True, text=True, check=True)
        self.assertEqual(proc.stdout.strip(), 'arecord -D hw:CARD=PianoCaptureDia,DEV=2 '
                                              '-f S16_LE -r 48000 -c 2 -d 5 -t wav -')

    def test_fft_matches_dft(self):
        rng = random.Random(7)
        x = [rng.uniform(-1, 1) for _ in range(64)]
        fast = check.FFT(64)(x)
        for k in (0, 1, 13, 32, 63):
            slow = sum(v * complex(math.cos(2 * math.pi * k * i / 64), -math.sin(2 * math.pi * k * i / 64))
                       for i, v in enumerate(x))
            self.assertAlmostEqual(abs(fast[k] - slow), 0, places=9)


if __name__ == '__main__':
    unittest.main()
