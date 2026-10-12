#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One attended wall-charger experiment, run locally on installed piano Ubuntu.

Launch from developer-mode SSH in a transient systemd service before moving the
cable to a wall charger. This is a finite diagnostic, not a charging service.
The legacy 5 V baseline requires masked ICL automation. --community-policy
observes the pre-enabled piano8 policy without issuing current writes. After a write attempt,
reboot resets the firmware; output is flushed to persistent storage first.
"""
import argparse
import hashlib
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
    row = {'monotonic': time.monotonic(), 'uptime': Path('/proc/uptime').read_text().split()[0],
            'usb_type': types[0],
            'usb': {p: integer(USB / p) for p in ('online', 'voltage_now', 'current_now',
                                                 'input_current_limit', 'constant_charge_current')},
            'batteries': {p.name: {k: integer(p / k) for k in ('capacity', 'current_now',
                                                              'voltage_now', 'temp')}
                          for p in gauges}}
    relay = USB / 'xiaomi/real_type'
    if relay.is_file():
        row['charger_type'] = relay.read_text().strip()
    cp = SUPPLIES / 'sc8541'
    if cp.is_dir():
        row['sc8541'] = {'online': integer(cp / 'online')}
        if row['sc8541']['online']:
            row['sc8541'].update({k: integer(cp / k) for k in
                                 ('current_now', 'voltage_now', 'temp', 'input_current_limit')})
    return row


def check_sample(s, source, community=False):
    if not s['usb']['online'] or (s['usb_type'] not in {'PD', 'PD_PPS'} if community else s['usb_type'] != source):
        raise RuntimeError('Wall source detached or changed type')
    # Measurement window for this 5 V experiment, not a charger setting.
    if not 4500000 <= s['usb']['voltage_now'] <= (10000000 if community else 5500000):
        raise RuntimeError('VBUS outside the experiment window')
    if community:
        hv = 8000000 <= s['usb']['voltage_now'] <= 9600000
        icl_max = (2500000 if s.get('charger_type') == 'PD_PPS' else 1600000) if hv else 1500000
        if not 100000 <= s['usb']['input_current_limit'] <= icl_max:
            raise RuntimeError("ICL request outside this unit's ceiling")
        if not 100000 <= s['usb']['constant_charge_current'] <= (3000000 if hv else 2000000):
            raise RuntimeError("FCC request outside this unit's ceiling")
        cp = s.get('sc8541', {})
        if cp.get('online') and (cp['temp'] >= 800 or cp['current_now'] > 5500000):
            raise RuntimeError('SC8541 outside the bounded test window')
    if any(not 150 <= b['temp'] < 450 for b in s['batteries'].values()):
        raise RuntimeError('Battery outside the attended 15..45 C test window')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--serial', required=True)
    ap.add_argument('--output', type=Path, help='New persistent directory, e.g. /var/log/piano-charging-01')
    ap.add_argument('--attended-wall-charger', action='store_true',
                    help='Operator present, wall charger available, cable will be moved')
    ap.add_argument('--community-policy', action='store_true', help='Observe the piano8 policy; do not write ICL/FCC manually')
    ap.add_argument('--allow-high-soc', action='store_true', help='Allow 91..100 percent; rising-percent PASS may be impossible')
    ap.add_argument('--preflight-only', action='store_true', help='Check identity and 40..90 percent before booting the candidate')
    args = ap.parse_args()
    if not args.preflight_only and (args.output is None or not args.attended_wall_charger):
        ap.error('--output and --attended-wall-charger are required for an experiment')
    # Reuse the installed device-support identity checks; no storage operations.
    sys.path.insert(0, '/usr/lib/piano/boot')
    from piano_bootslot import Host, require_piano, firmware_serial
    host = Host()
    host.require_root()
    require_piano(host)
    if firmware_serial(host) != args.serial:
        raise RuntimeError('Firmware serial does not match --serial')
    gauges = sorted(p for p in SUPPLIES.glob('bq27z561-*') if p.is_dir())
    if len(gauges) != 2:
        raise RuntimeError('Expected both bq27z561 gauges')
    capacity = {p.name: integer(p / 'capacity') for p in gauges}
    if any(v < 40 or v > (100 if args.allow_high_soc else 90) for v in capacity.values()):
        raise RuntimeError('Use 40..90 percent; --allow-high-soc only overrides the upper guard')
    if args.preflight_only:
        print(json.dumps({'preflight': 'PASS', 'capacity': capacity, 'allow_high_soc': args.allow_high_soc}))
        return 0
    identity = {}
    if args.community_policy:
        manifest = json.loads(Path(__file__).resolve().with_name('manifest.json').read_text())
        if os.uname().release != '7.2.6-piano8':
            raise RuntimeError('Community test requires the matching piano8 candidate')
        for kind, path in [('image', Path('/boot/vmlinuz-7.2.6-piano8')),
                           ('config', Path('/boot/config-7.2.6-piano8'))]:
            with path.open('rb') as stream:
                identity[kind + '_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
            if identity[kind + '_sha256'] != manifest['kernel'][kind + '_sha256']:
                raise RuntimeError('Installed candidate ' + kind + ' hash mismatch')
        identity['kernel_commit'] = manifest['kernel']['commit']
        identity['proc_version'] = Path('/proc/version').read_text().strip()
        for knob in ('charge_policy', 'hv_charge', 'charge_current', 'mipps_auth', 'cp_charge'):
            if Path('/sys/module/xiaomi_mca/parameters', knob).read_text().strip() != 'Y':
                raise RuntimeError('Community policy is not enabled: ' + knob)
    if not args.community_policy and Path('/sys/module/xiaomi_mca/parameters/charge_policy').exists():
        raise RuntimeError('Use --community-policy on a policy-capable kernel; do not mix the legacy 5 V writer')
    mask = Path('/run/udev/rules.d/80-piano-charging.rules')
    if not args.community_policy and (not mask.is_symlink() or str(mask.readlink()) != '/dev/null'):
        raise RuntimeError('Mask 80-piano-charging.rules in /run and reload udev before the baseline')
    if args.output.resolve().is_relative_to('/run') or args.output.resolve().is_relative_to('/tmp'):
        raise RuntimeError('Output must survive the concluding reboot')
    debug_dirs = list(Path('/sys/kernel/debug').glob('pmic_glink.xiaomi-mca*'))
    if len(debug_dirs) != 1 or any(not (debug_dirs[0] / f).is_file() for f in ('status', 'stats', 'frames')):
        raise RuntimeError('Mount debugfs and load the candidate before collecting MCA evidence')
    args.output.mkdir(parents=True, exist_ok=False)
    wrote = False
    result = {'status': 'NOT_RUN', 'kernel': os.uname().release, 'serial': args.serial,
              'community_policy': args.community_policy, 'allow_high_soc': args.allow_high_soc,
              'candidate_identity': identity,
              'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    trace = (args.output / 'samples.jsonl').open('x', buffering=1)

    def record(phase):
        s = sample(gauges)
        trace.write(json.dumps(dict(phase=phase, **s)) + '\n')
        return s

    def capture(name):
        with (args.output / (name + '-dmesg.txt')).open('w') as log:
            subprocess.run(['dmesg'], stdout=log, stderr=subprocess.STDOUT, check=False)
        if args.community_policy:
            with (args.output / (name + '-auth-journal.txt')).open('w') as log:
                subprocess.run(['journalctl', '-b', '-u', 'xiaomi-mipps-auth.service', '--no-pager'],
                               stdout=log, stderr=subprocess.STDOUT, check=False, timeout=15)
            for supply in (USB / 'xiaomi', SUPPLIES / 'sc8541'):
                for leaf in ('pd_verifed', 'verify_process', 'adapter_svid', 'online', 'voltage_now',
                             'current_now', 'temp', 'input_current_limit'):
                    try:
                        (args.output / f'{name}-{supply.name}-{leaf}.txt').write_text((supply / leaf).read_text())
                    except OSError:
                        pass
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
            check_sample(s, source, args.community_policy)
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
        check_sample(s, source, args.community_policy)
        if any(b['capacity'] < 40 or b['capacity'] > (100 if args.allow_high_soc else 90) for b in s['batteries'].values()):
            raise RuntimeError('Use 40..90 percent for a measurable, bounded experiment')
        if args.community_policy:
            capture('policy-start')
            rows = observe('community-policy', 600, source)
            tail = [r for r in rows if r['monotonic'] >= rows[-1]['monotonic'] - 60]
            currents = {p.name: statistics.median(r['batteries'][p.name]['current_now'] for r in tail)
                        for p in gauges}
            start_pct = sum(b['capacity'] for b in rows[0]['batteries'].values()) / 2
            end_pct = sum(b['capacity'] for b in rows[-1]['batteries'].values()) / 2
            auth_log = subprocess.check_output(['journalctl', '-b', '-u', 'xiaomi-mipps-auth.service',
                                                '--no-pager', '-o', 'cat'], text=True, timeout=15)
            authenticated = integer(USB / 'xiaomi/pd_verifed') == 1 and 'pd_auth=1' in auth_log
            passed = all(v > 0 for v in currents.values()) and end_pct > start_pct and authenticated
            result.update(status='PASS' if passed else 'FAIL_CRITERIA_NOT_MET',
                          authenticated=authenticated, final_minute_median_ua=currents,
                          start_percent=start_pct, end_percent=end_pct)
        else:
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
