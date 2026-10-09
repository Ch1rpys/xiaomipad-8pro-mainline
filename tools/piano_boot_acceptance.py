#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Acceptance criteria for a piano persistent boot or kernel update.

The criteria and their budgets are data (BUDGETS, CRITERIA, PROFILES).  They
are evaluated from saved captures, so a verdict can be replayed later from the
same evidence:

- root-phase console or SSH transcripts, in the order they were taken: the
  output of device_script(), or of the earlier measurement scripts (systemctl
  show, count[...] and KEY=value lines, dmesg excerpts, the 256 MiB copy,
  clk_summary rows, GCC_DISP_HF_AXI_CBCR reads, scanout probe output);
- the first initrd console (output of initrd_script());
- a host capture of /dev/kmsg, one '<host time> <prio>,<seq>,<usec>,<flags>;<text>'
  record per line, and/or a `journalctl -b -o short-monotonic` export;
- Fastboot getvar output before and after the session.

Every criterion is PASS, FAIL or UNAVAILABLE with its measured value.  A missing
or unparsable input gives UNAVAILABLE, never FAIL; FAIL needs a reading that
breaks the budget.  Console transcripts may contain echoed script text and
typed-ahead input in front of an output marker, so markers are never anchored
to the start of a line and a value never starts with '$'.

`live` runs device_script() once over the developer-mode SSH link
(piano-devmode-ssh.py), saves the transcript and evaluates it.  Debug-console
runners send initrd_script() and device_script() over their own console and
pass the transcripts to evaluate().  The scripts only read: /proc, sysfs,
debugfs, the kernel log, `piano-boot-switch status`, one register through
busybox devmem and (optionally) the scanout probe's /dev/mem reads; they copy
a 256 MiB buffer in RAM.  The initrd script mounts debugfs when it is absent.
"""
import argparse
import dataclasses
import getpass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

PASS, FAIL, UNAVAILABLE = 'PASS', 'FAIL', 'UNAVAILABLE'

# Budgets of the 2026-10-09 piano2 acceptance (7.2.6-piano2, CONFIG_SM_DISPCC_8750=y).  Measured
# then: switch-root 7.3-7.6 s, gdm 13.6-14.6 s, GMU 15.2-16.3 s, copy >= 5.3 GB/s.  The slow state
# (dispcc as a module; GCC_DISP_HF_AXI_CLK switched off by clk_disable_unused at ~2.6 s) measured
# switch-root 20-24 s, gdm 85-122 s and copy 36-47 MB/s, and the earlier "fast" state 15.5-17.2 s and
# 22-24 s: both are outside these budgets.
BUDGETS = {
    'simpledrm_init_s': 1.0,       # less than: first '[drm] Initialized simpledrm', kernel time
    'switch_root_s': 10.0,         # at most: systemd UserspaceTimestampMonotonic
    'gdm_active_s': 20.0,          # at most: gdm ActiveEnterTimestampMonotonic
    'gmu_loaded_s': 20.0,          # at most: first '[drm] Loaded GMU firmware'
    'gpu_window_s': 180.0,         # GPU error counts must cover at least this uptime ("~200 s")
    'copy_mbps': 2000,             # at least, every 256 MiB RAM copy reading
    'scanout_hz': (100.0, 140.0),  # INTF1 and INTF2 frame counters of the 120 Hz panel
    'scanout_distinct': 5,         # at least this many colours among the splash samples
    'scanout_top_rgb': '222222',   # most common sampled colour: the GDM greeter background
    # Slow-state signature; any one classifies the boot SLOW.
    'slow_switch_root_s': 18.0,
    'slow_fbcon_s': 0.5,           # simpledrm initialised -> fb0 registered
    'slow_gdm_by_s': 40.0,
}
GPU_ERRORS = ('GMU firmware initialization timed out', 'OOB', 'hangcheck')
THP_ERRORS = re.compile(r'SPI transfer timed|GPI.*timeout|THP SPI read')
RPMHPD_SYNCED = '/sys/devices/platform/soc@0/16500000.rsc/16500000.rsc:power-controller/state_synced'
HF_AXI_CBCR = 0x00127008     # gcc-sm8750.c: GCC_DISP_HF_AXI_CBCR, bit 0 CLK_ENABLE, bit 31 CLK_OFF
BUSYBOX = '/usr/libexec/piano/busybox'
HELPER = Path(__file__).with_name('piano-devmode-ssh.py')
PROBE_EOF = 'PIANO_SCANOUT_PROBE_EOF'


# ------------------------------------------------------------------ device-side scripts
INITRD_SCRIPT = rf'''B={BUSYBOX}
echo "== piano boot acceptance initrd read"
echo "WHERE=$(if [ -e /etc/initrd-release ]; then echo initrd; else echo root; fi)"
echo "UPTIME=$($B cut -d' ' -f1 /proc/uptime)"
[ -e /sys/kernel/debug/clk/clk_summary ] || $B mount -t debugfs none /sys/kernel/debug 2>/dev/null
$B grep -E '^ *gcc_disp_hf_axi_clk ' /sys/kernel/debug/clk/clk_summary
for i in 1 2; do
  v=$($B devmem 0x{HF_AXI_CBCR:08x} 32)
  echo "REG t=$($B cut -d' ' -f1 /proc/uptime) hf_axi_cbcr=$v"
  $B sleep 0.5
done
$B dmesg | $B grep -E '\[drm\] Initialized simpledrm|fb0: simpledrmdrmfb|clk: Disabling unused clocks'
echo "== acceptance read done"
'''

ROOT_SCRIPT = rf'''set -u
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin
B={BUSYBOX}
echo "== piano boot acceptance read"
echo "UPTIME=$(cut -d' ' -f1 /proc/uptime)"
echo "BOOT_ID=$(cat /proc/sys/kernel/random/boot_id)"
echo "WHERE=$(if [ -e /etc/initrd-release ]; then echo initrd; else echo root; fi)"
echo "UNAME=$(uname -r)"
echo "EUID=$(id -u)"
systemctl show -p InitRDTimestampMonotonic -p UserspaceTimestampMonotonic -p FinishTimestampMonotonic
systemctl show -p ActiveState -p ActiveEnterTimestampMonotonic gdm
if dmesg >/dev/null 2>&1; then K=dmesg
elif [ "$(journalctl -k -b -q --no-pager -n 1 2>/dev/null | wc -l)" -gt 0 ]; then K=journal
else K=none; fi
klog() {{ if [ "$K" = dmesg ]; then dmesg; else journalctl -k -b --no-pager -o short-monotonic; fi; }}
echo "KLOG=$K"
if [ "$K" != none ]; then
  echo "== kernel milestones"
  klog | grep -E '\[drm\] Initialized simpledrm|fb0: simpledrmdrmfb|clk: Disabling unused clocks|\[drm\] Loaded GMU firmware|THP first frame' | head -n 12
  for p in 'GMU firmware initialization timed out' OOB hangcheck 'SPI transfer timed out' 'module is already loaded'; do
    echo "count[$p]=$(klog | grep -c "$p")"
  done
  echo "GPU_ERR=$(klog | grep -iE 'gmu|adreno' | grep -ciE 'error|timed out|hang')"
  echo "THP_FIRST=$(klog | grep -c 'THP first frame')"
  echo "THP_ERR=$(klog | grep -cE 'SPI transfer timed|GPI.*timeout|THP SPI read')"
fi
if [ -r /proc/config.gz ]; then echo CONFIG_SOURCE=proc; zcat /proc/config.gz
elif [ -r "/boot/config-$(uname -r)" ]; then echo CONFIG_SOURCE=boot; cat "/boot/config-$(uname -r)"
fi | grep -E '^(# )?CONFIG_SM_DISPCC_8750[= ]|^CONFIG_SOURCE='
echo "== failed units"; systemctl --failed --no-legend --plain
echo "FAILED_COUNT=$(systemctl --failed --no-legend --plain | grep -c .)"
echo "SYSTEM_STATE=$(systemctl is-system-running)"
[ -r {RPMHPD_SYNCED} ] && echo "RPMHPD_SYNCED=$(cat {RPMHPD_SYNCED})"
n=0; u=0
for p in /sys/devices/platform/soc@0/*interconnect*/state_synced; do
  [ -r "$p" ] || continue
  n=$((n + 1)); [ "$(cat "$p")" = 1 ] || u=$((u + 1))
done
[ "$n" -gt 0 ] && echo "ICC_COUNT=$n" && echo "ICC_UNSYNCED=$u"
if command -v modinfo >/dev/null; then
  r=$(uname -r)
  echo "MOD_LOADED=$(wc -l < /proc/modules)"
  echo "MOD_OUTSIDE=$(for m in $(cut -d' ' -f1 /proc/modules); do modinfo -n "$m" 2>/dev/null; done | grep -vE "^(/usr)?/lib/modules/$r/" | grep -c .)"
  echo "MOD_NOFILE=$(for m in $(cut -d' ' -f1 /proc/modules); do modinfo -n "$m" >/dev/null 2>&1 || echo "$m"; done | grep -c .)"
fi
command -v hciconfig >/dev/null && echo "HCI_UP=$(hciconfig hci0 2>/dev/null | grep -c 'UP RUNNING')"
s=$(timeout 10 bluetoothctl show 2>/dev/null)
case "$s" in *Controller*) echo "BT_POWERED=$(printf '%s\n' "$s" | grep -c 'Powered: yes')";; esac
f=/var/lib/piano/switch/ubuntu/manifest.json
[ -r $f ] && echo "MANIFEST_RELEASE=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["kernel_release"])' $f 2>/dev/null)"
if [ "$(id -u)" = 0 ]; then
  grep -E '^ *gcc_disp_hf_axi_clk ' /sys/kernel/debug/clk/clk_summary 2>/dev/null
  [ -x $B ] && v=$($B devmem 0x{HF_AXI_CBCR:08x} 32 2>/dev/null) && echo "REG t=$(cut -d' ' -f1 /proc/uptime) hf_axi_cbcr=$v"
  if command -v piano-boot-switch >/dev/null; then echo "== piano-boot-switch status"; piano-boot-switch status; fi
fi
echo "== bench python 256 MiB buffer copy x8"
python3 -c "
import time
n = 256 << 20
a = bytearray(b'\x5a') * n; b = bytearray(n); b[:] = a
t = time.time(); k = 0
for _ in range(8):
    b[:] = a; k += 1
    if time.time() - t > 20: break
d = time.time() - t
print('memcpy_s', round(d, 3), 'iters', k, 'MBps', round(k * 256 / d))"
@SCANOUT@echo "== acceptance read done"
'''


def device_script(scanout_probe=None):
    """Root-phase read script; scanout_probe is the text of piano-scanout-probe.py (run as root)."""
    probe = ''
    if scanout_probe:
        if f'\n{PROBE_EOF}\n' in f'\n{scanout_probe}\n':
            raise ValueError(f'the scanout probe contains the heredoc terminator {PROBE_EOF}')
        probe = (f'if [ "$(id -u)" = 0 ]; then\necho "== scanout probe"; cat /proc/uptime\n'
                 f"python3 - <<'{PROBE_EOF}'\n{scanout_probe.rstrip()}\n{PROBE_EOF}\nfi\n")
    return ROOT_SCRIPT.replace('@SCANOUT@', probe)


def initrd_script():
    """First-initrd-console read script (busybox only)."""
    return INITRD_SCRIPT


# ------------------------------------------------------------------ parsing helpers
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
TS_LINE = re.compile(r'\[\s*(\d+\.\d+)\] (.*)')
JOURNAL_KERNEL = re.compile(r'\S+ kernel: (.*)')
JOURNAL_OTHER = re.compile(r'\S+ [^\s\[\]:]+\[\d+\]: ')
KMSG = re.compile(r'^\S+ (\d+),(\d+),(\d+),[^;]*;(.*)$', re.M)
UPTIME = re.compile(r'(?:\buptime[= ]|\bUPTIME=|\bUP=)(\d+\.\d+)'
                    r'|== (?:uptime|scanout probe)[ \t]*\n(?:[#>] )*(\d+\.\d+) \d+\.\d+')
ROW = re.compile(r'gcc_disp_hf_axi_clk\s+(\d+)\s+(\d+)\s+(?:-?\d+\s+){5}([YN?])\s+(\S+)')
CBCR = re.compile(r'hf_axi_cbcr=0x([0-9a-fA-F]{8})')
COPY = re.compile(r'memcpy_s [\d.]+ iters \d+ MBps (\d+)')
COUNT = re.compile(r'count\[([^\]\n]+)\]=(\d+)')
INTF = re.compile(r'(INTF\d) timing_en=(\d) frame_count (\d+)->(\d+) \(\+(\d+) in ([\d.]+)s\)'
                  r'.*?intr_status (0x[0-9a-f]+)->(0x[0-9a-f]+)')
SAMPLES = re.compile(r'scanout samples (\d+) distinct (\d+) top_rgb (\[.*?\])')
GETVAR = re.compile(r'^(?:\(bootloader\) )?([a-z-]+(?::[ab])?):\s*(\S+)\s*$', re.M)
MSG = {'simpledrm': re.compile(r'^\[drm\] Initialized simpledrm'),
       'fb0': re.compile(r'fb0: simpledrmdrmfb'),
       'clk_unused': re.compile(r'^clk: Disabling unused clocks'),
       'gmu': re.compile(r'^\[drm\] Loaded GMU firmware'),
       'thp_first': re.compile(r'THP first frame')}


def clean(text):
    return ANSI.sub('', (text or '').replace('\r', ''))


def uptime_of(text):
    """First uptime printed in a transcript: a lower bound for everything printed after it."""
    m = UPTIME.search(text)
    return float(m.group(1) or m.group(2)) if m else None


def fields(consoles, key):
    """(console uptime, value) of every KEY=value; a value never starts with $, quotes or ;."""
    rx = re.compile(rf'(?<![A-Za-z0-9_]){re.escape(key)}=([^\s"\'$;`]+)')
    return [(c.uptime, v) for c in consoles for v in rx.findall(c.text)]


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def span_s(text):
    """Seconds of a systemd span such as '1min 7.694s' or '916ms'."""
    unit = {'h': 3600, 'min': 60, 's': 1, 'ms': 1e-3, 'us': 1e-6}
    return round(sum(float(v) * unit[u] for v, u in re.findall(r'(\d+(?:\.\d+)?)(min|ms|us|h|s)\b', text)), 6)


@dataclasses.dataclass
class Console:
    label: str
    text: str
    uptime: float = None


def console(label, text):
    text = clean(text)
    return Console(label, text, uptime_of(text))


def kernel_lines(text):
    """(kind, seconds, message) of every '[ seconds] ...' line: dmesg, journal (kernel) or journal-user."""
    for line in clean(text).split('\n'):
        mt = TS_LINE.search(line)
        if not mt:
            continue
        t, rest = float(mt.group(1)), mt.group(2)
        mk = JOURNAL_KERNEL.match(rest)
        if mk:
            yield 'journal', t, mk.group(1)
        elif JOURNAL_OTHER.match(rest):
            yield 'journal-user', t, rest
        else:
            yield 'dmesg', t, rest


def kmsg_records(text):
    """{sequence: (seconds, message)} of a /dev/kmsg capture; a reconnect replays records, kept once."""
    seen = {}
    for _, seq, usec, msg in KMSG.findall(clean(text)):
        seen.setdefault(int(seq), (int(usec) / 1e6, msg.strip()))
    return seen


def parse_getvar(text):
    return dict(GETVAR.findall(clean(text))) if text else None


# ------------------------------------------------------------------ measurements
class Logs:
    """Kernel and systemd lines by source.  Full logs (kmsg capture, journal export) can prove an
    absence and give counts; console excerpts are filtered by the device scripts and only give times."""

    def __init__(self, consoles, kmsg_texts, journal_texts):
        records = {}
        for t in kmsg_texts:
            for seq, rec in kmsg_records(t).items():
                records.setdefault(seq, rec)
        # An absence is evidence only when the capture holds the boot's log from its first record.
        self.kmsg_from_start = 0 in records
        self.full = {'kmsg': sorted(records.values()), 'journal': []}
        self.excerpt = {'dmesg': set(), 'journal': set()}
        self.user = set()
        for kind, t, msg in (x for j in journal_texts for x in kernel_lines(j)):
            if kind == 'journal':
                self.full['journal'].append((t, msg))
            elif kind == 'journal-user':
                self.user.add((t, msg))
        for kind, t, msg in (x for c in consoles for x in kernel_lines(c.text)):
            if kind == 'journal-user':
                self.user.add((t, msg))
            else:
                self.excerpt[kind].add((t, msg))
        self.full['journal'].sort()

    def window(self):
        """(source, last record time) of the longest full log."""
        got = [(recs[-1][0], src) for src, recs in self.full.items() if recs]
        return (max(got)[1], max(got)[0]) if got else (None, None)

    def first(self, key, switch_root=None):
        """First kernel time of a message.  Journal times before switch-root are journald receive
        times (simpledrm 0.20 s in dmesg was 4.25 s in the journal), so they are not accepted."""
        rx = MSG[key]
        kernel = [(t, src) for src, recs in (('kmsg', self.full['kmsg']), ('dmesg', self.excerpt['dmesg']))
                  for t, msg in recs if rx.search(msg)]
        if kernel:
            t, src = min(kernel, key=lambda e: (e[0], e[1] != 'kmsg'))
            return {'s': t, 'source': src}
        journal = [t for recs in (self.full['journal'], self.excerpt['journal']) for t, msg in recs if rx.search(msg)]
        if journal:
            t = min(journal)
            if switch_root is not None and t > switch_root:
                return {'s': t, 'source': 'journal'}
            return {'s': None, 'journal_s': t, 'note': 'journal time before switch-root is not a kernel timestamp'}
        if self.full['kmsg'] and self.kmsg_from_start:
            return {'s': None, 'absent_to_s': self.full['kmsg'][-1][0], 'source': 'kmsg'}
        return None

    def count(self, match):
        """Lines matching in the longest full log, with its window: {'n', 'to_s', 'source'} or None."""
        src, end = self.window()
        if not src:
            return None
        return {'n': sum(1 for _, msg in self.full[src] if match(msg)), 'to_s': end, 'source': src}


def systemd_times(consoles, logs):
    """switch-root and gdm from systemctl show, or from systemd's own journal lines."""
    def usecs(key):
        return [(c.uptime, int(v)) for c in consoles for v in re.findall(rf'\b{key}=(\d+)', c.text)]
    sr = [v for _, v in usecs('UserspaceTimestampMonotonic') if v]
    out = {'switch_root': {'s': sr[-1] / 1e6, 'source': 'systemctl show UserspaceTimestampMonotonic'} if sr else None,
           'gdm': None, 'gdm_states': []}
    for c in consoles:
        for st in re.findall(r'\bActiveState=(\w+)', c.text):
            out['gdm_states'].append((c.uptime, st))
    gdm = [v for _, v in usecs('ActiveEnterTimestampMonotonic') if v]
    if gdm:
        out['gdm'] = {'s': gdm[0] / 1e6, 'source': 'systemctl show gdm ActiveEnterTimestampMonotonic'}
    for t, msg in sorted(logs.user):
        m = re.search(r'systemd\[1\]: Startup finished in (.+?) \(kernel\)(?: \+ (.+?) \(initrd\))?', msg)
        if m and not out['switch_root']:
            out['switch_root'] = {'s': round(span_s(m.group(1)) + span_s(m.group(2) or ''), 6),
                                  'source': 'journal: Startup finished (kernel + initrd)'}
        if re.search(r'systemd\[1\]: Started gdm\.service', msg) and not out['gdm']:
            out['gdm'] = {'s': t, 'source': 'journal: Started gdm.service'}
    return out


def hf_axi(consoles):
    """clk_summary rows of gcc_disp_hf_axi_clk and GCC_DISP_HF_AXI_CBCR reads."""
    rows, cbcr, first = [], [], None
    for c in consoles:
        got_rows = [{'enable': int(e), 'prepare': int(p), 'hw': hw, 'consumer': who}
                    for e, p, hw, who in ROW.findall(c.text)]
        got_cbcr = [int(v, 16) for v in CBCR.findall(c.text)]
        if (got_rows or got_cbcr) and first is None:
            first = c.uptime
        rows, cbcr = rows + got_rows, cbcr + got_cbcr
    return {'rows': rows, 'cbcr': cbcr, 'first_uptime': first}


def scanout_runs(consoles):
    """One entry per scanout probe run: INTF lines followed by the splash sample line."""
    runs = []
    for c in consoles:
        pending = []
        events = sorted([(m.start(), 'intf', m) for m in INTF.finditer(c.text)] +
                        [(m.start(), 'samples', m) for m in SAMPLES.finditer(c.text)], key=lambda e: e[0])
        for _, kind, m in events:
            if kind == 'intf':
                name, en, f1, f2, frames, period, i1, i2 = m.groups()
                pending.append({'name': name, 'timing_en': int(en), 'hz': round(int(frames) / float(period), 1),
                                'intr_same': i1 == i2, 'intr_status': i2})
                continue
            top = re.findall(r"\('([0-9a-f]{6})', (\d+)\)", m.group(3))
            runs.append({'uptime': c.uptime, 'intf': pending[-2:], 'samples': int(m.group(1)),
                         'distinct': int(m.group(2)), 'top_rgb': top[0][0] if top else None})
            pending = []
    return runs


def measure(consoles, initrd, kmsg_texts=(), journal_texts=(), getvar_before=None, getvar_after=None):
    logs = Logs(consoles, kmsg_texts, journal_texts)
    sd = systemd_times(consoles, logs)
    sr = sd['switch_root']['s'] if sd['switch_root'] else None
    m = {'switch_root': sd['switch_root'], 'gdm': sd['gdm'], 'gdm_states': sd['gdm_states'],
         'simpledrm': logs.first('simpledrm', sr), 'fb0': logs.first('fb0', sr),
         'clk_disable_unused': logs.first('clk_unused', sr), 'gmu': logs.first('gmu', sr),
         'hf_axi_initrd': hf_axi(initrd), 'hf_axi_root': hf_axi(consoles),
         'copies': [int(v) for c in consoles for v in COPY.findall(c.text)],
         'scanout': scanout_runs(consoles), 'logs': logs}
    sd_init, fb0 = m['simpledrm'], m['fb0']
    m['fbcon_s'] = (round(fb0['s'] - sd_init['s'], 4) if sd_init and fb0 and sd_init.get('s') is not None
                    and fb0.get('s') is not None else None)
    m['counts'] = [(c.uptime, {k: int(v) for k, v in COUNT.findall(c.text)}) for c in consoles]
    m['counts'] = [(u, d) for u, d in m['counts'] if d]
    for key in ('GPU_ERR', 'THP_FIRST', 'THP_ERR', 'HCI_UP', 'BT_POWERED', 'FAILED_COUNT', 'SYSTEM_STATE',
                'RPMHPD_SYNCED', 'ICC_COUNT', 'ICC_UNSYNCED', 'MOD_OUTSIDE', 'MOD_NOFILE', 'UNAME', 'WHERE',
                'MANIFEST_RELEASE'):
        m[key] = fields(consoles, key)
    text = '\n'.join(c.text for c in consoles)
    if not m['WHERE']:
        m['WHERE'] = [(None, w) for w in re.findall(r'== where[ \t]*\n(?:[#>] )*(initrd|root)\b', text)]
    if not m['UNAME']:
        m['UNAME'] = [(None, u) for u in re.findall(r'== uname[ \t]*\n(?:[#>] )*(\d+\.\d+\S*)', text)]
    if not m['HCI_UP'] and re.search(r'^\s+UP RUNNING\b', text, re.M):
        m['HCI_UP'] = [(None, '1')]
    cfg = re.findall(r'(?:CONFIG_SM_DISPCC_8750=([ymn])\b|# CONFIG_SM_DISPCC_8750 (is not set))', text)
    m['config_dispcc'] = (cfg[-1][0] or 'n') if cfg else None
    m['occupant'] = (re.findall(r'"occupant":\s*"(\w+)"', text) or [None])[-1]
    m['getvar_before'], m['getvar_after'] = parse_getvar(getvar_before), parse_getvar(getvar_after)
    m['classification'] = classify(m)
    return m


def classify(m):
    """FAST, SLOW or UNKNOWN by the slow-state signature (any reason makes the boot SLOW)."""
    b, reasons, unknown = BUDGETS, [], []
    sr = m['switch_root']['s'] if m['switch_root'] else None
    if sr is None:
        unknown.append('switch_root')
    elif sr > b['slow_switch_root_s']:
        reasons.append(f'switch_root {sr:.2f} s > {b["slow_switch_root_s"]:g} s')
    if m['fbcon_s'] is None:
        unknown.append('fbcon')
    elif m['fbcon_s'] > b['slow_fbcon_s']:
        reasons.append(f'simpledrm->fb0 {m["fbcon_s"]:.3f} s > {b["slow_fbcon_s"]:g} s')
    gdm = m['gdm']['s'] if m['gdm'] else None
    late = [u for u, st in m['gdm_states'] if st != 'active' and u is not None and u >= b['slow_gdm_by_s']]
    if gdm is not None and gdm > b['slow_gdm_by_s']:
        reasons.append(f'gdm active at {gdm:.2f} s > {b["slow_gdm_by_s"]:g} s')
    elif gdm is None and late:
        reasons.append(f'gdm not active at {late[0]:.0f} s')
    elif gdm is None:
        unknown.append('gdm')
    mode = 'SLOW' if reasons else ('UNKNOWN' if unknown else 'FAST')
    return {'mode': mode, 'reasons': reasons, 'unknown': unknown, 'switch_root_s': sr, 'fbcon_s': m['fbcon_s'],
            'gdm_active_s': gdm}


# ------------------------------------------------------------------ criteria
@dataclasses.dataclass(frozen=True)
class Criterion:
    name: str
    source: str       # where the reading comes from
    budget: str       # the limit, from BUDGETS
    rule: str         # how PASS / FAIL / UNAVAILABLE are decided
    check: object     # (measurements, release) -> (status, value, shown)


def _timing(entry, budget, strict=False):
    """A kernel-time milestone against its budget; absence in a full kmsg capture past the budget fails."""
    if not entry:
        return UNAVAILABLE, None, 'not captured'
    if entry.get('s') is not None:
        ok = entry['s'] < budget if strict else entry['s'] <= budget
        return (PASS if ok else FAIL), entry, f'{entry["s"]:.3f} s ({entry["source"]})'
    if entry.get('journal_s') is not None:
        return UNAVAILABLE, entry, f'journal only: {entry["journal_s"]:.3f} s (receive time)'
    if entry.get('absent_to_s') is not None and entry['absent_to_s'] > budget:
        return FAIL, entry, f'absent from the {entry["source"]} log to {entry["absent_to_s"]:.1f} s'
    return UNAVAILABLE, entry, 'not found'


def c_mode(m, _):
    cls = m['classification']
    status = {'FAST': PASS, 'SLOW': FAIL}.get(cls['mode'], UNAVAILABLE)
    detail = '; '.join(cls['reasons']) or (('unknown: ' + ', '.join(cls['unknown'])) if cls['unknown'] else '')
    return status, cls, cls['mode'] + (f' ({detail})' if detail else '')


def c_simpledrm(m, _):
    return _timing(m['simpledrm'], BUDGETS['simpledrm_init_s'], strict=True)


def _held(h):
    """FAIL on any reading that is not held; PASS needs both a clk_summary row and a CBCR read."""
    rows, cbcr = h['rows'], h['cbcr']
    bad_rows = [r for r in rows if not (r['enable'] >= 1 and r['hw'] == 'Y' and r['consumer'] == 'framebuffer')]
    bad_cbcr = [v for v in cbcr if not (v & 1 and not v >> 31 & 1)]
    value = {'rows': rows, 'cbcr': sorted({'0x%08x' % v for v in cbcr}), 'cbcr_samples': len(cbcr),
             'first_uptime': h['first_uptime']}
    if not rows and not cbcr:
        return UNAVAILABLE, value, 'not captured'
    row_text = ', '.join(sorted({'%d/%d %s %s' % (r['enable'], r['prepare'], r['hw'], r['consumer']) for r in rows}))
    shown = 'clk_summary %s; CBCR %s' % (row_text or '-', ','.join(value['cbcr']) or '-')
    if h['first_uptime'] is not None:
        shown += ' from %.2f s' % h['first_uptime']
    if bad_rows or bad_cbcr:
        return FAIL, value, shown
    return (PASS if rows and cbcr else UNAVAILABLE), value, shown


def c_hf_axi_initrd(m, _):
    return _held(m['hf_axi_initrd'])


def c_hf_axi_root(m, _):
    return _held(m['hf_axi_root'])


def c_switch_root(m, _):
    return _timing(m['switch_root'], BUDGETS['switch_root_s'])


def c_gdm(m, _):
    budget, entry = BUDGETS['gdm_active_s'], m['gdm']
    states = m['gdm_states']
    latest = states[-1][1] if states else None
    if entry:
        if entry['s'] > budget:
            return FAIL, entry, f'{entry["s"]:.3f} s ({entry["source"]})'
        if latest not in (None, 'active'):
            return FAIL, dict(entry, latest_state=latest), f'{entry["s"]:.3f} s, then {latest}'
        return PASS, entry, f'{entry["s"]:.3f} s ({entry["source"]})'
    late = [(u, st) for u, st in states if st != 'active' and u is not None and u > budget]
    if late:
        return FAIL, {'state': late[0][1], 'uptime': late[0][0]}, f'{late[0][1]} at {late[0][0]:.1f} s'
    return UNAVAILABLE, None, 'not captured'


def c_gmu(m, _):
    return _timing(m['gmu'], BUDGETS['gmu_loaded_s'])


def c_gpu_errors(m, _):
    """Counts of the three named messages (console count[...] or a full log) and GPU_ERR lines.  GPU_ERR
    alone can fail but not pass; PASS needs the three counts covering the window."""
    window, sources, counts = BUDGETS['gpu_window_s'], [], {}
    for uptime, d in m['counts']:
        got = {k: d[k] for k in GPU_ERRORS if k in d}
        if len(got) == len(GPU_ERRORS):
            sources.append(('console count[...]', uptime, got, True))
    for uptime, v in m['GPU_ERR']:
        if as_int(v) is not None:
            sources.append(('GPU_ERR', uptime, {'gmu/adreno error lines': int(v)}, False))
    logs = m['logs']
    full = {k: logs.count(lambda msg, k=k: k in msg) for k in GPU_ERRORS}
    full['gmu/adreno error lines'] = logs.count(lambda msg: re.search(r'(?i)gmu|adreno', msg) and
                                                re.search(r'(?i)error|timed out|hang', msg))
    if all(full.values()):
        sources.append((full['OOB']['source'] + ' log', full['OOB']['to_s'], {k: v['n'] for k, v in full.items()},
                        True))
    if not sources:
        return UNAVAILABLE, None, 'not captured'
    for _, _, d, _ in sources:
        for k, n in d.items():
            counts[k] = max(counts.get(k, 0), n)
    observed = max((u for _, u, _, named in sources if named and u is not None), default=None)
    value = {'counts': counts, 'observed_to_s': observed, 'sources': [s for s, _, _, _ in sources]}
    short = {GPU_ERRORS[0]: 'GMU init timeout', 'gmu/adreno error lines': 'error lines'}
    shown = ', '.join('%s %d' % (short.get(k, k), n) for k, n in counts.items())
    shown += ' to %.1f s' % observed if observed is not None else ' (named counts not read)'
    if any(counts.values()):
        return FAIL, value, shown
    if observed is None or observed < window:
        return UNAVAILABLE, value, shown + ' (needs >= %g s)' % window
    return PASS, value, shown


def c_copy(m, _):
    v = m['copies']
    if not v:
        return UNAVAILABLE, None, 'not captured'
    return (PASS if min(v) >= BUDGETS['copy_mbps'] else FAIL), v, ', '.join(f'{x} MB/s' for x in v)


def c_scanout(m, _):
    lo, hi = BUDGETS['scanout_hz']
    results = []
    for run in m['scanout']:
        names = sorted(i['name'] for i in run['intf'])
        ok = (names == ['INTF1', 'INTF2'] and
              all(i['timing_en'] == 1 and lo <= i['hz'] <= hi and i['intr_same'] for i in run['intf']) and
              run['distinct'] >= BUDGETS['scanout_distinct'] and run['top_rgb'] == BUDGETS['scanout_top_rgb'])
        results.append(dict(run, ok=ok))
    if not results:
        return UNAVAILABLE, None, 'not captured'
    shown = '; '.join('%s Hz, %s, %d colours, top %s' % (
        '/'.join('%g' % i['hz'] for i in r['intf']),
        'intr same' if all(i['intr_same'] for i in r['intf']) else 'intr changed', r['distinct'], r['top_rgb'])
        for r in results)
    return (PASS if all(r['ok'] for r in results) else FAIL), results, shown


def c_thp(m, _):
    """Errors count from THP_ERR, a full log or count[SPI transfer timed out]; PASS needs one of the
    first two (the last covers one pattern only) and a first frame seen anywhere."""
    logs, late = m['logs'], BUDGETS['gpu_window_s']
    first = [(u, as_int(v)) for u, v in m['THP_FIRST'] if as_int(v) is not None]
    errors = [('THP_ERR', as_int(v)) for _, v in m['THP_ERR'] if as_int(v) is not None]
    complete = bool(errors)
    full_errors = logs.count(lambda msg: THP_ERRORS.search(msg))
    if full_errors:
        errors.append((full_errors['source'] + ' log', full_errors['n']))
        complete = True
    full_first = logs.count(lambda msg: MSG['thp_first'].search(msg))
    seen = (any(n for _, n in first) or bool(full_first and full_first['n']) or
            any(MSG['thp_first'].search(msg) for _, msg in logs.excerpt['dmesg'] | logs.excerpt['journal']))
    for _, d in m['counts']:
        if 'SPI transfer timed out' in d:
            errors.append(('count[SPI transfer timed out]', d['SPI transfer timed out']))
    n_err = max((n for _, n in errors), default=None)
    none_late = any(n == 0 and u is not None and u >= late for u, n in first)
    value = {'first_frame_seen': seen, 'errors': n_err, 'error_sources': [s for s, _ in errors]}
    shown = 'first frame %s, errors %s' % ('yes' if seen else ('none by %g s' % late if none_late else '?'),
                                           '?' if n_err is None else n_err)
    if (n_err or 0) > 0 or (none_late and not seen):
        return FAIL, value, shown
    return (PASS if seen and complete else UNAVAILABLE), value, shown


def _latest_int(m, key):
    got = [as_int(v) for _, v in m[key] if as_int(v) is not None]
    return got[-1] if got else None


def c_hci0(m, _):
    up, powered = _latest_int(m, 'HCI_UP'), _latest_int(m, 'BT_POWERED')
    value = {'hci_up': up, 'powered': powered}
    shown = f'UP RUNNING {up if up is not None else "?"}, Powered {powered if powered is not None else "-"}'
    if up == 0 or powered == 0:
        return FAIL, value, shown
    return (PASS if up else UNAVAILABLE), value, shown


def c_failed_units(m, _):
    n = _latest_int(m, 'FAILED_COUNT')
    state = (m['SYSTEM_STATE'] or [(None, None)])[-1][1]
    if n is None:
        return UNAVAILABLE, None, 'not captured'
    return (PASS if n == 0 else FAIL), {'failed': n, 'system_state': state}, f'{n} failed, system {state or "?"}'


def c_synced(m, _):
    rpmhpd, unsynced, count = (_latest_int(m, k) for k in ('RPMHPD_SYNCED', 'ICC_UNSYNCED', 'ICC_COUNT'))
    value = {'rpmhpd_synced': rpmhpd, 'icc_unsynced': unsynced, 'icc_providers': count}
    shown = f'rpmhpd {rpmhpd if rpmhpd is not None else "?"}, interconnect unsynced ' \
            f'{unsynced if unsynced is not None else "?"}/{count if count is not None else "?"}'
    if rpmhpd == 0 or (unsynced or 0) > 0 or count == 0:
        return FAIL, value, shown
    # ICC_UNSYNCED=0 without a provider count can come from an empty glob.
    return (PASS if rpmhpd == 1 and unsynced == 0 and count else UNAVAILABLE), value, shown


def c_release(m, release):
    uname = (m['UNAME'] or [(None, None)])[-1][1]
    where = (m['WHERE'] or [(None, None)])[-1][1]
    value = {'uname': uname, 'where': where, 'expected': release}
    shown = f'{uname or "?"} in {where or "?"}'
    if where == 'initrd' or (release and uname and uname != release):
        return FAIL, value, shown
    if not (release and uname and where):
        return UNAVAILABLE, value, shown + ('' if release else ' (no --release)')
    return PASS, value, shown


def c_modules(m, _):
    outside, nofile = _latest_int(m, 'MOD_OUTSIDE'), _latest_int(m, 'MOD_NOFILE')
    value = {'outside_release_tree': outside, 'missing_file': nofile}
    shown = f'outside {outside if outside is not None else "?"}, missing {nofile if nofile is not None else "?"}'
    if (outside or 0) > 0 or (nofile or 0) > 0:
        return FAIL, value, shown
    return (PASS if outside == 0 and nofile == 0 else UNAVAILABLE), value, shown


def c_config(m, _):
    cfg = m['config_dispcc']
    dup = [d['module is already loaded'] for _, d in m['counts'] if 'module is already loaded' in d]
    value = {'CONFIG_SM_DISPCC_8750': cfg, 'module_is_already_loaded': dup[-1] if dup else None}
    shown = f'CONFIG_SM_DISPCC_8750={cfg or "?"}' + (f', "module is already loaded" {dup[-1]}' if dup else '')
    if cfg is None:
        return UNAVAILABLE, value, 'not captured'
    return (PASS if cfg == 'y' and not (dup and dup[-1]) else FAIL), value, shown


def c_slot(m, _):
    before, after = m['getvar_before'], m['getvar_after']
    if not after or 'current-slot' not in after:
        return UNAVAILABLE, None, 'no getvar after the session'
    s = after['current-slot']
    keys = (f'slot-successful:{s}', f'slot-unbootable:{s}', f'slot-retry-count:{s}')
    got = {k: after.get(k) for k in keys}
    value = {'slot': s, 'after': got, 'before': {k: before.get(k) for k in keys} if before else None}
    shown = f'{s}: successful {got[keys[0]]}, unbootable {got[keys[1]]}, retry {got[keys[2]]}'
    if got[keys[0]] == 'no' or got[keys[1]] == 'yes' or (
            before and before.get(keys[2]) and got[keys[2]] and before[keys[2]] != got[keys[2]]):
        return FAIL, value, shown + (f' (before {before.get(keys[2])})' if before else '')
    if not before or None in got.values() or before.get(keys[2]) is None:
        return UNAVAILABLE, value, shown + ('' if before else '; no getvar before')
    return PASS, value, shown


def c_manifest(m, release):
    rel = (m['MANIFEST_RELEASE'] or [(None, None)])[-1][1]
    if rel is None:
        return UNAVAILABLE, None, 'not captured'
    if not release:
        return UNAVAILABLE, rel, f'{rel} (no --release)'
    return (PASS if rel == release else FAIL), rel, rel


def c_occupant(m, _):
    occ = m['occupant']
    if occ is None:
        return UNAVAILABLE, None, 'not captured'
    return (PASS if occ == 'ubuntu' else FAIL), occ, occ


B = BUDGETS
CRITERIA = (
    Criterion('mode_fast', 'systemctl show (UserspaceTimestampMonotonic, gdm ActiveEnter); kernel log simpledrm '
              'init and fb0', f'SLOW if switch-root > {B["slow_switch_root_s"]:g} s, simpledrm->fb0 > '
              f'{B["slow_fbcon_s"]:g} s or gdm not active by {B["slow_gdm_by_s"]:g} s',
              'FAST: all three readings inside; SLOW: any outside; else UNAVAILABLE', c_mode),
    Criterion('simpledrm_init', "first '[drm] Initialized simpledrm' in the kmsg capture or dmesg",
              f'< {B["simpledrm_init_s"]:g} s', 'journal receive times before switch-root are not accepted',
              c_simpledrm),
    Criterion('hf_axi_held_initrd', 'first initrd console: clk_summary row gcc_disp_hf_axi_clk and '
              f'GCC_DISP_HF_AXI_CBCR 0x{HF_AXI_CBCR:08x} (busybox devmem)', 'held from the first initrd console',
              'every row enable >= 1, hardware Y, consumer framebuffer; every CBCR CLK_ENABLE=1, CLK_OFF=0',
              c_hf_axi_initrd),
    Criterion('hf_axi_held_root', 'root consoles: the same clk_summary row and CBCR', 'held in the root',
              'as hf_axi_held_initrd', c_hf_axi_root),
    Criterion('switch_root', 'systemctl show UserspaceTimestampMonotonic (or journal "Startup finished" '
              'kernel + initrd)', f'<= {B["switch_root_s"]:g} s', 'value against the budget', c_switch_root),
    Criterion('gdm_active', 'systemctl show gdm ActiveEnterTimestampMonotonic / ActiveState (or journal '
              '"Started gdm.service")', f'<= {B["gdm_active_s"]:g} s and still active',
              'FAIL also when a reading after the budget shows gdm not active', c_gdm),
    Criterion('gmu_first_load', "first '[drm] Loaded GMU firmware' (journal accepted after switch-root)",
              f'<= {B["gmu_loaded_s"]:g} s', 'absent from a full kmsg capture past the budget: FAIL', c_gmu),
    Criterion('gpu_errors', 'count[...] of ' + ', '.join(GPU_ERRORS) + ' and GPU_ERR (gmu/adreno error, timed out, '
              'hang lines) from dmesg, or the full kmsg/journal log',
              f'all 0, observed to >= {B["gpu_window_s"]:g} s', 'any count > 0: FAIL; all 0 but a shorter '
              'window: UNAVAILABLE', c_gpu_errors),
    Criterion('copy_256mib', "python 256 MiB bytearray copy ('memcpy_s ... MBps N')",
              f'>= {B["copy_mbps"]} MB/s in every reading', 'minimum against the budget', c_copy),
    Criterion('scanout', 'piano-scanout-probe.py output (INTF1/INTF2 frame and interrupt registers, splash '
              'samples)', f'both INTF {B["scanout_hz"][0]:g}-{B["scanout_hz"][1]:g} Hz, intr_status unchanged, '
              f'>= {B["scanout_distinct"]} colours, most common {B["scanout_top_rgb"]} (GDM greeter)',
              'every probe run must pass', c_scanout),
    Criterion('thp_first_frame', "THP_FIRST/THP_ERR, 'THP first frame', SPI/GPI/THP read errors in dmesg or kmsg",
              'first frame and 0 errors', 'errors need THP_ERR or a full log; any error: FAIL', c_thp),
    Criterion('hci0_up', 'HCI_UP (hciconfig hci0 UP RUNNING), BT_POWERED (bluetoothctl show)', 'UP RUNNING, '
              'Powered yes when read', 'HCI_UP=0 or BT_POWERED=0: FAIL', c_hci0),
    Criterion('failed_units', 'FAILED_COUNT (systemctl --failed)', '0', 'latest reading', c_failed_units),
    Criterion('rpmhpd_icc_synced', 'RPMHPD_SYNCED, ICC_UNSYNCED/ICC_COUNT (state_synced in sysfs)',
              'rpmhpd 1, every interconnect provider synced', 'latest reading; PASS needs ICC_COUNT >= 1', c_synced),
    Criterion('release_in_root', 'UNAME (uname -r), WHERE (/etc/initrd-release)', '--release, running the root',
              'UNAVAILABLE without --release', c_release),
    Criterion('modules_own_release', 'MOD_OUTSIDE, MOD_NOFILE (modinfo -n of every loaded module)',
              'every loaded module from /lib/modules/$(uname -r)', 'both 0', c_modules),
    Criterion('config_dispcc_builtin', '/proc/config.gz (or /boot/config-*) CONFIG_SM_DISPCC_8750; count of '
              "'module is already loaded'", '=y; duplicate-module messages 0 when counted',
              'the firmware scanout clock provider must be built in', c_config),
    Criterion('slot_attributes', 'fastboot getvar before and after the session', 'current slot successful yes, '
              'unbootable no, retry count unchanged', 'UNAVAILABLE without both readings', c_slot),
    Criterion('store_manifest_release', 'MANIFEST_RELEASE (/var/lib/piano/switch/ubuntu/manifest.json)',
              '--release', 'cold boot', c_manifest),
    Criterion('slot_occupant', 'piano-boot-switch status "occupant" (root)', 'ubuntu', 'cold boot', c_occupant),
)
NAMES = tuple(c.name for c in CRITERIA)
# debug: a debug RAM validation boot of the installed root (the seventeen 2026-10-09 criteria and the slot
# attributes read in Fastboot before and after).  cold: a release cold boot read over developer-mode SSH,
# where there is no initrd console and no Fastboot reading, plus the store manifest and slot occupant.
SEVENTEEN = ('mode_fast', 'simpledrm_init', 'hf_axi_held_initrd', 'hf_axi_held_root', 'switch_root', 'gdm_active',
             'gmu_first_load', 'gpu_errors', 'copy_256mib', 'scanout', 'thp_first_frame', 'hci0_up', 'failed_units',
             'rpmhpd_icc_synced', 'release_in_root', 'modules_own_release', 'config_dispcc_builtin')
PROFILES = {
    'debug': SEVENTEEN + ('slot_attributes',),
    'cold': tuple(n for n in SEVENTEEN if n != 'hf_axi_held_initrd') + ('store_manifest_release', 'slot_occupant'),
}
assert all(n in NAMES for p in PROFILES.values() for n in p)


def evaluate(consoles=(), initrd=(), kmsg=(), journal=(), getvar_before=None, getvar_after=None, release=None,
             profile='debug', inputs=None):
    """Verdict of texts.  consoles/initrd are (label, text) pairs in the order they were taken."""
    if profile not in PROFILES:
        raise ValueError(f'unknown profile {profile!r}')
    roots = [console(label, text) for label, text in consoles]
    first = [console(label, text) for label, text in initrd]
    m = measure(roots, first, list(kmsg), list(journal), getvar_before, getvar_after)
    rows = []
    for c in CRITERIA:
        status, value, shown = c.check(m, release)
        rows.append({'name': c.name, 'status': status, 'measured': shown, 'value': value, 'budget': c.budget,
                     'source': c.source, 'rule': c.rule, 'required': c.name in PROFILES[profile]})
    required = [r for r in rows if r['required']]
    failed = [r['name'] for r in required if r['status'] == FAIL]
    missing = [r['name'] for r in required if r['status'] == UNAVAILABLE]
    return {'schema': 1, 'tool': 'piano_boot_acceptance', 'profile': profile, 'release': release,
            'budgets': BUDGETS, 'inputs': inputs or [], 'classification': m['classification'],
            'verdict': 'FAIL' if failed else ('INCOMPLETE' if missing else 'PASS'),
            'failed': failed, 'unavailable': missing, 'criteria': rows}


def table(verdict):
    lines = [f'{"criterion":24} {"result":11} {"measured":60} budget']
    for r in verdict['criteria']:
        mark = '' if r['required'] else ' (info)'
        lines.append(f'{r["name"]:24} {r["status"] + mark:11} {str(r["measured"])[:60]:60} {r["budget"]}')
    lines.append(f'verdict {verdict["verdict"]} (profile {verdict["profile"]}, classification '
                 f'{verdict["classification"]["mode"]})')
    return '\n'.join(lines)


# ------------------------------------------------------------------ files and CLI
def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def collect(args):
    """Inputs from --dir (initrd-*.txt, root-*.txt, kmsg*.txt, journal*.txt, getvar-{before,after}.txt) and flags."""
    roles = {'initrd': [], 'console': [], 'kmsg': [], 'journal': [], 'getvar_before': [], 'getvar_after': []}
    for d in args.dir or ():
        d = Path(d)
        for role, pattern in (('initrd', 'initrd-*.txt'), ('console', 'root-*.txt'), ('kmsg', 'kmsg*.txt'),
                              ('journal', 'journal*.txt'), ('getvar_before', 'getvar-before.txt'),
                              ('getvar_after', 'getvar-after.txt')):
            roles[role] += sorted(d.glob(pattern))
    for role in roles:
        roles[role] += [Path(p) for p in getattr(args, role) or ()]
    for role in ('getvar_before', 'getvar_after'):
        if len(roles[role]) > 1:
            raise SystemExit(f'more than one {role.replace("_", "-")} input: {[str(p) for p in roles[role]]}')
    inputs = [{'role': role, 'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size}
              for role, paths in roles.items() for p in paths]
    text = {role: [(str(p), p.read_text(errors='replace')) for p in paths] for role, paths in roles.items()}
    return text, inputs


def run_evaluate(args):
    text, inputs = collect(args)
    verdict = evaluate(consoles=text['console'], initrd=text['initrd'],
                       kmsg=[t for _, t in text['kmsg']], journal=[t for _, t in text['journal']],
                       getvar_before=(text['getvar_before'] or [(None, None)])[0][1],
                       getvar_after=(text['getvar_after'] or [(None, None)])[0][1],
                       release=args.release, profile=args.profile, inputs=inputs)
    return verdict


def emit(verdict, json_path):
    print(table(verdict))
    if json_path == '-':
        print(json.dumps(verdict, indent=2))
    elif json_path:
        Path(json_path).write_text(json.dumps(verdict, indent=2) + '\n')
    return {'PASS': 0, 'FAIL': 1}.get(verdict['verdict'], 3)


def live(args, run=subprocess.run, ask=getpass.getpass, now=time.gmtime):
    """One read over developer-mode SSH; the transcript is saved to --save and evaluated with --dir inputs."""
    serial = ['--serial', args.serial] if args.serial else []
    check = run([sys.executable, str(HELPER), '--check', '--wait', str(args.wait)] + serial,
                capture_output=True, text=True)
    if check.returncode != 0:
        print((check.stdout + check.stderr).strip(), file=sys.stderr)
        return 4
    probe = Path(args.scanout_probe).read_text() if args.scanout_probe else None
    password = ask('sudo password on the tablet: ') if args.sudo else None
    remote = "sudo -S -p '' sh -s" if args.sudo else 'sh -s'
    started = time.strftime('%Y%m%dT%H%M%SZ', now())
    p = run([sys.executable, str(HELPER)] + serial + [args.user, remote],
            input=(password + '\n' if password else '') + device_script(probe), capture_output=True, text=True,
            timeout=args.timeout)
    out, err = p.stdout, p.stderr
    if password:
        out, err = out.replace(password, '<password>'), err.replace(password, '<password>')
    save = Path(args.save)
    save.mkdir(parents=True, exist_ok=True)
    up = uptime_of(clean(out))
    path = save / (f'root-{int(up):04d}s-live-{started}.txt' if up is not None else f'root-live-{started}.txt')
    path.write_text(f'# piano_boot_acceptance live read {started} over piano-devmode-ssh.py, rc={p.returncode}, '
                    f'sudo={bool(args.sudo)}, scanout probe={"yes" if probe else "no"}\n== stdout\n{out}\n'
                    f'== stderr\n{err}\n')
    print(f'saved {path}', file=sys.stderr)
    if p.returncode != 0 and up is None:
        print(f'piano_boot_acceptance: the remote read failed (rc {p.returncode})', file=sys.stderr)
        return 4
    args.dir = list(args.dir or ()) + [str(save)]
    verdict = run_evaluate(args)
    return emit(verdict, args.json or str(save / f'verdict-{started}.json'))


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='command', required=True)

    def inputs(p):
        p.add_argument('--dir', action='append', metavar='DIR',
                       help='evidence directory: initrd-*.txt, root-*.txt (name order = time order), kmsg*.txt, '
                            'journal*.txt, getvar-before.txt, getvar-after.txt')
        p.add_argument('--console', action='append', metavar='FILE', help='root-phase transcript, in time order')
        p.add_argument('--initrd', action='append', metavar='FILE', help='first initrd console transcript')
        p.add_argument('--kmsg', action='append', metavar='FILE', help='host /dev/kmsg capture')
        p.add_argument('--journal', action='append', metavar='FILE', help='journalctl -b -o short-monotonic export')
        p.add_argument('--getvar-before', dest='getvar_before', action='append', metavar='FILE')
        p.add_argument('--getvar-after', dest='getvar_after', action='append', metavar='FILE')
        p.add_argument('--release', help='expected kernel release, e.g. 7.2.6-piano2')
        p.add_argument('--profile', choices=sorted(PROFILES), default='debug',
                       help='debug: RAM validation boot (default); cold: release cold boot over SSH')
        p.add_argument('--json', metavar='FILE', help="write the verdict JSON ('-' for stdout)")

    inputs(sub.add_parser('evaluate', help='evaluate saved captures'))
    lv = sub.add_parser('live', help='read once over developer-mode SSH, save the transcript and evaluate')
    inputs(lv)
    lv.add_argument('--user', required=True, help='account on the tablet')
    lv.add_argument('--serial', help='androidboot serial number, when more than one piano is attached')
    lv.add_argument('--save', required=True, metavar='DIR', help='directory for the transcript and the verdict')
    lv.add_argument('--sudo', action='store_true', help='run the read as root (asks for the password here)')
    lv.add_argument('--scanout-probe', metavar='FILE', help='piano-scanout-probe.py, run as root in the read')
    lv.add_argument('--wait', type=float, default=20, help='seconds to wait for the link (default 20)')
    lv.add_argument('--timeout', type=float, default=240, help='seconds for the remote read (default 240)')
    sc = sub.add_parser('script', help='print a device-side read script')
    sc.add_argument('--initrd', action='store_true', help='the initrd console script instead of the root one')
    sc.add_argument('--scanout-probe', metavar='FILE', help='embed piano-scanout-probe.py in the root script')
    cr = sub.add_parser('criteria', help='print the criteria, budgets and profiles')
    cr.add_argument('--json', action='store_true')
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == 'evaluate':
        return emit(run_evaluate(args), args.json)
    if args.command == 'live':
        return live(args)
    if args.command == 'script':
        if args.initrd and args.scanout_probe:
            raise SystemExit('the scanout probe runs in the root, not in the initrd')
        print(initrd_script() if args.initrd else
              device_script(Path(args.scanout_probe).read_text() if args.scanout_probe else None), end='')
        return 0
    data = {'budgets': BUDGETS, 'profiles': PROFILES,
            'criteria': [{k: v for k, v in dataclasses.asdict(c).items() if k != 'check'} for c in CRITERIA]}
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for c in CRITERIA:
            prof = ','.join(p for p, names in PROFILES.items() if c.name in names)
            print(f'{c.name:24} [{prof}]\n  source: {c.source}\n  budget: {c.budget}\n  rule:   {c.rule}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
