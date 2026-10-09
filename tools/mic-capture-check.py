#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Judge an internal-microphone capture WAV taken on the tablet; no device access.

Take the capture on the tablet with alsa-utils, for example over developer mode:

    tools/piano-devmode-ssh.py USER -- arecord -D hw:CARD=PianoCaptureDia,DEV=2 \\
        -f S16_LE -r 48000 -c 2 -d 5 -t wav - > capture.wav

(`--print-command` prints this line), then run this program on the host. Each
channel is checked after skipping the stream start (the VA path opens with a
high-pass-filter transient):

- not digital silence and not constant (enough distinct sample values, AC RMS
  at least one LSB);
- not clipped (fraction of samples at full scale);
- AC level at least --min-rms-dbfs;
- spectrum not flat: Welch-averaged spectral flatness over --band below
  --max-flatness. White noise (electrical/thermal/quantisation) is flat;
  room sound is not.

Strong narrow spectral lines (mains harmonics or any other line well above the
local floor) are reported as warnings. With --tone HZ, each channel must also
show that tone (a known source played near the tablet).

Limits: an ambient-only result cannot prove the signal is acoustic. Clock
leakage, interference or a stuck data line can produce a non-flat spectrum,
and a working microphone in a quiet room can be below the level threshold or
dominated by its own white self-noise. `path_alive` separates "the capture
path delivers live data" from the acoustic verdict. Audibility needs a person.
The exit status is 0 for PASS, 1 for FAIL and 2 for unusable input.
"""
import argparse
import cmath
import json
import math
from pathlib import Path
import sys
import wave

FULL_SCALE = 32768.0
CARD = 'PianoCaptureDia'


def dbfs(value):
    return round(20 * math.log10(value / FULL_SCALE), 2) if value > 0 else None


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        if w.getcomptype() != 'NONE' or w.getsampwidth() != 2:
            raise ValueError('expected uncompressed 16-bit PCM')
        rate, channels, frames = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(frames)
    samples = memoryview(raw).cast('h')
    return rate, [samples[c::channels].tolist() for c in range(channels)]


class FFT:
    """In-place iterative radix-2 FFT with precomputed twiddles."""

    def __init__(self, n):
        if n & (n - 1):
            raise ValueError('FFT size must be a power of two')
        self.n = n
        bits = n.bit_length() - 1
        self.rev = [int(format(i, f'0{bits}b')[::-1], 2) for i in range(n)]
        self.tw = [cmath.exp(-2j * math.pi * k / n) for k in range(n // 2)]

    def __call__(self, x):
        n, a = self.n, [complex(x[i]) for i in self.rev]
        size = 2
        while size <= n:
            half, step = size // 2, n // size
            for start in range(0, n, size):
                for k in range(half):
                    t = self.tw[k * step] * a[start + k + half]
                    a[start + k + half] = a[start + k] - t
                    a[start + k] += t
            size *= 2
        return a


def welch_psd(x, nperseg, max_segments):
    """One-sided Hann-window Welch PSD (arbitrary units) from evenly spread segments."""
    count = len(x) // nperseg
    if count < 1:
        raise ValueError('capture shorter than one analysis segment')
    picks = sorted({round(i * (count - 1) / max(max_segments - 1, 1)) for i in range(min(count, max_segments))})
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / nperseg) for i in range(nperseg)]
    fft = FFT(nperseg)
    psd = [0.0] * (nperseg // 2 + 1)
    for seg in picks:
        chunk = x[seg * nperseg:(seg + 1) * nperseg]
        mean = sum(chunk) / nperseg
        spectrum = fft([(v - mean) * w for v, w in zip(chunk, window)])
        for k in range(len(psd)):
            psd[k] += abs(spectrum[k]) ** 2
    return [p / len(picks) for p in psd], len(picks)


def tonal_lines(psd, freqs, lo, hi, neighbours=16, threshold_db=20.0, limit=5):
    """Bins at least threshold_db above the median of their neighbourhood, strongest first."""
    lines = []
    for k, f in enumerate(freqs):
        if not lo <= f <= hi or psd[k] <= 0:
            continue
        around = sorted(psd[max(0, k - neighbours):k - 1] + psd[k + 2:k + neighbours + 1])
        floor = around[len(around) // 2] if around else 0
        if floor > 0 and psd[k] >= max(psd[k - 1], psd[min(k + 1, len(psd) - 1)]):
            excess = 10 * math.log10(psd[k] / floor)
            if excess >= threshold_db:
                lines.append({'hz': round(f, 1), 'above_floor_db': round(excess, 1)})
    lines.sort(key=lambda line: -line['above_floor_db'])
    return lines[:limit]


def mains_related(hz, resolution):
    """Within one bin of a 50/60 Hz harmonic up to the 20th."""
    return any(abs(hz - h * m) <= max(resolution, 1.0) for m in (50, 60) for h in range(1, 21))


def analyse_channel(x, rate, args):
    skip = int(args.skip_seconds * rate)
    head, body = x[:skip], x[skip:]
    n = len(body)
    mean = sum(body) / n
    ac_rms = math.sqrt(sum((v - mean) ** 2 for v in body) / n)
    clipped = sum(1 for v in body if v >= 32767 or v <= -32768)
    result = {
        'samples': n,
        'distinct_values': len(set(body)),
        'zero_fraction': round(body.count(0) / n, 6),
        'dc_dbfs': dbfs(abs(mean)),
        'ac_rms_dbfs': dbfs(ac_rms),
        'peak_dbfs': dbfs(max(abs(min(body)), abs(max(body)))),
        'clipped_fraction': round(clipped / n, 6),
        'startup': {'seconds_skipped': args.skip_seconds,
                    'peak_dbfs': dbfs(max((abs(v) for v in head), default=0)),
                    'clipped_samples': sum(1 for v in head if v >= 32767 or v <= -32768)},
    }
    failures = []
    if result['distinct_values'] < 16 or ac_rms < 1.0:
        failures.append('silent-or-constant')
    if clipped / n > args.max_clipped_fraction:
        failures.append('clipped')
    result['path_alive'] = not failures
    if ac_rms < 1.0 or dbfs(ac_rms) < args.min_rms_dbfs:
        failures.append('level')
    warnings = []
    if ac_rms >= 1.0:
        psd, segments = welch_psd(body, args.segment, args.max_segments)
        resolution = rate / args.segment
        freqs = [k * resolution for k in range(len(psd))]
        band = [(f, p) for f, p in zip(freqs, psd) if args.band[0] <= f <= args.band[1] and p > 0]
        if len(band) < 8:
            raise ValueError('analysis band holds too few frequency bins')
        arithmetic = sum(p for _, p in band) / len(band)
        geometric = math.exp(sum(math.log(p) for _, p in band) / len(band))
        flatness = geometric / arithmetic
        lf, lp = [math.log2(f) for f, _ in band], [10 * math.log10(p) for _, p in band]
        mf, mp = sum(lf) / len(lf), sum(lp) / len(lp)
        slope = (sum((a - mf) * (b - mp) for a, b in zip(lf, lp)) /
                 sum((a - mf) ** 2 for a in lf))
        # Narrow lines on a 4x finer grid so that mains harmonics can be told apart.
        fine, _ = welch_psd(body, 4 * args.segment, max(args.max_segments // 2, 1))
        fine_resolution = resolution / 4
        lines = tonal_lines(fine, [k * fine_resolution for k in range(len(fine))], args.band[0], args.band[1])
        for line in lines:
            line['mains_related'] = mains_related(line['hz'], fine_resolution)
        result.update({'welch_segments': segments, 'resolution_hz': round(resolution, 2),
                       'line_resolution_hz': round(fine_resolution, 2),
                       'spectral_flatness': round(flatness, 4),
                       'spectral_slope_db_per_octave': round(slope, 2), 'tonal_lines': lines})
        if flatness > args.max_flatness:
            failures.append('flat-spectrum')
        for line in lines:
            warnings.append(('mains-related' if line['mains_related'] else 'narrow') +
                            f' line {line["hz"]} Hz, {line["above_floor_db"]} dB above floor')
        tones = {}
        for hz in args.tone:
            k = round(hz / resolution)
            peak = max(psd[max(k - 2, 0):k + 3])
            around = sorted(psd[max(0, k - 24):max(k - 4, 0)] + psd[k + 5:k + 25])
            floor = around[len(around) // 2] if around else 0
            excess = 10 * math.log10(peak / floor) if peak > 0 and floor > 0 else None
            tones[str(hz)] = None if excess is None else round(excess, 1)
            if excess is None or excess < args.tone_db:
                failures.append(f'tone-{hz}-missing')
        if tones:
            result['tones_above_floor_db'] = tones
    result['failures'] = failures
    result['warnings'] = warnings
    result['verdict'] = 'FAIL' if failures else 'PASS'
    return result


def correlation(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da, db = [v - ma for v in a], [v - mb for v in b]
    den = math.sqrt(sum(v * v for v in da) * sum(v * v for v in db))
    return round(sum(x * y for x, y in zip(da, db)) / den, 4) if den else None


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('wav', type=Path, nargs='?', help='captured WAV (16-bit PCM)')
    ap.add_argument('--json', type=Path, help='also write the result to this new file')
    ap.add_argument('--print-command', action='store_true', help='print the tablet-side arecord command and exit')
    ap.add_argument('--device', default=f'hw:CARD={CARD},DEV=2', help='ALSA device for --print-command')
    ap.add_argument('--rate', type=int, default=48000)
    ap.add_argument('--channels', type=int, default=2)
    ap.add_argument('--seconds', type=int, default=5, help='capture length for --print-command')
    ap.add_argument('--skip-seconds', type=float, default=0.5, help='stream start excluded from the judgement')
    ap.add_argument('--min-rms-dbfs', type=float, default=-60.0)
    ap.add_argument('--max-flatness', type=float, default=0.8)
    ap.add_argument('--max-clipped-fraction', type=float, default=0.001)
    ap.add_argument('--band', type=float, nargs=2, default=(50.0, 8000.0), metavar=('LOW_HZ', 'HIGH_HZ'))
    ap.add_argument('--segment', type=int, default=2048, help='Welch segment length (power of two)')
    ap.add_argument('--max-segments', type=int, default=64)
    ap.add_argument('--tone', type=float, action='append', default=[], metavar='HZ',
                    help='require this known source frequency on every channel')
    ap.add_argument('--tone-db', type=float, default=15.0, help='required tone excess over the local floor')
    args = ap.parse_args(argv)
    if not args.print_command and not args.wav:
        ap.error('a WAV file is required')
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.print_command:
        print(f'arecord -D {args.device} -f S16_LE -r {args.rate} -c {args.channels} -d {args.seconds} -t wav -')
        return 0
    try:
        rate, channels = read_wav(args.wav)
        if rate != args.rate or len(channels) != args.channels:
            raise ValueError(f'expected {args.rate} Hz x {args.channels} channels, got {rate} Hz x {len(channels)}')
        if len(channels[0]) < (args.skip_seconds + 1) * rate:
            raise ValueError('capture shorter than the skipped start plus one second')
        per_channel = [analyse_channel(x, rate, args) for x in channels]
    except (ValueError, wave.Error, EOFError) as error:
        print(f'mic-capture-check: {args.wav}: {error}', file=sys.stderr)
        return 2
    skip = int(args.skip_seconds * rate)
    bodies = [x[skip:] for x in channels]
    result = {
        'input': str(args.wav), 'rate': rate, 'channels': len(channels),
        'seconds': round(len(channels[0]) / rate, 3),
        'criteria': {k: getattr(args, k) for k in ('skip_seconds', 'min_rms_dbfs', 'max_flatness',
                                                   'max_clipped_fraction', 'band', 'segment', 'tone', 'tone_db')},
        'per_channel': per_channel,
        'path_alive': all(c['path_alive'] for c in per_channel),
        'verdict': 'PASS' if all(c['verdict'] == 'PASS' for c in per_channel) else 'FAIL',
        'limits': 'Ambient-only criteria do not prove an acoustic source; audibility needs a person.',
    }
    if len(bodies) == 2:
        result['identical_channels'] = bodies[0] == bodies[1]
        result['channel_correlation'] = correlation(*bodies)
        if result['identical_channels']:
            for c in per_channel:
                c['warnings'].append('both channels carry identical samples')
    text = json.dumps(result, indent=2) + '\n'
    if args.json:
        with args.json.open('x') as f:
            f.write(text)
    sys.stdout.write(text)
    return 0 if result['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
