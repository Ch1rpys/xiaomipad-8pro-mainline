#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Emit a bounded native-display capture for the existing debug-console runner,
or judge saved captures. This tool itself never connects to a device.

The external scanout probe is the existing internal piano-scanout-probe.py.
Its splash colours are retained as historical data, never native frame proof.
"""
import argparse
import json
from pathlib import Path
import re

import piano_boot_acceptance as acceptance

HF_AXI_CONSUMERS = {
    'framebuffer', 'ae96000.dsi', 'ae00000.display-subsystem',
    'ae01000.display-controller', 'mdss', 'dpu',
}
HF_AXI_RULE = ('every captured row enable >= 1, hardware Y, consumer framebuffer, ae96000.dsi or MDSS/DPU; '
               'every CBCR CLK_ENABLE=1, CLK_OFF=0; any observed disabled/unheld gap fails; '
               'PASS needs both clk_summary and CBCR evidence')
RAM_TIMING_NOTE = (
    'RAM full-module boot; persistent budgets '
    f'(switch_root ≤{acceptance.BUDGETS["switch_root_s"]:g} s, '
    f'GDM ≤{acceptance.BUDGETS["gdm_active_s"]:g} s) apply only to the cold-boot acceptance'
)

NATIVE = r'''
import ctypes, fcntl, glob, json, os, re, struct
from pathlib import Path
def read(p):
    try: return Path(p).read_text().strip()
    except OSError: return None
def ioctl(n, size): return (3 << 30) | (size << 16) | (ord('d') << 8) | n
result = {'uptime': float(Path('/proc/uptime').read_text().split()[0]),
          'connectors': {}, 'crtcs': [], 'encoders': [], 'errors': []}
for p in glob.glob('/sys/class/drm/card*-DSI-*'):
    result['connectors'][Path(p).name] = {k: read(p + '/' + k) for k in ('status', 'enabled', 'modes')}
for p in glob.glob('/sys/class/drm/card[0-9]*'):
    if not re.fullmatch(r'card\d+', Path(p).name): continue
    if Path(os.path.realpath(p + '/device/driver')).name != 'msm_dpu': continue
    try:
        fd = os.open('/dev/dri/' + Path(p).name, os.O_RDONLY)
        try:
            res = bytearray(64); fcntl.ioctl(fd, ioctl(0xa0, 64), res)
            count = struct.unpack_from('<I', res, 36)[0]
            if not 0 < count <= 16: raise ValueError('unexpected CRTC count')
            ids = ctypes.create_string_buffer(count * 4)
            struct.pack_into('<Q', res, 8, ctypes.addressof(ids))
            # Only the CRTC array has storage; do not pass nonzero counts for
            # the NULL FB/connector/encoder arrays returned by the first call.
            struct.pack_into('<4I', res, 32, 0, count, 0, 0)
            fcntl.ioctl(fd, ioctl(0xa0, 64), res)
            if struct.unpack_from('<I', res, 36)[0] != count:
                raise ValueError('CRTC list changed during query')
            for cid in struct.unpack('<' + 'I' * count, ids.raw):
                c = bytearray(104); struct.pack_into('<I', c, 12, cid)
                fcntl.ioctl(fd, ioctl(0xa1, 104), c)
                if struct.unpack_from('<I', c, 32)[0]:
                    result['crtcs'].append({'id': cid, 'card': Path(p).name,
                        'width': struct.unpack_from('<H', c, 40)[0],
                        'height': struct.unpack_from('<H', c, 50)[0],
                        'hz': struct.unpack_from('<I', c, 60)[0]})
        finally: os.close(fd)
    except (OSError, ValueError) as e: result['errors'].append(str(e))
for p in glob.glob('/sys/kernel/debug/dri/*/*/status'):
    text = read(p) or ''
    for intf, vsync, underrun, timedout in re.findall(
            r'intf:(\d+)\s+wb:-?\d+\s+vsync:\s*(\d+)\s+underrun:\s*(\d+)\s+frame_done_cnt:(\d+)', text):
        result['encoders'].append({'path': p, 'intf': int(intf), 'vsync': int(vsync),
                                   'underrun': int(underrun), 'frame_timeout': int(timedout)})
result['backlight'] = {Path(p).name: {k: read(p + '/' + k)
                         for k in ('brightness', 'actual_brightness', 'max_brightness', 'bl_power')}
                       for p in glob.glob('/sys/class/backlight/*')}
print('NATIVE_JSON=' + json.dumps(result, sort_keys=True))
'''


def script(probe):
    if '\nPIANO_NATIVE_PROBE\n' in '\n' + probe + '\n':
        raise ValueError('Probe contains the heredoc delimiter')
    # No expanded register dump: the earlier broad MDSS dump caused a TZ
    # fatal reset. Check the same MDSS/DPU runtime and genpd gates as step 2.
    gate = '''
D=/sys/devices/platform/soc@0/ae00000.display-subsystem
G=$(awk '/^mdss_gdsc /{print $2}' /sys/kernel/debug/pm_genpd/pm_genpd_summary)
echo "NATIVE_MDSS_RT=$(cat $D/power/runtime_status 2>/dev/null)"
echo "NATIVE_DPU_RT=$(cat $D/ae01000.display-controller/power/runtime_status 2>/dev/null)"
if [ "$(cat $D/power/runtime_status 2>/dev/null)" = active ] &&
   [ "$(cat $D/ae01000.display-controller/power/runtime_status 2>/dev/null)" = active ] && [ "$G" = on ]; then
'''
    return (acceptance.device_script() + "\npython3 - <<'PIANO_NATIVE_STATE'\n" + NATIVE +
            "\nPIANO_NATIVE_STATE\n" + gate +
            "python3 - <<'PIANO_NATIVE_PROBE'\n" + probe + '\nPIANO_NATIVE_PROBE\n' +
            'else echo NATIVE_SCANOUT_SKIPPED=power-not-active; fi\n' +
            'echo NATIVE_DSI_ERRORS=$(dmesg | grep -cE "dsi_err_worker|DSI.*(error|timed out)|lock failed|Unhandled context fault")\n' +
            'echo "== native resources"\ncat /sys/kernel/debug/dri/*/state 2>/dev/null\n' +
            'cat /sys/kernel/debug/pm_genpd/pm_genpd_summary\n' +
            'cat /sys/kernel/debug/interconnect/interconnect_summary\n' +
            'echo "== RAM handoff and SSH listener"\n' +
            'findmnt -T /usr/lib/modules -o TARGET,SOURCE,FSTYPE,OPTIONS\n' +
            'grep -c ": OK$" /run/piano-native-display/modules-verified.txt\n' +
            'systemctl show piano-devmode-ssh.socket -p ActiveState -p SubState -p BindsTo -p FragmentPath\n' +
            'ss -ltn\n' +
            'echo "== touch runtime log and IRQ counts"\n' +
            'journalctl -b -u piano-thp.service --no-pager -o short-monotonic -n 40\n' +
            'grep -iE "nt36532|nvt|thp" /proc/interrupts || :\n' +
            'echo "== native boot log"\njournalctl -k -b --no-pager -o short-monotonic\n' +
            'echo NATIVE_CAPTURE_DONE\n')


def judge(directory, release):
    texts = [(p.name, p.read_text(errors='replace')) for p in sorted(directory.glob('root-*.txt'))]
    args = acceptance.parse_args(['evaluate', '--dir', str(directory), '--release', release])
    raw = acceptance.run_evaluate(args)
    # Firmware-only scanout does not describe native KMS. Evaluate clock
    # ownership below using the same rule for the legacy and native row names.
    required = {'simpledrm_init', 'switch_root', 'gdm_active', 'gmu_first_load', 'gpu_errors',
                'copy_256mib', 'thp_first_frame', 'modules_own_release', 'release_in_root',
                'config_dispcc_builtin', 'rpmhpd_icc_synced', 'failed_units', 'slot_attributes'}
    rows = [dict(r, required=r['name'] in required) for r in raw['criteria']]
    mode = next(r for r in rows if r['name'] == 'mode_fast')
    timings = {k: mode['value'][k] for k in ('switch_root_s', 'gdm_active_s', 'fbcon_s')}
    measured = '; '.join(f'{name} {timings[key]:.3f} s' if timings[key] is not None
                         else f'{name} not captured'
                         for name, key in (('switch_root', 'switch_root_s'), ('GDM', 'gdm_active_s')))
    mode.update(status='INFO', value=timings, measured=RAM_TIMING_NOTE + '; ' + measured,
                budget='informational for RAM full-module boot', rule=RAM_TIMING_NOTE, required=False)

    def add(name, status, value):
        rows.append({'name': name, 'status': status, 'value': value, 'required': True})

    native, rates, underruns, dsi = [], [], [], []
    for label, text in texts:
        states = re.findall(r'^NATIVE_JSON=(.+)$', text, re.M)
        if not states:
            continue
        state = json.loads(states[-1]); native.append(state)
        modes = state['crtcs']
        modes_ok = (len(modes) == 1 and (modes[0]['width'], modes[0]['height']) == (3200, 2136)
                    and modes[0]['hz'] in (60, 90, 120, 144))
        native_ok = (modes_ok and not state['errors'] and any(
            c['status'] == 'connected' and c['enabled'] == 'enabled' for c in state['connectors'].values()))
        add('native_kms:' + label, 'PASS' if native_ok else 'FAIL', state)
        found = acceptance.INTF.findall(text)
        measured = [(v[0], int(v[4]) / float(v[5])) for v in found if float(v[5]) > 0]
        expected = modes[0]['hz'] if modes_ok else None
        ok = (expected and {i for i, _ in measured} == {'INTF1', 'INTF2'} and
              all(abs(hz - expected) <= expected * 0.05 for _, hz in measured))
        rates.append(measured)
        add('intf_rate:' + label, 'PASS' if ok else 'FAIL' if measured else 'UNAVAILABLE',
            {'expected_hz': expected, 'measured': measured})
        enc = [e for e in state['encoders'] if e['intf'] in (1, 2)]
        underruns += enc
        ok = enc and {e['intf'] for e in enc} == {1, 2} and all(
            e['vsync'] > 0 and e['underrun'] == 0 and e['frame_timeout'] == 0 for e in enc)
        add('zero_underrun:' + label, 'PASS' if ok else 'FAIL' if enc else 'UNAVAILABLE', enc)
        dsi += [int(x) for x in re.findall(r'^NATIVE_DSI_ERRORS=(\d+)$', text, re.M)]
    add('native_capture', 'PASS' if native else 'UNAVAILABLE', len(native))
    add('dsi_smmu_errors', 'PASS' if dsi and not any(dsi) else 'FAIL' if any(dsi) else 'UNAVAILABLE', dsi)
    # Require every sample to stay held, including the framebuffer -> KMS
    # handoff. A later enabled sample cannot erase an observed gap.
    for phase in ('initrd', 'root'):
        row = next(r for r in rows if r['name'] == 'hf_axi_held_' + phase)
        v = row['value'] or {}; clocks, registers = v.get('rows', []), v.get('cbcr', [])
        bad = (any(c['enable'] < 1 or c['hw'] != 'Y' or c['consumer'] not in HF_AXI_CONSUMERS
                   for c in clocks)
               or any(not int(x, 16) & 1 or int(x, 16) & (1 << 31) for x in registers))
        status = 'FAIL' if bad else 'PASS' if clocks and registers else 'UNAVAILABLE'
        row.update(status=status, rule=HF_AXI_RULE)
        add('native_hf_axi_' + phase, status, v)
    failures = [r['name'] for r in rows if r['required'] and r['status'] == 'FAIL']
    missing = [r['name'] for r in rows if r['required'] and r['status'] == 'UNAVAILABLE']
    return {'profile': 'native-display-ram', 'release': release, 'criteria': rows,
            'failed': failures, 'unavailable': missing,
            'hardware_verdict': 'FAIL' if failures else 'INCOMPLETE' if missing else 'PASS',
            'desktop_visual': 'PENDING_OPERATOR', 'brightness_slider': 'PENDING_OPERATOR',
            'dpms_off_on': 'MUST_RECORD_RESULT_SEPARATELY_D06_GAP',
            'note': 'No splash colour or process-active result counts as native desktop proof.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    emit = sub.add_parser('emit'); emit.add_argument('--scanout-probe', type=Path, required=True)
    check = sub.add_parser('judge'); check.add_argument('--dir', type=Path, required=True)
    check.add_argument('--release', required=True)
    a = p.parse_args()
    if a.action == 'emit': print(script(a.scanout_probe.read_text()))
    else: print(json.dumps(judge(a.dir, a.release), indent=2))


if __name__ == '__main__':
    main()
