#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Host checks of the maintenance RAM environment (piano.diag=maintenance); no device.

- piano-maint's idle watchdog and LUN map, run by a host BusyBox `sh` (BUSYBOX_SH,
  default "busybox sh") against a temporary state and sysfs tree, with the reboot
  replaced by a marker;
- the payload tool's symlink resolution and its refusal of a changed payload;
- with MAINTENANCE_INITRAMFS=<initramfs.cpio.gz>: the archive content. Every ELF
  file's interpreter and DT_NEEDED libraries resolve inside the archive, the
  tools, modules (of the recorded release), login link and network contract are
  present, and the scripts that run without the operator contain no disk write.
"""
import gzip
import json
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import unittest

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from initramfs_archive import read_newc, regular_file  # noqa: E402

PAYLOAD = runpy.run_path(str(TOOLS / 'prepare-maintenance-payload.py'))
SH = shlex.split(os.environ.get('BUSYBOX_SH', 'busybox sh'))
ARCHIVE = os.environ.get('MAINTENANCE_INITRAMFS')
MAINT = REPO / 'initramfs/piano-maint'


def watchdog(tmp, limit, setup='', sleep='0.05'):
    """Run piano-maint's watchdog; returns (Popen, marker path)."""
    script = f'''PIANO_MAINT_LIBRARY=1 . {shlex.quote(str(MAINT))}
load_reboot_mode() {{ return 1; }}
reboot_to_fastboot() {{ echo "REBOOT $1|${{2:-}}" >"$state/rebooted"; exit 0; }}
{setup}
watchdog {limit}
'''
    env = dict(os.environ, PIANO_MAINT_STATE=str(tmp / 'state'), PIANO_MAINT_SYS=str(tmp / 'sys'),
               PIANO_MAINT_SLEEP=sleep)
    return subprocess.Popen([*SH, '-c', script], env=env), tmp / 'state/rebooted'


def carrier(tmp, value):
    path = tmp / 'sys/class/net/usb0/carrier'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{value}\n')


class Watchdog(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def finish(self, proc, timeout=10):
        proc.wait(timeout=timeout)
        self.assertEqual(proc.returncode, 0)

    def test_no_session_reboots_after_the_limit_with_fallback(self):
        carrier(self.tmp, 1)
        proc, marker = watchdog(self.tmp, 30)
        self.finish(proc)
        self.assertEqual(marker.read_text(), 'REBOOT no session or keepalive for 30 s|fallback\n')
        self.assertEqual((self.tmp / 'state/idle').read_text(), '30\n')

    def test_open_session_holds_until_it_ends(self):
        carrier(self.tmp, 1)
        holder = subprocess.Popen(['sleep', '30'])
        (self.tmp / 'state/sessions').mkdir(parents=True)
        (self.tmp / f'state/sessions/{holder.pid}').touch()
        proc, marker = watchdog(self.tmp, 30)
        time.sleep(1.5)  # 30 ticks: six would have been enough without the session
        self.assertIsNone(proc.poll())
        self.assertEqual((self.tmp / 'state/idle-count').read_text(), '0\n')
        holder.kill()
        holder.wait()
        self.finish(proc)
        self.assertTrue(marker.exists())
        self.assertFalse((self.tmp / f'state/sessions/{holder.pid}').exists(), 'stale session file removed')

    def test_session_without_carrier_does_not_count(self):
        carrier(self.tmp, 0)
        holder = subprocess.Popen(['sleep', '30'])
        try:
            (self.tmp / 'state/sessions').mkdir(parents=True)
            (self.tmp / f'state/sessions/{holder.pid}').touch()
            proc, marker = watchdog(self.tmp, 30)
            self.finish(proc)
            self.assertTrue(marker.exists())
        finally:
            holder.kill()
            holder.wait()

    def test_keepalive_touches_restart_the_count(self):
        carrier(self.tmp, 1)
        keepalive = self.tmp / 'state/keepalive'
        keepalive.parent.mkdir(parents=True)
        keepalive.touch()
        proc, marker = watchdog(self.tmp, 30, sleep='0.1')
        t = 1_000_000
        end = time.monotonic() + 2
        while time.monotonic() < end:
            t += 1
            os.utime(keepalive, (t, t))
            time.sleep(0.05)
            self.assertIsNone(proc.poll(), 'rebooted while the keepalive file changed')
        stopped = time.monotonic()
        self.finish(proc)
        self.assertGreater(time.monotonic() - stopped, 0.5)  # at least six 0.1 s ticks after the last touch
        self.assertTrue(marker.exists())

    def test_runtime_limit_and_refusals(self):
        env = dict(os.environ, PIANO_MAINT_STATE=str(self.tmp / 'state'), PIANO_MAINT_SYS=str(self.tmp / 'sys'))
        (self.tmp / 'state').mkdir()
        run = lambda *a: subprocess.run([*SH, str(MAINT), *a], env=env, capture_output=True, text=True)
        self.assertEqual(run('idle', '120').stdout, 'idle limit 120 s\n')
        self.assertEqual((self.tmp / 'state/idle').read_text(), '120\n')
        for bad in (('idle', '29'), ('idle', '3601'), ('idle', 'x'), ('idle',), ('watchdog', '-1'), ('format',)):
            self.assertEqual(run(*bad).returncode, 2, bad)
        self.assertIn('of 120 s', run('status').stdout)
        # No nvmem-reboot-mode device in the fake sysfs: a requested reboot is refused.
        self.assertEqual(run('fastboot').returncode, 1)


class Map(unittest.TestCase):
    def test_luns_and_lun0(self):
        tmp = Path(tempfile.mkdtemp())
        sys_ = tmp / 'sys'
        for disk, lun in (('sda', 0), ('sdb', 1), ('sdf', 5)):
            target = sys_ / f'devices/platform/soc@0/1d84000.ufshc/host0/target0:0:0/0:0:0:{lun}'
            target.mkdir(parents=True)
            block = sys_ / 'block' / disk
            (block / 'queue').mkdir(parents=True)
            (block / 'size').write_text('996417536\n')
            (block / 'queue/logical_block_size').write_text('4096\n')
            (block / 'device').symlink_to(target)
        script = f'''PIANO_MAINT_LIBRARY=1 . {shlex.quote(str(MAINT))}
sgdisk() {{ echo "SGDISK $*"; }}
map'''
        out = subprocess.run([*SH, '-c', script], env=dict(os.environ, PIANO_MAINT_SYS=str(sys_)),
                             capture_output=True, text=True, check=True).stdout
        self.assertIn('0 sda 996417536 4096 ', out)
        self.assertIn('5 sdf 996417536 4096 ', out)
        self.assertIn('LUN 0: /dev/sda\nSGDISK -p /dev/sda\n', out)


class Payload(unittest.TestCase):
    def test_resolve_follows_links_and_records_them(self):
        tree = {'lib': ('l', 'usr/lib'), 'usr': ('d', None), 'usr/lib': ('d', None),
                'usr/lib/ld-linux-aarch64.so.1': ('l', 'aarch64-linux-gnu/ld-linux-aarch64.so.1'),
                'usr/lib/aarch64-linux-gnu': ('d', None),
                'usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1': ('-', None),
                'usr/share/doc/a': ('l', '../doc/b'), 'usr/share': ('d', None), 'usr/share/doc': ('d', None),
                'usr/share/doc/b': ('d', None), 'usr/share/doc/b/copyright': ('-', None),
                'loop': ('l', 'loop')}
        links = {}
        self.assertEqual(PAYLOAD['resolve'](tree, '/lib/ld-linux-aarch64.so.1', links),
                         'usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1')
        self.assertEqual(links, {'lib': 'usr/lib', 'usr/lib/ld-linux-aarch64.so.1':
                                 'aarch64-linux-gnu/ld-linux-aarch64.so.1'})
        self.assertEqual(PAYLOAD['resolve'](tree, 'usr/share/doc/a/copyright', {}), 'usr/share/doc/b/copyright')
        with self.assertRaises(ValueError):
            PAYLOAD['resolve'](tree, 'loop', {})
        with self.assertRaises(FileNotFoundError):
            PAYLOAD['resolve'](tree, 'usr/lib/missing.so', {})
        with self.assertRaises(ValueError):
            PAYLOAD['resolve'](tree, 'usr/lib', {})

    def test_stage_refuses_a_changed_payload(self):
        tmp = Path(tempfile.mkdtemp())
        root = tmp / 'p/root/usr/sbin'
        root.mkdir(parents=True)
        (root / 'tool').write_bytes(b'one')
        manifest = {'kind': 'piano-maintenance-payload', 'kernel_release': 'x',
                    'files': {'usr/sbin/tool': PAYLOAD['sha'](root / 'tool')}, 'symlinks': {}}
        (tmp / 'p/manifest.json').write_text(json.dumps(manifest))
        stage = lambda d: subprocess.run([sys.executable, str(TOOLS / 'prepare-maintenance-payload.py'), 'stage',
                                          '--payload', str(tmp / 'p'), '--stage-dir', str(tmp / d)],
                                         capture_output=True, text=True)
        ok = stage('s1')
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn(f'file /usr/sbin/tool {root / "tool"} 0644 0 0', ok.stdout)
        (root / 'tool').write_bytes(b'two')
        self.assertIn('differs from its manifest', stage('s2').stderr)
        (root / 'tool').write_bytes(b'one')
        (tmp / 'p/root/lib').symlink_to('/usr/lib')
        manifest['symlinks'] = {'lib': '/usr/lib'}
        (tmp / 'p/manifest.json').write_text(json.dumps(manifest))
        self.assertIn('leaves the tree', stage('s3').stderr)


def resolve_in(entries, path, depth=0):
    """Regular file reached by path inside the archive, following its symlinks."""
    parts = PurePosixPath(path.lstrip('/')).parts
    current = PurePosixPath()
    for i, part in enumerate(parts):
        current = current.parent if part == '..' else current / part
        mode, body = entries.get(str(current), (None, None))
        if mode is None:
            raise FileNotFoundError(path)
        if stat.S_ISLNK(mode):
            if depth > 40:
                raise ValueError('symlink loop')
            target = body.rstrip(b'\0').decode()
            base = PurePosixPath('/') if target.startswith('/') else current.parent
            rest = parts[i + 1:]
            return resolve_in(entries, os.path.normpath(str(base.joinpath(target, *rest))), depth + 1)
    return str(current)


@unittest.skipUnless(ARCHIVE, 'set MAINTENANCE_INITRAMFS to a built initramfs.cpio.gz')
class Archive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = read_newc(gzip.decompress(Path(ARCHIVE).read_bytes()))
        cls.info = json.loads(regular_file(cls.entries, 'etc/piano-maintenance.json'))

    def test_every_elf_runs_from_the_archive(self):
        elves = 0
        for name, (mode, body) in self.entries.items():
            if not stat.S_ISREG(mode) or body[:4] != b'\x7fELF' or name.endswith('.ko'):
                continue
            elves += 1
            interp, needed, runpath = PAYLOAD['elf_info'](body)
            self.assertIsNone(runpath, name)
            if interp:
                self.assertTrue(stat.S_ISREG(self.entries[resolve_in(self.entries, interp)][0]), name)
            for soname in needed:
                found = [d for d in PAYLOAD['LIBRARY_DIRS'] if f'{d}/{soname}' in self.entries]
                self.assertTrue(found, f'{name}: {soname}')
                resolve_in(self.entries, f'{found[0]}/{soname}')
        self.assertGreater(elves, 20)

    def test_tools_modules_and_login(self):
        for tool in PAYLOAD['TOOLS']:
            mode, _ = self.entries[tool]
            self.assertTrue(stat.S_ISREG(mode) and mode & 0o111, tool)
        restart2 = regular_file(self.entries, 'bin/restart2')
        self.assertIsNone(PAYLOAD['elf_info'](restart2)[0], 'restart2 is static')
        link = lambda name: self.entries[name][1].rstrip(b'\0')
        self.assertEqual(link('lib'), b'usr/lib')
        self.assertEqual(link('bin/piano-maint-login'), b'piano-maint')
        self.assertEqual(regular_file(self.entries, 'bin/piano-maint'), MAINT.read_bytes())
        self.assertEqual(regular_file(self.entries, 'init'), (REPO / 'initramfs/init').read_bytes())
        for applet in ('dd', 'sha256sum', 'sync', 'wget', 'insmod', 'telnetd', 'udhcpd', 'stat', 'readlink', 'reboot'):
            self.assertEqual(link(f'bin/{applet}'), b'busybox', applet)
        release = self.info['kernel_release']
        for module in PAYLOAD['MODULES']:
            body = regular_file(self.entries, f'usr/lib/modules/{release}/{module}')
            self.assertIn(f'vermagic={release} '.encode(), body)
        network = json.loads((REPO / 'initramfs/network.json').read_text())
        text = regular_file(self.entries, 'etc/piano-network').decode()
        for key, value in network.items():
            self.assertIn(f"PIANO_{key.upper()}={value}\n", text)
        for licence in self.info['licences']:
            resolve_in(self.entries, licence)

    def test_unattended_scripts_do_not_write_disks(self):
        # The watchdog, login and map run without the operator; /init likewise.
        for name in ('bin/piano-maint', 'init', 'bin/usb-diag'):
            text = regular_file(self.entries, name).decode()
            # Comments and the login banner's here-document are text, not commands.
            text = re.sub(r'<<EOT\n.*?\nEOT\n', '\n', text, flags=re.S)
            code = '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))
            for pattern in (r'\bof=', r'\bsfdisk\b', r'\bblkdiscard\b', r'\bmkfs', r'\bmke2fs\b', r'\bwipefs\b',
                            r'\bpartx\b', r'\bblockdev\b', r'\bfstrim\b', r'mount\s+\S*\s*/dev/sd',
                            r'\bsgdisk\s+(?!-p\b)', r'>\s*/dev/sd'):
                self.assertIsNone(re.search(pattern, code), f'{name}: {pattern}')
        init = regular_file(self.entries, 'init').decode()
        self.assertIn('shell=/bin/piano-maint-login', init)
        self.assertIn('/bin/piano-maint watchdog "$maint_idle" &', init)


if __name__ == '__main__':
    unittest.main()
