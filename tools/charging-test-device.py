#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One attended wall-charger experiment, run locally on installed piano Ubuntu.

Launch from developer-mode SSH in a transient systemd service before moving the
cable to a wall charger. This is a finite diagnostic, not a charging service.
ICL automation must be masked for the entire baseline. After a write attempt,
reboot resets the firmware; output is flushed to persistent storage first.
"""
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

SUPPLIES = Path('/sys/class/power_supply')
USB = SUPPLIES / 'xiaomi-mca-usb'
WALL_TYPES = {'DCP', 'C', 'PD', 'PD_PPS'}


def integer(path):
    return int(path.read_text().strip())


def sample(gauges):
    types = re.findall(r'\[([^\]]+)\]', (USB / 'usb_type').read_text())
    if len(types) != 1:
        raise RuntimeError('Cannot identify the selected USB type')
    return {'monotonic': time.monotonic(), 'uptime': Path('/proc/uptime').read_text().split()[0],
            'usb_type': types[0],
            'usb': {p: integer(USB / p) for p in ('online', 'voltage_now', 'current_now',
                                                 'input_current_limit', 'constant_charge_current')},
            'batteries': {p.name: {k: integer(p / k) for k in ('capacity', 'current_now',
                                                              'voltage_now', 'temp')}
                          for p in gauges}}


def check_sample(s, source):
    if not s['usb']['online'] or s['usb_type'] != source:
        raise RuntimeError('Wall source detached or changed type')
    # Measurement window for this 5 V experiment, not a charger setting.
    if not 4500000 <= s['usb']['voltage_now'] <= 5500000:
        raise RuntimeError('VBUS outside the 5 V experiment window')
    if any(not 150 <= b['temp'] < 450 for b in s['batteries'].values()):
        raise RuntimeError('Battery outside the attended 15..45 C test window')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial', required=True)
    ap.add_argument('--output', type=Path, required=True, help='New persistent directory, e.g. /var/log/piano-charging-01')
    ap.add_argument('--attended-wall-charger', action='store_true', required=True,
                    help='Operator present, wall charger available, cable will be moved')
    args = ap.parse_args()
    # Reuse the installed device-support identity checks; no storage operations.
    sys.path.insert(0, '/usr/lib/piano/boot')
    from piano_bootslot import Host, require_piano, firmware_serial
    host = Host()
    host.require_root()
    require_piano(host)
    if firmware_serial(host) != args.serial:
        raise RuntimeError('Firmware serial does not match --serial')
    mask = Path('/run/udev/rules.d/80-piano-charging.rules')
    if not mask.is_symlink() or str(mask.readlink()) != '/dev/null':
        raise RuntimeError('Mask 80-piano-charging.rules in /run and reload udev before the baseline')
    if args.output.resolve().is_relative_to('/run') or args.output.resolve().is_relative_to('/tmp'):
        raise RuntimeError('Output must survive the concluding reboot')
    debug_dirs = list(Path('/sys/kernel/debug').glob('pmic_glink.xiaomi-mca*'))
    if len(debug_dirs) != 1 or any(not (debug_dirs[0] / f).is_file() for f in ('status', 'stats', 'frames')):
        raise RuntimeError('Mount debugfs and load the candidate before collecting MCA evidence')
    gauges = sorted(p for p in SUPPLIES.glob('bq27z561-*') if p.is_dir())
    if len(gauges) != 2:
        raise RuntimeError('Expected both bq27z561 gauges')
    args.output.mkdir(parents=True, exist_ok=False)
    wrote = False
    result = {'status': 'NOT_RUN', 'kernel': os.uname().release, 'serial': args.serial,
              'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    trace = (args.output / 'samples.jsonl').open('x', buffering=1)

    def record(phase):
        s = sample(gauges)
        trace.write(json.dumps(dict(phase=phase, **s)) + '\n')
        return s

    def capture(name):
        with (args.output / (name + '-dmesg.txt')).open('w') as log:
            subprocess.run(['dmesg'], stdout=log, stderr=subprocess.STDOUT, check=False)
        for d in debug_dirs:
            for leaf in ('status', 'stats', 'frames'):
                try:
                    (args.output / f'{name}-{leaf}.txt').write_text((d / leaf).read_text())
                except OSError as exc:
                    (args.output / f'{name}-{leaf}-error.txt').write_text(str(exc))

    def observe(phase, seconds, source):
        rows = []
        end = time.monotonic() + seconds
        while True:
            s = record(phase)
            rows.append(s)
            check_sample(s, source)
            remaining = end - time.monotonic()
            if remaining <= 0:
                return rows
            time.sleep(min(10, remaining))

    try:
        print('Ready: move the cable from the USB host to the wall charger now.', flush=True)
        end = time.monotonic() + 120
        while True:
            s = record('waiting-for-wall')
            if s['usb']['online'] and s['usb_type'] in WALL_TYPES:
                break
            if time.monotonic() >= end:
                raise RuntimeError('No recognized wall source within 120 seconds; no writes')
            time.sleep(2)
        source = s['usb_type']
        check_sample(s, source)
        if any(b['capacity'] < 40 or b['capacity'] > 90 for b in s['batteries'].values()):
            raise RuntimeError('Use 40..90 percent for a measurable, bounded experiment')
        capture('baseline-start')
        baseline = observe('baseline', 120, source)
        capture('baseline-end')
        # The kernel re-reads online/raw type, checks both limits and reads back.
        wrote = True  # A failed write may still have reached the firmware.
        (USB / 'input_current_limit').write_text('1500000\n')
        after_icl = record('after-icl')
        check_sample(after_icl, source)
        if after_icl['usb']['input_current_limit'] != 1500000:
            raise RuntimeError('ICL readback mismatch')
        (USB / 'constant_charge_current').write_text('2000000\n')
        after_fcc = record('after-fcc')
        check_sample(after_fcc, source)
        if after_fcc['usb']['constant_charge_current'] != 2000000:
            raise RuntimeError('FCC readback mismatch')
        rows = observe('written', 300, source)
        tail = [r for r in rows if r['monotonic'] >= rows[-1]['monotonic'] - 60]
        currents = {p.name: statistics.median(r['batteries'][p.name]['current_now'] for r in tail)
                    for p in gauges}
        start_pct = sum(b['capacity'] for b in baseline[-1]['batteries'].values()) / 2
        end_pct = sum(b['capacity'] for b in rows[-1]['batteries'].values()) / 2
        passed = all(i > 0 for i in currents.values()) and end_pct > start_pct
        result.update(status='PASS' if passed else 'FAIL_CRITERIA_NOT_MET', usb_type=source,
                      final_minute_median_ua=currents, start_percent=start_pct, end_percent=end_pct,
                      baseline_net_ua=statistics.median(sum(b['current_now'] for b in r['batteries'].values())
                                                        for r in baseline))
    except Exception as exc:
        result.update(status='ABORT', error=str(exc))
    finally:
        capture('end')
        trace.flush()
        os.fsync(trace.fileno())
        trace.close()
        (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        os.sync()
        print(json.dumps(result, indent=2), flush=True)
        if wrote:
            print('Rebooting to restore firmware defaults and the installed driver.', flush=True)
            subprocess.run(['systemctl', 'reboot'], check=True)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
