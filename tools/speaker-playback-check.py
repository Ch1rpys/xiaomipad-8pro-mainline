#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Unattended speaker playback check for piano; no device access here.

Two steps on the host around tools/speaker-playback-device.sh, which runs on
the tablet as root:

  speaker-playback-check.py tone tone.wav           # 3 s, 1 kHz, -20 dBFS, 4 ch
  (copy tone.wav to the tablet, run the device script, save its log)
  speaker-playback-check.py judge speaker-run.log --json result.json

`tone` refuses levels above -20 dBFS and lengths above 3 s: together with the
device script's amplifier limit (160 of 255, -35.6 dB) that is the ceiling for
unattended runs. `judge` reads the key=value log and reports each criterion:

- card and playback PCM present, four amplifiers bound, DEVID 0x2900 each;
- amplifier volume read back at the unattended value, kernel cap in force;
- aplay exit 0 after the whole tone, the 5 s watchdog not fired;
- no DSP/APM/amplifier error lines in the kernel log of the run;
- amplifiers running during the tone (PWRCTRL power-down bit clear, SYSCTRL
  0x00ef, DIGSTAT DACRUN set) and shut down afterwards (power-down bit set);
- STATUS (register 0x00) identical on the four amplifiers and stable during
  the tone. The vendor sources name its bits but not their polarity, so the
  bit values are reported, not judged; a fault on one amplifier still shows as
  a difference;
- battery current proxy: the summed bq27 current_now during the tone is lower
  (more discharge or less charge) than both the before and after windows by at
  least --min-delta-ma and by more than the spread inside the quiet windows.
  If that spread reaches --min-delta-ma (or the positive difference) the
  result is INCONCLUSIVE rather than FAIL. At the unattended gain the
  difference is mostly amplifier quiescent and boost current, not sound.

A PASS says the stream ran through the DSP and the amplifiers were powered and
fault-consistent while it did; it does not say anything was audible. Exit
status: 0 PASS, 1 FAIL or INCONCLUSIVE, 2 unusable input.
"""
import argparse
import json
import math
from pathlib import Path
import re
import statistics
import struct
import sys
import wave

RATE = 48000
CHANNELS = 4
MAX_LEVEL_DBFS = -20.0
MAX_SECONDS = 3.0
UNATTENDED_AMP = 160
KERNEL_CAP = 215
AMP_ADDRS = ('0x34', '0x35', '0x36', '0x37')
DEVID = 0x2900
# Field positions from the vendor fs1958.c (FS19XX_PWDN 0x0010, DACRUN 0x0106)
PWRCTRL_PWDN = 1 << 0
DIGSTAT_DACRUN = 1 << 1
SYSCTRL_ALL_ON = 0x00ef
STATUS_BITS = {0: 'BOVDS', 1: 'PLLS', 2: 'OTPDS', 3: 'OVDS', 4: 'UVDS', 5: 'OCDS',
               6: 'CLKS', 8: 'OTWDS', 9: 'BOPS', 10: 'BOLDS', 11: 'INDS', 14: 'VDDPS'}
ERROR_PATTERNS = re.compile(
    r'(fs19xx|q6apm|audioreach|q6prm|gpr|apm|sc8280xp|snd-sc8280xp|q6apm-lpass-dais)'
    r'.*(error|fail|timeout|timed out|invalid)|DSP returned error|CMD timeout', re.I)


def write_tone(path, level_dbfs, seconds, freq):
    if level_dbfs > MAX_LEVEL_DBFS:
        raise SystemExit(f'level {level_dbfs} dBFS above the unattended limit {MAX_LEVEL_DBFS}')
    if not 0 < seconds <= MAX_SECONDS:
        raise SystemExit(f'duration must be in (0, {MAX_SECONDS}] s')
    amp = 32767 * 10 ** (level_dbfs / 20)
    frames = int(RATE * seconds)
    ramp = int(RATE * 0.02)
    data = bytearray()
    for n in range(frames):
        gain = min(1.0, n / ramp, (frames - 1 - n) / ramp)
        v = int(round(amp * gain * math.sin(2 * math.pi * freq * n / RATE)))
        data += struct.pack('<h', v) * CHANNELS
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(data))
    peak = max(abs(s) for (s,) in struct.iter_unpack('<h', bytes(data))) or 1
    return {'path': str(path), 'frames': frames, 'channels': CHANNELS, 'rate': RATE,
            'freq_hz': freq, 'peak_dbfs': round(20 * math.log10(peak / 32768), 2)}


def fields(line):
    out = {}
    for m in re.finditer(r'([\w-]+)=("([^"]*)"|\S+)', line):
        out[m.group(1)] = m.group(3) if m.group(3) is not None else m.group(2)
    return out


def hexval(v):
    try:
        return int(v, 16)
    except (TypeError, ValueError):
        return None


def parse(text):
    log = {'amps': {}, 'volume': {}, 'regs': [], 'gauge': [], 'dmesg': [], 'fatal': [],
           'watchdog': False, 'unbound': False}
    for line in text.splitlines():
        key, _, rest = line.partition(' ')
        f = fields(rest)
        if key == 'card':
            log['card'] = f
        elif key == 'pcm0p':
            log['pcm0p'] = f.get('present') == '1'
        elif key == 'amp':
            log['amps'][f.get('addr')] = f
        elif key == 'volume':
            log['volume'][f.get('pos')] = f
        elif key == 'regs':
            log['regs'].append(f)
        elif key == 'gauge':
            vals = [int(v) for k, v in f.items() if k.startswith('bq27') and re.fullmatch(r'-?\d+', v)]
            if vals:
                log['gauge'].append((f.get('tag'), sum(vals)))
        elif key == 'aplay':
            log.setdefault('aplay', {}).update(f)
        elif key == 'watchdog':
            if f.get('fired') == '1':
                log['watchdog'] = True
            if f.get('unbound') == '1':
                log['unbound'] = True
        elif key == 'dmesg':
            log['dmesg'].append(rest)
        elif key == 'fatal':
            log['fatal'].append(rest)
        elif key in ('start', 'end'):
            log[key] = f
    return log


def judge(log, min_delta_ma):
    checks = {}

    def check(name, ok, detail):
        checks[name] = {'result': 'PASS' if ok else 'FAIL', 'detail': detail}

    check('no_fatal', not log['fatal'], log['fatal'])
    check('card', 'card' in log and log.get('pcm0p', False), log.get('card'))
    bound = {a: log['amps'].get(a, {}).get('bound') == '1' for a in AMP_ADDRS}
    check('amps_bound', all(bound.values()), bound)
    idle = {r.get('addr'): r for r in log['regs'] if r.get('tag') == 'idle'}
    devids = {a: hexval(idle.get(a, {}).get('r03')) for a in AMP_ADDRS}
    check('devid', all(v == DEVID for v in devids.values()),
          {a: (f'0x{v:04x}' if v is not None else None) for a, v in devids.items()})
    vols = log['volume']
    check('volume_cap', len(vols) == 4 and all(
        v.get('value', '').isdigit() and int(v['value']) == UNATTENDED_AMP and
        v.get('max', '').isdigit() and int(v['max']) <= KERNEL_CAP for v in vols.values()), vols)

    ap = log.get('aplay', {})
    rc = ap.get('rc')
    try:
        elapsed = float(ap['t1']) - float(ap['t0'])
    except (KeyError, ValueError):
        elapsed = None
    check('aplay', rc == '0' and elapsed is not None and 2.8 <= elapsed < 5.0,
          {'rc': rc, 'elapsed_s': elapsed})
    check('watchdog_not_fired', not log['watchdog'] and not log['unbound'],
          {'fired': log['watchdog'], 'unbound': log['unbound']})
    errors = [d for d in log['dmesg'] if ERROR_PATTERNS.search(d)]
    check('kernel_log', not errors, errors[:20])

    play = [r for r in log['regs'] if r.get('tag') == 'play']
    after = [r for r in log['regs'] if r.get('tag') == 'after']
    running = {}
    for a in AMP_ADDRS:
        rows = [r for r in play if r.get('addr') == a]
        running[a] = bool(rows) and all(
            (hexval(r.get('r10')) or 0) & PWRCTRL_PWDN == 0 and hexval(r.get('r11')) == SYSCTRL_ALL_ON and
            (hexval(r.get('r06')) or 0) & DIGSTAT_DACRUN for r in rows)
    check('amps_running', all(running.values()), running)
    stopped = {a: any(r.get('addr') == a and (hexval(r.get('r10')) or 0) & PWRCTRL_PWDN for r in after)
               for a in AMP_ADDRS}
    check('amps_shut_down_after', all(stopped.values()), stopped)

    status = {a: [hexval(r.get('r00')) for r in play if r.get('addr') == a] for a in AMP_ADDRS}
    flat = [v for vals in status.values() for v in vals]
    consistent = bool(flat) and None not in flat and len(set(flat)) == 1 and all(status.values())
    named = {}
    if flat and flat[0] is not None:
        named = {name: bool(flat[0] >> bit & 1) for bit, name in STATUS_BITS.items()}
    checks['status_consistent'] = {
        'result': 'PASS' if consistent else 'FAIL',
        'detail': {'values': {a: [f'0x{v:04x}' if v is not None else None for v in vals]
                              for a, vals in status.items()},
                   'bits_of_first': named,
                   'note': 'bit polarity unknown; only equality and stability are judged'}}

    def window(tag):
        return [v / 1000 for t, v in log['gauge'] if t == tag]
    before, during, later = window('before'), window('play'), window('after')
    if len(before) >= 5 and len(during) >= 3 and len(later) >= 5:
        mb, md, ma = statistics.mean(before), statistics.mean(during), statistics.mean(later)
        delta = min(mb - md, ma - md)
        spread = max(max(before) - min(before), max(later) - min(later))
        detail = {'before_ma': round(mb, 1), 'play_ma': round(md, 1), 'after_ma': round(ma, 1),
                  'delta_ma': round(delta, 1), 'quiet_spread_ma': round(spread, 1),
                  'min_delta_ma': min_delta_ma}
        if delta >= min_delta_ma and spread < delta:
            result = 'PASS'
        elif spread >= min_delta_ma or spread >= delta > 0:
            result = 'INCONCLUSIVE'
        else:
            result = 'FAIL'
        checks['current_proxy'] = {'result': result, 'detail': detail}
    else:
        checks['current_proxy'] = {'result': 'FAIL', 'detail': {
            'samples': [len(before), len(during), len(later)]}}

    results = {c['result'] for c in checks.values()}
    verdict = 'FAIL' if 'FAIL' in results else 'INCONCLUSIVE' if 'INCONCLUSIVE' in results else 'PASS'
    return {'verdict': verdict, 'checks': checks,
            'scope': 'DSP graph, amplifier state and current proxy; not audibility'}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('tone', help='write the unattended test tone')
    t.add_argument('output', type=Path)
    t.add_argument('--level-dbfs', type=float, default=MAX_LEVEL_DBFS)
    t.add_argument('--seconds', type=float, default=MAX_SECONDS)
    t.add_argument('--freq', type=float, default=1000.0)
    j = sub.add_parser('judge', help='judge a device log')
    j.add_argument('log', type=Path)
    j.add_argument('--min-delta-ma', type=float, default=50.0)
    j.add_argument('--json', type=Path)
    args = ap.parse_args()

    if args.cmd == 'tone':
        print(json.dumps(write_tone(args.output, args.level_dbfs, args.seconds, args.freq)))
        return 0
    try:
        text = args.log.read_text(errors='replace')
    except OSError as e:
        print(f'cannot read log: {e}', file=sys.stderr)
        return 2
    if 'start uptime=' not in text:
        print('not a speaker-playback-device.sh log', file=sys.stderr)
        return 2
    result = judge(parse(text), args.min_delta_ma)
    out = json.dumps(result, indent=1, sort_keys=True)
    if args.json:
        args.json.write_text(out + '\n')
    print(out)
    return 0 if result['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
