#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline tests of speaker-playback-check.py on synthetic device logs."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('spk', HERE / 'speaker-playback-check.py')
spk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spk)

AMPS = [('Top Left', '35'), ('Top Right', '37'), ('Bottom Left', '34'), ('Bottom Right', '36')]


def make_log(devid='2900', vol=160, vmax=215, rc=0, t1=103.1, watchdog=False,
             play_pwr='0000', play_sys='00ef', play_dig='0002', after_pwr='0001',
             status=('0f43', '0f43'), odd_status=None, before=-300, play=-420, after=-305,
             noise=5, dmesg=()):
    out = ['start uptime=90.00 kernel=7.2.6-piano6',
           'card index=0 id=XiaomiPad8Pro', 'pcm0p present=1']
    for pos, a in AMPS:
        out.append(f'amp addr=0x{a} pos="{pos}" bound=1 dev=0-00{a}')
    for pos, a in AMPS:
        out.append(f'regs tag=idle addr=0x{a} t=91.0 r00=0f00 r03={devid} r04=00a1 '
                   f'r06=0000 r10=0001 r11=0000 r16=c0c0 r17=980b')
    for pos, a in AMPS:
        out.append(f'volume pos="{pos}" max={vmax} value={vol}')
    out.append('route set=1')
    for i in range(15):
        out.append(f'gauge tag=before t={92 + i / 5:.2f} bq27z561-0={(before // 2 + (noise if i % 2 else -noise)) * 1000} '
                   f'bq27z561-1={(before // 2) * 1000}')
    out.append('aplay pid=1234 t0=100.0')
    for k, s in enumerate(status):
        for pos, a in AMPS:
            st = odd_status if (odd_status and a == '36' and k == 1) else s
            out.append(f'regs tag=play addr=0x{a} t={100.6 + k:.1f} r00={st} r03={devid} r04=00a1 '
                       f'r06={play_dig} r10={play_pwr} r11={play_sys} r16=a0c0 r17=980b')
        if k == 0:
            for i in range(9):
                out.append(f'gauge tag=play t={100.7 + i / 5:.2f} bq27z561-0={(play // 2) * 1000} '
                           f'bq27z561-1={(play // 2) * 1000}')
    if watchdog:
        out.append('watchdog fired=1 t=105.0')
    out.append(f'aplay rc={rc} t1={t1}')
    out.append('pcm status=closed')
    for i in range(15):
        out.append(f'gauge tag=after t={104 + i / 5:.2f} bq27z561-0={(after // 2) * 1000} '
                   f'bq27z561-1={(after // 2 + (noise if i % 2 else -noise)) * 1000}')
    for pos, a in AMPS:
        out.append(f'regs tag=after addr=0x{a} t=107.0 r00=0f00 r03={devid} r04=00a1 '
                   f'r06=0000 r10={after_pwr} r11=0000 r16=a0c0 r17=980b')
    out.extend(f'dmesg [  101.000000] {d}' for d in dmesg)
    out.append('end uptime=108.0')
    return '\n'.join(out) + '\n'


def verdict(text, **kw):
    return spk.judge(spk.parse(text), kw.get('min_delta_ma', 50.0))


CASES = [
    ('pass', {}, 'PASS', None),
    ('devid', {'devid': '1700'}, 'FAIL', 'devid'),
    ('volume above unattended', {'vol': 200}, 'FAIL', 'volume_cap'),
    ('kernel cap missing', {'vmax': 255}, 'FAIL', 'volume_cap'),
    ('aplay error', {'rc': 1}, 'FAIL', 'aplay'),
    ('short stream', {'t1': 101.0}, 'FAIL', 'aplay'),
    ('watchdog', {'watchdog': True}, 'FAIL', 'watchdog_not_fired'),
    ('amp powered down in play', {'play_pwr': '0001'}, 'FAIL', 'amps_running'),
    ('dac not running', {'play_dig': '0000'}, 'FAIL', 'amps_running'),
    ('not shut down after', {'after_pwr': '0000'}, 'FAIL', 'amps_shut_down_after'),
    ('one amp status differs', {'odd_status': '0f63'}, 'FAIL', 'status_consistent'),
    ('dsp error', {'dmesg': ['q6apm-dai 3000000.remoteproc:glink-edge:gpr:service@1:dais: '
                             'DSP returned error[100100f] 1']}, 'FAIL', 'kernel_log'),
    ('no current change', {'play': -302}, 'FAIL', 'current_proxy'),
    ('noisy current', {'noise': 80}, 'INCONCLUSIVE', 'current_proxy'),
    ('charging, less charge while playing', {'before': 500, 'play': 380, 'after': 498}, 'PASS', None),
]


def main():
    failed = 0
    for name, kw, want, key in CASES:
        r = verdict(make_log(**kw))
        ok = r['verdict'] == want and (key is None or r['checks'][key]['result'] == want)
        if want == 'PASS':
            ok = ok and all(c['result'] == 'PASS' for c in r['checks'].values())
        print(f"{'ok ' if ok else 'BAD'} {name}: {r['verdict']}"
              + ('' if ok else ' ' + json.dumps({k: v['result'] for k, v in r['checks'].items()})))
        failed += not ok

    with tempfile.TemporaryDirectory() as d:
        tone = Path(d) / 'tone.wav'
        p = subprocess.run([sys.executable, str(HERE / 'speaker-playback-check.py'), 'tone', str(tone)],
                           capture_output=True, text=True)
        info = json.loads(p.stdout)
        with wave.open(str(tone)) as w:
            shape = (w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes())
        ok = p.returncode == 0 and shape == (4, 48000, 2, 144000) and -20.1 < info['peak_dbfs'] <= -20.0
        print(f"{'ok ' if ok else 'BAD'} tone: {shape} peak {info['peak_dbfs']} dBFS")
        failed += not ok
        for extra in (['--level-dbfs', '-10'], ['--seconds', '10']):
            p = subprocess.run([sys.executable, str(HERE / 'speaker-playback-check.py'), 'tone',
                                str(Path(d) / 'x.wav')] + extra, capture_output=True, text=True)
            ok = p.returncode != 0 and not (Path(d) / 'x.wav').exists()
            print(f"{'ok ' if ok else 'BAD'} tone refuses {' '.join(extra)}")
            failed += not ok
        log = Path(d) / 'run.log'
        log.write_text(make_log())
        p = subprocess.run([sys.executable, str(HERE / 'speaker-playback-check.py'), 'judge', str(log)],
                           capture_output=True, text=True)
        ok = p.returncode == 0 and json.loads(p.stdout)['verdict'] == 'PASS'
        print(f"{'ok ' if ok else 'BAD'} judge CLI exit status")
        failed += not ok
        log.write_text('random text\n')
        p = subprocess.run([sys.executable, str(HERE / 'speaker-playback-check.py'), 'judge', str(log)],
                           capture_output=True, text=True)
        ok = p.returncode == 2
        print(f"{'ok ' if ok else 'BAD'} judge rejects a foreign log")
        failed += not ok

    # the device script must name all four amplifiers with their two-word positions
    probe = subprocess.run(['sh', '-c', 'eval "$(sed -n \'/^AMPS=/p\' "$0")"; for a in $AMPS; do '
                            'printf "%s|%s\\n" "$(printf %s "${a%%:*}" | tr _ " ")" "${a##*:}"; done',
                            str(HERE / 'speaker-playback-device.sh')], capture_output=True, text=True)
    want = 'Top Left|35\nTop Right|37\nBottom Left|34\nBottom Right|36\n'
    ok = probe.stdout == want
    print(f"{'ok ' if ok else 'BAD'} device script amplifier list: {probe.stdout!r}")
    failed += not ok

    total = len(CASES) + 6
    print(f'{total - failed}/{total} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
