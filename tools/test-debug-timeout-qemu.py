#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""ARM64 RAM -> Ubuntu ext4 auto-return regression (no device access).

Uses the smoke-ubuntu/smoke-ubuntu-handoff virt/TCG, serial and -no-reboot
exit harness. Unlike snapshot=on, a disposable raw copy retains guest writes
for e2fsck -n: checking the unchanged input would hide a dirty journal.
The tiny QEMU initrd substitutes VirtIO for UFS; real Ubuntu PID1, the shipped
return units/helper, session-slice teardown and ext4 shutdown run unchanged.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import time

REPO = Path(__file__).resolve().parents[1]
SUPPORT = REPO / 'packaging/piano-device-support'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel', 'rootfs', 'qemu', 'output', 'busybox', 'gen-init-cpio'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--debugfs', default='debugfs')
    ap.add_argument('--e2fsck', default='e2fsck')
    ap.add_argument('--seconds', type=int, default=600, choices=range(60, 901), metavar='60..900',
                    help='Guest uptime deadline; default is the unchanged 600 s runner budget')
    ap.add_argument('--scenario', choices=('clean', 'blocked-stop', 'blocked-shutdown', 'old-force'), default='clean')
    a = ap.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    disk = out / 'root.ext4'
    subprocess.run(['cp', '--reflink=auto', '--sparse=always', str(a.rootfs.resolve()), str(disk)], check=True)
    before = subprocess.run([a.e2fsck, '-n', str(disk)], capture_output=True, text=True)
    (out / 'e2fsck-before.log').write_text(before.stdout + before.stderr)
    if before.returncode or 'clean' not in before.stdout or 'skipping journal recovery' in before.stderr.lower():
        raise SystemExit('Input ext4 is not clean; refusing to replay/repair the test input')

    # Stage the very same current-source runtime units used by the RAM builder.
    spec = importlib.util.spec_from_file_location('native', REPO / 'tools/build-native-display-initrd.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    stage = out / 'stage'
    units = stage / 'etc/piano-native-display/systemd'
    units.mkdir(parents=True)
    native.stage_return(stage, units)
    helper = stage / 'usr/libexec/piano/debug-timeout'
    if a.scenario == 'old-force':
        helper.write_text("#!/bin/sh\nread up rest </proc/uptime\nleft=$((" + str(a.seconds) + " - ${up%%.*}))\n[ \"$left\" -le 0 ] || sleep \"$left\"\nsync\nexec systemctl --force --force --reboot-argument=bootloader reboot\n")
    # The original root helper must never win after pivot in this test.
    bad = out / 'stale-helper'
    bad.write_text('#!/bin/sh\necho STALE_ROOT_HELPER_EXECUTED >/dev/console\nexit 1\n')
    guest = out / 'guest'
    guest.mkdir()
    stop = 'sleep 90; ' if a.scenario == 'blocked-stop' else ''
    fixtures = {
        '/usr/libexec/piano/debug-timeout': bad.read_text(),
        '/etc/systemd/system/ram-return-test.target':
            '[Unit]\nDefaultDependencies=no\nWants=systemd-journald.service piano-debug-timeout.service display-manager.service ram-return-user.service ram-return-evidence.service\n',
        '/etc/systemd/system/display-manager.service':
            '[Unit]\nDefaultDependencies=no\nConflicts=shutdown.target\nBefore=shutdown.target\nDescription=QEMU display-manager lifecycle fixture\nBefore=ram-return-evidence.service\n[Service]\nType=exec\nExecStart=/bin/sleep infinity\nExecStop=/bin/sh -c "' + stop + 'echo display-stopped >>/var/tmp/ram-return-stops"\nTimeoutStopSec=120\n',
        '/etc/systemd/system/ram-return-user.service':
            '[Unit]\nDefaultDependencies=no\nConflicts=shutdown.target\nBefore=shutdown.target\nBefore=ram-return-evidence.service\n[Service]\nType=exec\nSlice=user-1000.slice\nExecStart=/bin/sleep infinity\nExecStop=/bin/sh -c "echo user-stopped >>/var/tmp/ram-return-stops"\n',
        '/etc/systemd/system/ram-return-evidence.service':
            '[Unit]\nDefaultDependencies=no\nAfter=display-manager.service ram-return-user.service\nBefore=piano-debug-timeout.service\n[Service]\nType=oneshot\nExecStart=/bin/sh -c "echo PIANO_RETURN_EXT4_WRITABLE >/var/tmp/ram-return-written; cat /var/tmp/ram-return-written; cat /proc/mounts; systemctl --version"\nStandardOutput=journal+console\n',
    }
    if a.scenario == 'blocked-shutdown':
        # Runs after PID1's final kill; proves the independent fallback survived.
        fixtures['/usr/lib/systemd/system-shutdown/ram-return-block'] = '#!/bin/sh\necho PIANO_RETURN_LATE_SHUTDOWN_BLOCK >/dev/console\nsleep 120\n'
    script = []
    dirs = set()
    for i, (name, content) in enumerate(fixtures.items()):
        source = guest / str(i)
        source.write_text(content)
        for parent in reversed(Path(name).parents):
            if str(parent) != '/' and str(parent) not in dirs:
                script.append('mkdir ' + str(parent))
                dirs.add(str(parent))
        mode = '0100755' if content.startswith('#!') else '0100644'
        script.extend(['rm ' + name, f'write {source} {name}', f'set_inode_field {name} mode {mode}'])
    (out / 'debugfs.commands').write_text('\n'.join(script) + '\n')
    patched = subprocess.run([a.debugfs, '-w', '-f', str(out / 'debugfs.commands'), str(disk)], capture_output=True, text=True, check=True)
    (out / 'debugfs.log').write_text(patched.stdout + patched.stderr)
    # Real RAM mount/switch_root and /run unit handoff, no shutdown substitution.
    init = out / 'init'
    init.write_text("""#!/bin/busybox sh
set -eu
B=/bin/busybox
$B mount -t devtmpfs devtmpfs /dev
$B mount -t proc proc /proc
$B mount -t sysfs sysfs /sys
$B mount -t tmpfs tmpfs /run
$B mkdir -p /run/piano-native-display /run/systemd/system /newroot
$B cp /usr/libexec/piano/debug-timeout /run/piano-native-display/debug-timeout
$B cp -a /etc/piano-native-display/systemd/. /run/systemd/system/
$B mount -t ext4 -o rw /dev/vda /newroot
for name in dev proc sys run; do
    $B mkdir -p /newroot/$name
    $B mount --move /$name /newroot/$name
done
exec $B switch_root /newroot /sbin/init
""")
    lines = ['dir /bin 0755 0 0', 'dir /dev 0755 0 0', 'dir /proc 0755 0 0',
             'dir /sys 0755 0 0', 'dir /run 0755 0 0', 'dir /newroot 0755 0 0',
             f'file /bin/busybox {a.busybox.resolve()} 0755 0 0', f'file /init {init} 0755 0 0']
    for path in sorted(stage.rglob('*')):
        name = '/' + str(path.relative_to(stage))
        lines.append(f'dir {name} 0755 0 0' if path.is_dir() else f'file {name} {path} 0755 0 0')
    listing = out / 'initrd.list'
    listing.write_text('\n'.join(lines) + '\n')
    raw = subprocess.check_output([str(a.gen_init_cpio.resolve()), '-t', '0', str(listing)])
    initrd = out / 'initrd.cpio.gz'
    initrd.write_bytes(gzip.compress(raw, mtime=0))
    cmdline = (f'console=ttyAMA0 rdinit=/init root=/dev/vda rootfstype=ext4 rw rootwait panic=-1 '
               f'fstab=no apparmor=0 systemd.gpt_auto=0 piano.debug=1 piano.debug_timeout={a.seconds} '
               'systemd.unit=ram-return-test.target')
    command = [str(a.qemu.resolve()), '-machine', 'virt', '-cpu', 'max', '-accel', 'tcg,thread=multi',
               '-smp', '2', '-m', '2048M', '-nodefaults', '-display', 'none', '-monitor', 'none',
               '-serial', 'stdio', '-nic', 'none', '-no-reboot', '-kernel', str(a.kernel.resolve()),
               '-initrd', str(initrd), '-append', cmdline,
               '-drive', f'file={disk},format=raw,if=none,id=rootfs',
               '-device', 'virtio-blk-device,bus=virtio-mmio-bus.0,drive=rootfs,serial=piano-test-root']
    result = dict(state='RUNNING', scenario=a.scenario, command=command, seconds=a.seconds,
                  kernel_sha256=sha(a.kernel), initrd_sha256=sha(initrd),
                  return_files_sha256={n: sha(SUPPORT / n) for n in native.RETURN_FILES},
                  scope='ARM64 Ubuntu PID1 after RAM pivot, ext4 and fixture user/display units; no piano or GDM hardware PASS')
    return run_guest(a, out, command, result)


def run_guest(a, out, command, result):
    disk = out / 'root.ext4'
    report = out / 'result.json'
    report.write_text(json.dumps(result, indent=2) + '\n')
    start = time.monotonic()
    with (out / 'console.log').open('wb') as log:
        try:
            p = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                               timeout=a.seconds + 120)
            result['qemu_returncode'] = p.returncode
        except subprocess.TimeoutExpired:
            result['qemu_returncode'] = None
    result['wall_seconds'] = round(time.monotonic() - start, 2)
    text = (out / 'console.log').read_text(errors='replace')
    checked = subprocess.run([a.e2fsck, '-n', str(disk)], capture_output=True, text=True)
    fsck = checked.stdout + checked.stderr
    (out / 'e2fsck-after.log').write_text(fsck)
    superblock = subprocess.check_output([a.debugfs, '-R', 'stats', str(disk)], text=True, stderr=subprocess.DEVNULL)
    (out / 'superblock-after.txt').write_text(superblock)
    stops = subprocess.check_output([a.debugfs, '-R', 'cat /var/tmp/ram-return-stops', str(disk)], text=True, stderr=subprocess.DEVNULL)
    # e2fsck -n may return zero despite "skipping journal recovery". Check both
    # its verdict and the on-disk needs_recovery bit, without replaying it.
    clean = (checked.returncode == 0 and 'clean' in fsck and 'skipping journal recovery' not in fsck.lower()
             and 'needs_recovery' not in superblock and 'Filesystem state:         clean' in superblock)
    reboot = re.search(r"\[\s*([0-9.]+)\] reboot: Restarting system with command 'bootloader'", text)
    result['reboot_uptime_seconds'] = float(reboot[1]) if reboot else None
    result.update(e2fsck_returncode=checked.returncode, clean_journal=clean, stops=stops,
                  returned_to_bootloader="reboot: Restarting system with command 'bootloader'" in text,
                  fallback_fired='PIANO_DEBUG_RETURN forced after 45 seconds' in text,
                  late_shutdown_reached='PIANO_RETURN_LATE_SHUTDOWN_BLOCK' in text,
                  wrote_ext4='PIANO_RETURN_EXT4_WRITABLE' in text,
                  stale_helper_used='STALE_ROOT_HELPER_EXECUTED' in text)
    passed = (result['qemu_returncode'] == 0 and result['returned_to_bootloader'] and result['wrote_ext4']
              and not result['stale_helper_used'] and 'Kernel panic' not in text)
    if a.scenario == 'clean':
        passed &= (clean and not result['fallback_fired'] and 'display-stopped' in stops and 'user-stopped' in stops
                   and reboot is not None and a.seconds <= float(reboot[1]) < a.seconds + 45)
    elif a.scenario == 'old-force':
        passed &= not clean  # negative control proves the journal assertion catches the original bug
    else:
        passed &= (result['fallback_fired'] and reboot is not None
                   and a.seconds + 45 <= float(reboot[1]) < a.seconds + 50)
        if a.scenario == 'blocked-shutdown':
            passed &= result['late_shutdown_reached'] and clean
    result.update(passed=bool(passed), state='PASS' if passed else 'FAIL')
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('state', 'scenario', 'wall_seconds', 'clean_journal', 'fallback_fired')}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
