#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""piano_boot_acceptance.py on scrubbed real captures of one fast and one slow boot.

fixtures/boot-acceptance/fast-piano2-20261009: the 7.2.6-piano2 validation boot that passed the
seventeen criteria on 2026-10-09.  fixtures/boot-acceptance/slow-dispcc-module-20261009: a boot of
the 2026-10-08 image with dispcc as a module, in the slow state.  provenance.json in each directory
names the original captures and what was removed from them.
"""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import piano_boot_acceptance as acc  # noqa: E402

FIXTURES = TOOLS / 'fixtures/boot-acceptance'
FAST, SLOW = FIXTURES / 'fast-piano2-20261009', FIXTURES / 'slow-dispcc-module-20261009'


def load(directory, release=None, profile='debug', **drop):
    """evaluate() of a fixture directory; drop={'console': True, ...} leaves a role out."""
    d = Path(directory)

    def texts(pattern):
        return [(p.name, p.read_text()) for p in sorted(d.glob(pattern))]

    def one(name):
        return (d / name).read_text() if (d / name).exists() else None
    return acc.evaluate(consoles=[] if drop.get('console') else texts('root-*.txt'),
                        initrd=[] if drop.get('initrd') else texts('initrd-*.txt'),
                        kmsg=[] if drop.get('kmsg') else [t for _, t in texts('kmsg*.txt')],
                        getvar_before=one('getvar-before.txt'), getvar_after=one('getvar-after.txt'),
                        release=release, profile=profile)


def by_name(verdict):
    return {r['name']: r for r in verdict['criteria']}


def statuses(verdict, status, required_only=True):
    return {r['name'] for r in verdict['criteria'] if r['status'] == status and (r['required'] or not required_only)}


class Fixtures(unittest.TestCase):
    def test_fast_boot_passes_every_debug_criterion(self):
        v = load(FAST, release='7.2.6-piano2')
        self.assertEqual(v['verdict'], 'PASS', v['failed'] + v['unavailable'])
        self.assertEqual(statuses(v, 'PASS'), set(acc.PROFILES['debug']))
        self.assertEqual(len(acc.PROFILES['debug']), 18)
        c = by_name(v)
        self.assertEqual(v['classification']['mode'], 'FAST')
        self.assertEqual(c['simpledrm_init']['value'], {'s': 0.201081, 'source': 'kmsg'})
        self.assertAlmostEqual(c['switch_root']['value']['s'], 7.617393)
        self.assertAlmostEqual(c['gdm_active']['value']['s'], 14.588769)
        self.assertAlmostEqual(c['gmu_first_load']['value']['s'], 16.261025)
        self.assertEqual(c['copy_256mib']['value'], [5305, 5360])
        self.assertEqual(c['hf_axi_held_initrd']['value']['cbcr'], ['0x08200001'])
        self.assertEqual(c['hf_axi_held_initrd']['value']['first_uptime'], 6.11)
        run, = c['scanout']['value']
        self.assertEqual(([i['hz'] for i in run['intf']], run['distinct'], run['top_rgb']),
                         ([120.0, 120.0], 7, '222222'))
        self.assertGreaterEqual(c['gpu_errors']['value']['observed_to_s'], 198)
        self.assertEqual(c['slot_attributes']['value']['after'],
                         {'slot-successful:a': 'yes', 'slot-unbootable:a': 'no', 'slot-retry-count:a': '6'})

    def test_slow_boot_fails_the_bandwidth_and_timing_budgets(self):
        v = load(SLOW, release='7.2.6-piano+')
        self.assertEqual(v['verdict'], 'FAIL')
        cls = v['classification']
        self.assertEqual(cls['mode'], 'SLOW')
        self.assertEqual(len(cls['reasons']), 3, cls['reasons'])
        self.assertEqual(statuses(v, 'FAIL'), {
            'mode_fast', 'simpledrm_init', 'hf_axi_held_initrd', 'switch_root', 'gdm_active', 'gmu_first_load',
            'gpu_errors', 'copy_256mib', 'scanout', 'thp_first_frame', 'config_dispcc_builtin'})
        # The root holds the clock again after simpledrm bound at 16 s: a measured PASS in a slow boot.
        self.assertEqual(statuses(v, 'PASS'), {'hf_axi_held_root'})
        # These were not read in that run; missing evidence is never a FAIL.
        self.assertEqual(statuses(v, 'UNAVAILABLE'), {
            'hci0_up', 'failed_units', 'rpmhpd_icc_synced', 'release_in_root', 'modules_own_release',
            'slot_attributes'})
        c = by_name(v)
        self.assertEqual(c['copy_256mib']['value'], [42, 39])
        self.assertAlmostEqual(c['simpledrm_init']['value']['s'], 16.106994)
        self.assertAlmostEqual(c['switch_root']['value']['s'], 23.950249)
        self.assertAlmostEqual(c['gdm_active']['value']['s'], 102.246757)
        self.assertGreater(c['gmu_first_load']['value']['s'], 128)
        self.assertEqual(c['config_dispcc_builtin']['value']['CONFIG_SM_DISPCC_8750'], 'm')
        initrd = c['hf_axi_held_initrd']['value']
        self.assertIn('0x8a200000', initrd['cbcr'])     # CLK_OFF=1, CLK_ENABLE=0
        self.assertEqual(initrd['rows'][0], {'enable': 0, 'prepare': 0, 'hw': 'N', 'consumer': 'deviceless'})
        self.assertGreater(c['gpu_errors']['value']['counts']['GMU firmware initialization timed out'], 0)
        run, = c['scanout']['value']
        self.assertEqual((run['distinct'], run['top_rgb']), (1, '010101'))

    def test_kmsg_capture_alone_separates_the_two_boots(self):
        fast, slow = (by_name(load(d, console=True, initrd=True)) for d in (FAST, SLOW))
        for name in ('simpledrm_init', 'gmu_first_load', 'gpu_errors', 'thp_first_frame'):
            self.assertEqual(fast[name]['status'], 'PASS', (name, fast[name]['measured']))
            self.assertEqual(slow[name]['status'], 'FAIL', (name, slow[name]['measured']))
        self.assertEqual(fast['gpu_errors']['value']['sources'], ['kmsg log'])
        # Without systemctl readings the classification cannot be made.
        self.assertEqual(fast['mode_fast']['status'], 'UNAVAILABLE')
        self.assertEqual(slow['mode_fast']['status'], 'FAIL')    # simpledrm->fb0 1.36 s is enough

    def test_typed_ahead_text_before_a_marker(self):
        # bigfoot-r200: the console echo left input in front of '== uptime' on the same line.
        self.assertEqual(acc.uptime_of(' rd(b + # # # == uptime\n198.08 1558.22\n'), 198.08)
        slow = [acc.console(p.name, p.read_text()) for p in sorted(SLOW.glob('root-*.txt'))]
        self.assertEqual({c.label: c.uptime for c in slow}['root-0060s-readings.txt'], 60.57)


class Rules(unittest.TestCase):
    def test_no_input_is_unavailable_not_fail(self):
        for profile in acc.PROFILES:
            v = acc.evaluate(release='7.2.6-piano2', profile=profile)
            self.assertEqual({r['status'] for r in v['criteria']}, {'UNAVAILABLE'})
            self.assertEqual(v['verdict'], 'INCOMPLETE')

    def test_echoed_scripts_are_not_readings(self):
        probe = ("print(f'{name} timing_en={en} frame_count {fc1}->{fc2} (+{d} in {SAMPLE_S}s) intr_status "
                 "0x{ir1:x}->0x{ir2:x}')\nprint('scanout samples', n, 'distinct', k, 'top_rgb', top)\n")
        echo = [('device', acc.device_script(probe)), ('initrd', acc.initrd_script())]
        v = acc.evaluate(consoles=echo, initrd=echo, release='7.2.6-piano2')
        measured = {r['name']: r['measured'] for r in v['criteria'] if r['status'] != 'UNAVAILABLE'}
        self.assertEqual(measured, {})

    def test_journal_receive_times_before_switch_root(self):
        journal = '\n'.join([
            '[    4.250112] localhost kernel: [drm] Initialized simpledrm 1.0.0 for chosen:framebuffer on minor 1',
            '[   14.588792] piano systemd[1]: Started gdm.service - GNOME Display Manager.',
            '[   15.616652] piano systemd[1]: Startup finished in 3.089s (kernel) + 4.527s (initrd) '
            '+ 7.999s (userspace) = 15.616s.',
            '[   15.634653] piano systemd[2536]: Startup finished in 916ms.',
            '[   16.260329] piano kernel: [drm] Loaded GMU firmware v5.1.25'])
        c = by_name(acc.evaluate(journal=[journal]))
        self.assertEqual(c['simpledrm_init']['status'], 'UNAVAILABLE')
        self.assertEqual(c['simpledrm_init']['value']['journal_s'], 4.250112)
        self.assertEqual((c['switch_root']['status'], c['switch_root']['value']['s']), ('PASS', 7.616))
        self.assertEqual(c['gdm_active']['value']['s'], 14.588792)
        self.assertEqual(c['gmu_first_load']['value'], {'s': 16.260329, 'source': 'journal'})
        self.assertEqual(acc.span_s('1min 7.694s'), 67.694)

    def test_errors_fail_even_in_a_short_window(self):
        early = [('r', 'UPTIME=40.00\ncount[GMU firmware initialization timed out]=0\ncount[OOB]=0\n'
                       'count[hangcheck]=0\nGPU_ERR=0\n')]
        self.assertEqual(by_name(acc.evaluate(consoles=early))['gpu_errors']['status'], 'UNAVAILABLE')
        bad = [('r', early[0][1].replace('count[OOB]=0', 'count[OOB]=2'))]
        self.assertEqual(by_name(acc.evaluate(consoles=bad))['gpu_errors']['status'], 'FAIL')

    def test_device_scripts_are_valid_sh(self):
        for script in (acc.device_script('print(1)\n'), acc.device_script(), acc.initrd_script()):
            subprocess.run(['sh', '-n'], input=script, text=True, check=True)
        with self.assertRaises(ValueError):
            acc.device_script(f'x = 1\n{acc.PROBE_EOF}\n')


class Cli(unittest.TestCase):
    def cli(self, *words):
        return subprocess.run([sys.executable, str(TOOLS / 'piano_boot_acceptance.py')] + list(words),
                              capture_output=True, text=True)

    def test_exit_codes_and_json(self):
        p = self.cli('evaluate', '--dir', str(FAST), '--release', '7.2.6-piano2', '--json', '-')
        self.assertEqual(p.returncode, 0, p.stderr)
        verdict = json.loads(p.stdout[p.stdout.index('\n{') + 1:])
        self.assertEqual(verdict['verdict'], 'PASS')
        self.assertEqual({i['role'] for i in verdict['inputs']},
                         {'initrd', 'console', 'kmsg', 'getvar_before', 'getvar_after'})
        self.assertEqual(self.cli('evaluate', '--dir', str(SLOW)).returncode, 1)
        self.assertEqual(self.cli('evaluate').returncode, 3)
        crit = json.loads(self.cli('criteria', '--json').stdout)
        self.assertEqual([c['name'] for c in crit['criteria']], list(acc.NAMES))

    def test_live_saves_the_transcript_and_evaluates_it(self):
        ident = (FAST / 'root-0198s-ident.txt').read_text()
        password, calls = 'S3cret-pw!', []

        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if '--check' in cmd:
                return subprocess.CompletedProcess(cmd, 0, 'enx000000000000 piano-SERIAL ready\n', '')
            return subprocess.CompletedProcess(cmd, 0, ident + f'\nsudo echoed {password}\n', '')
        with tempfile.TemporaryDirectory() as tmp:
            args = acc.parse_args(['live', '--user', 'owner', '--save', tmp, '--sudo', '--profile', 'cold',
                                   '--release', '7.2.6-piano2'])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = acc.live(args, run=run, ask=lambda prompt: password)
            saved, = Path(tmp).glob('root-*-live-*.txt')
            verdict, = Path(tmp).glob('verdict-*.json')
            self.assertTrue(saved.name.startswith('root-0198s-live-'))
            self.assertNotIn(password, saved.read_text())
            self.assertEqual(json.loads(verdict.read_text())['profile'], 'cold')
        cmd, kwargs = calls[1]
        self.assertEqual(cmd[-2:], ['owner', "sudo -S -p '' sh -s"])
        self.assertTrue(kwargs['input'].startswith(password + '\n'))
        self.assertIn('== piano boot acceptance read', kwargs['input'])
        self.assertEqual(rc, 3)       # an SSH read has no initrd console, scanout or 200 s window


if __name__ == '__main__':
    unittest.main()
