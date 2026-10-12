#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Judge saved piano cold-boot captures, or collect two over developer SSH.

Only `run` contacts a device. Missing evidence is UNAVAILABLE, never PASS.
The captured UPTIME, not a filename or journal receive time, sets the window.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import piano_boot_acceptance as acceptance

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('piano_native_capture', TOOLS / 'piano-native-display-capture.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
LATE_SECONDS = 200


def fields(text, key):
    # Anchoring excludes echoed shell source, including echo KEY=$(command).
    return re.findall(r'^' + re.escape(key) + r'=([^\r\n]+)$', text, re.M)


def number(text, key):
    values = fields(text, key)
    if len(values) != 1:
        return None
    try:
        value = float(values[0])
        return value if math.isfinite(value) and value >= 0 else None
    except ValueError:
        return None


def one(text, key):
    values = fields(text, key)
    return values[0] if len(values) == 1 else None


def judge(early, late=None, expected_release='7.2.6-piano8'):
    """Return data only; accepts capture text, never opens a device or a path."""
    captures = [('early', acceptance.clean(early))]
    if late is not None:
        captures.append(('late', acceptance.clean(late)))
    rows = []

    def add(name, checks, budget):
        # A known failure wins over missing evidence; later PASS cannot erase it.
        states = [ok for _, _, ok in checks]
        status = 'FAIL' if False in states else 'UNAVAILABLE' if None in states or not states else 'PASS'
        values = {label: value for label, value, _ in checks}
        measured = '; '.join(f'{label}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}'
                             for label, value, _ in checks)
        rows.append(dict(name=name, status=status, required=True, value=values,
                         measured=measured, budget=budget))

    def per_capture(name, measure, budget):
        add(name, [(label, *measure(text)) for label, text in captures], budget)

    def numeric(key, predicate):
        def measure(text):
            value = number(text, key)
            return value, None if value is None else predicate(value)
        return measure

    per_capture('capture_complete', lambda text: (
        [marker for marker in ('NATIVE_CAPTURE_DONE', 'PIANO8_INTEGRATION_DONE')
         if re.search(r'^' + marker + r'$', text, re.M)],
        True if all(re.search(r'^' + marker + r'$', text, re.M)
                    for marker in ('NATIVE_CAPTURE_DONE', 'PIANO8_INTEGRATION_DONE')) else None),
        'native and piano8 completion markers in every capture')
    identities = [{key: one(text, key) for key in ('BOOT_ID', 'UNAME', 'WHERE', 'EUID')}
                  for _, text in captures]
    identity_ok = None if any(v is None for i in identities for v in i.values()) else (
        all(i['WHERE'] == 'root' and i['EUID'] == '0' for i in identities)
        and len({i['BOOT_ID'] for i in identities}) == 1
        and len({i['UNAME'] for i in identities}) == 1)
    add('capture_identity', [('captures', identities, identity_ok)],
        'root captures from the same BOOT_ID and kernel release')
    uptimes = [number(text, 'UPTIME') for _, text in captures]
    window = None
    if len(uptimes) == 2 and all(t is not None for t in uptimes):
        window = False if uptimes[1] <= uptimes[0] else True if uptimes[1] >= LATE_SECONDS else None
    add('late_observation', [('uptime_s', uptimes, window)],
        'two captures, increasing UPTIME; second >= 200 s (short/missing window: UNAVAILABLE)')

    def milestone(pattern, budget, strict=False):
        def measure(text):
            # journal kernel timestamps before switch_root are receive times.
            values = [t for kind, t, msg in acceptance.kernel_lines(text)
                      if kind == 'dmesg' and re.search(pattern, msg)]
            values += [t for t, msg in acceptance.kmsg_records(text).values() if re.search(pattern, msg)]
            value = min(values) if values else None
            return value, None if value is None else value < budget if strict else value <= budget
        return measure

    per_capture('simpledrm_init', milestone(r'^\[drm\] Initialized simpledrm', 1, True),
                'first kernel timestamp < 1 s; journal receive times excluded')
    per_capture('switch_root', numeric('UserspaceTimestampMonotonic', lambda v: 0 < v <= 10_000_000),
                '0 < UserspaceTimestampMonotonic <= 10000000 us (10 s)')

    def gdm(text):
        # The first ActiveState/ActiveEnter pair is gdm; the later one is SSH.
        header = text.split('KLOG=', 1)[0]
        state, value = one(header, 'ActiveState'), number(header, 'ActiveEnterTimestampMonotonic')
        ok = False if state is not None and state != 'active' else (
            None if state is None or value is None else 0 < value <= 20_000_000)
        return {'state': state, 'monotonic_us': value}, ok
    per_capture('gdm_active', gdm, 'active; 0 < ActiveEnterTimestampMonotonic <= 20000000 us (20 s)')
    per_capture('gmu_first_load', milestone(r'^\[drm\] Loaded GMU firmware', 20),
                'first kernel timestamp <= 20 s')

    def zeros(keys):
        def measure(text):
            values = {k: number(text, k) for k in keys}
            ok = False if any(v is not None and v != 0 for v in values.values()) else (
                None if any(v is None for v in values.values()) else True)
            return values, ok
        return measure
    per_capture('gpu_errors', zeros(['GPU_ERR'] + [f'count[{k}]' for k in acceptance.GPU_ERRORS]),
                'GPU_ERR / GMU timeout / OOB / hangcheck all 0; late_observation required')
    per_capture('clock_dsi_warnings', zeros(['PIANO8_CLOCK_WARNINGS', 'NATIVE_DSI_ERRORS']),
                'clock/DSI warnings 0 in every capture; late_observation required')

    def copies(text):
        # Match the benchmark section, not an unrelated throughput number.
        values = [int(v) for v in re.findall(
            r'^== bench python 256 MiB buffer copy x8\nmemcpy_s [\d.]+ iters [1-8] MBps (\d+)$', text, re.M)]
        return values, all(v >= acceptance.BUDGETS['copy_mbps'] for v in values) if values else None
    per_capture('copy_256mib', copies, 'every 256 MiB memcpy >= 2000 MB/s (capture benchmark units)')

    def clock(text):
        v = acceptance.hf_axi([acceptance.console('capture', text)])
        bad = (any(c['enable'] < 1 or c['hw'] != 'Y' or c['consumer'] not in native.HF_AXI_CONSUMERS
                   for c in v['rows']) or any(not r & 1 or r & (1 << 31) for r in v['cbcr']))
        return v, False if bad else True if v['rows'] and v['cbcr'] else None
    per_capture('hf_axi_held', clock, 'every clk row held, hardware Y; every CBCR bit0=1, bit31=0')

    def scanout(text):
        intfs = native.native_intfs(text)
        bad = any(not i['advancing'] or i['timing_en'] != 1 or not i['intr_same']
                  or i['sample_s'] != 0.5 or not 70 <= i['frames'] <= 74 for i in intfs)
        complete = {i['name'] for i in intfs} == {'INTF1', 'INTF2'}
        return intfs, False if bad else True if complete else None
    per_capture('scanout', scanout, 'INTF1 AND INTF2: +72 +/- 2 frames / 0.5 s; enabled, interrupts unchanged')
    per_capture('modules_own_release', zeros(['MOD_OUTSIDE', 'MOD_NOFILE']), 'MOD_OUTSIDE=0 AND MOD_NOFILE=0')

    def failed(text):
        count, state = number(text, 'FAILED_COUNT'), one(text, 'SYSTEM_STATE')
        ok = False if (count is not None and count != 0) or (state is not None and state != 'running') else (
            None if count is None or state is None else True)
        return {'FAILED_COUNT': count, 'SYSTEM_STATE': state}, ok
    per_capture('failed_units', failed, 'FAILED_COUNT=0 AND SYSTEM_STATE=running')

    def controls(text):
        expected = {'PIANO8_RELEASE': expected_release, 'PIANO8_KEYBOARD_MODULE': 'present',
                    'PIANO8_MCA_MODULE': 'present', 'PIANO8_MCA_SUPPLY': 'present'}
        values = {key: one(text, key) for key in expected}
        bad = any(v not in (None, 'UNAVAILABLE', expected[k]) for k, v in values.items())
        if values['PIANO8_RELEASE'] is not None and one(text, 'UNAME') != values['PIANO8_RELEASE']:
            bad = True
        return values, False if bad else None if any(v in (None, 'UNAVAILABLE') for v in values.values()) else True
    per_capture('piano8_controls', controls, f'PIANO8_RELEASE=UNAME={expected_release}; keyboard/MCA/supply present')
    per_capture('wayland_session', numeric('PIANO8_ACTIVE_WAYLAND_USERS', lambda v: v == 1),
                'exactly 1 active Class=user, Type=wayland session')
    # Legacy late capture lacks /proc/asound/cards; registration in either
    # capture of the same boot suffices, but an explicit empty card list fails.
    sound_checks = []
    for label, text in captures:
        match = re.search(r'^== sound\n(.*?)(?=^== |\Z)', text, re.M | re.S)
        if match:
            values = re.findall(r'^\s*\d+ \[([^\]\n]+)\s*\]:[^\n]+', match[1], re.M)
            sound_checks.append((label, values, bool(values)))
    add('sound_card', sound_checks or [('cards', None, None)], 'ALSA card present in this boot (/proc/asound/cards)')

    def thp(text):
        first, error = number(text, 'THP_FIRST'), number(text, 'THP_ERR')
        logged = any('THP first frame' in msg for _, _, msg in acceptance.kernel_lines(text))
        ok = False if error is not None and error != 0 or first == 0 else (
            None if first is None or error is None or not logged else True)
        return {'first': first, 'errors': error, 'logged': logged}, ok
    per_capture('thp_first_frame', thp, 'THP first frame logged, THP_FIRST > 0 AND THP_ERR=0')
    failures = [r['name'] for r in rows if r['status'] == 'FAIL']
    missing = [r['name'] for r in rows if r['status'] == 'UNAVAILABLE']
    return {'schema': 1, 'profile': expected_release.split('-')[-1] + '-cold-boot', 'expected_release': expected_release,
            'criteria': rows, 'failed': failures,
            'unavailable': missing, 'verdict': 'FAIL' if failures else 'UNAVAILABLE' if missing else 'PASS',
            'scope': 'Saved cold-boot readings; no visual, physical input, charging or continuous clock proof.'}


def report(verdict):
    print('Criterion | Status | Measured | Budget')
    print('--- | --- | --- | ---')
    for row in verdict['criteria']:
        print(' | '.join(str(row[k]).replace('|', '\\|') for k in ('name', 'status', 'measured', 'budget')))
    print('\n' + json.dumps(verdict, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if verdict['verdict'] == 'PASS' else 1


def password_from_input():
    path = os.environ.get('PIANO_SUDO_PASSWORD_FILE')
    if path:
        password = Path(path).read_bytes()
    else:
        password = sys.stdin.buffer.readline()
    password = password.removesuffix(b'\n').removesuffix(b'\r')
    if not password or any(c in password for c in (b'\n', b'\r', b'\0')):
        raise ValueError('sudo password must be one nonempty line on stdin or in PIANO_SUDO_PASSWORD_FILE')
    return password + b'\n'


def save(path, data):
    # Never overwrite evidence; raw captures can contain per-device identities.
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def run_captures(args, password, run=subprocess.run):
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    script = native.cold_boot_script()
    texts, transport = [], []
    env = dict(os.environ)
    env.pop('PIANO_SUDO_PASSWORD_FILE', None)
    for label in ('early', 'late'):
        payload = 'exec </dev/null\n' + script
        timeout = 120
        if label == 'late':
            uptime = number(texts[0], 'UPTIME')
            if uptime is None:
                transport.append('early capture has no valid UPTIME; late capture not attempted')
                break
            # Use actual device uptime, not a host sleep or a nominal filename.
            # One wait, no reconnect/retry; judge verifies BOOT_ID afterwards.
            payload = ("exec </dev/null\npython3 - <<'PIANO_COLD_WAIT'\nimport time\nfrom pathlib import Path\n"
                       f"time.sleep(max(0, {args.late_seconds} - float(Path('/proc/uptime').read_text().split()[0])))\n"
                       "PIANO_COLD_WAIT\n" + script)
            timeout += args.late_seconds
        # Script is shell-quoted in argv; ONLY the password is on stdin. This
        # also works with cached sudo/NOPASSWD: unread password is never code.
        command = [sys.executable, str(TOOLS / 'piano-devmode-ssh.py'), '--serial', args.serial,
                   args.user, "sudo -k -S -p '' bash -c " + shlex.quote(payload)]
        print(f'Capturing {label}' + (f' at uptime >= {args.late_seconds:g} s' if label == 'late' else ''),
              file=sys.stderr, flush=True)
        try:
            result = run(command, input=password, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         timeout=timeout, env=env)
            stdout, stderr, rc = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, rc = exc.stdout or b'', exc.stderr or b'', 'timeout'
        # Do not let unexpected SSH diagnostics persist the supplied secret.
        secret = password.rstrip(b'\r\n')
        stderr = stderr.replace(secret, b'<PASSWORD>')
        save(args.out / f'capture-{label}.txt', stdout)
        save(args.out / f'capture-{label}.stderr.txt', stderr)
        texts.append(stdout.decode('utf-8', errors='replace'))
        if rc != 0:
            transport.append(f'{label} capture SSH/sudo exit: {rc}')
            break
    verdict = judge(texts[0] if texts else '', texts[1] if len(texts) > 1 else None, args.kernel_release)
    if transport:
        verdict['criteria'].append(dict(name='capture_transport', status='FAIL', required=True,
            value=transport, measured='; '.join(transport), budget='both SSH/sudo captures exit 0'))
        verdict['failed'].append('capture_transport')
        verdict['verdict'] = 'FAIL'
    verdict['capture_script_sha256'] = hashlib.sha256(script.encode()).hexdigest()
    save(args.out / 'verdict.json', (json.dumps(verdict, ensure_ascii=False, indent=2) + '\n').encode())
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    check = sub.add_parser('judge', help='host-only replay; incomplete evidence exits 1')
    check.add_argument('capture_early', type=Path)
    check.add_argument('capture_late', type=Path, nargs='?')
    live = sub.add_parser('run', help='two read-only captures on the selected developer-mode USB link')
    live.add_argument('--serial', required=True)
    live.add_argument('--user', required=True)
    live.add_argument('--out', type=Path, required=True, help='new private output directory')
    live.add_argument('--late-seconds', type=float, default=LATE_SECONDS, help='second capture uptime, >=200 (default 200)')
    for command in (check, live):
        command.add_argument('--kernel-release', default='7.2.6-piano8',
                             help='required kernel release (default: 7.2.6-piano8)')
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-piano[1-9][0-9]*', args.kernel_release):
            parser.error('invalid --kernel-release')
        if args.action == 'judge':
            verdict = judge(args.capture_early.read_text(), args.capture_late.read_text() if args.capture_late else None,
                            args.kernel_release)
        else:
            if not math.isfinite(args.late_seconds) or not LATE_SECONDS <= args.late_seconds <= 3600:
                parser.error('--late-seconds must be between 200 and 3600')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.serial):
                parser.error('invalid --serial')
            if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.-]*', args.user):
                parser.error('invalid --user')
            verdict = run_captures(args, password_from_input())
        return report(verdict)
    except (OSError, ValueError) as exc:
        print(f'piano-cold-boot-accept: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
