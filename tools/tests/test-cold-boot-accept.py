#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-only replay and mocked SSH tests; no device discovery or SSH."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('cold_accept', TOOLS / 'piano-cold-boot-accept.py')
cold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cold)
FIXTURES = Path(__file__).parent / 'fixtures/cold-boot'
EARLY = (FIXTURES / 'cold-01-0040s.txt').read_text()
LATE = (FIXTURES / 'cold-01-0240s.txt').read_text()
GOOD = (FIXTURES / 'cold-02-0060s.txt').read_text()
# Explicitly synthetic second reading, never a real cold-02 device PASS.
SYNTHETIC_LATE = GOOD.replace('UPTIME=41.86', 'UPTIME=240.00')


def row(verdict, name):
    return next(r for r in verdict['criteria'] if r['name'] == name)


class JudgeTests(unittest.TestCase):
    def test_cold01_failed_units_only_failure(self):
        verdict = cold.judge(EARLY, LATE)
        self.assertEqual(verdict['verdict'], 'FAIL')
        self.assertEqual(verdict['failed'], ['failed_units'])
        self.assertEqual(verdict['unavailable'], [])
        self.assertTrue(all(r['status'] == 'PASS' for r in verdict['criteria'] if r['name'] != 'failed_units'))
        self.assertEqual(row(verdict, 'failed_units')['value']['early']['SYSTEM_STATE'], 'degraded')

    def test_early_cold01_preserves_failure_and_missing_window(self):
        verdict = cold.judge(EARLY)
        self.assertEqual(verdict['failed'], ['failed_units'])
        self.assertEqual(verdict['unavailable'], ['late_observation'])

    def test_cold02_all_captured_criteria_pass_but_no_late_evidence(self):
        verdict = cold.judge(GOOD)
        self.assertEqual(verdict['failed'], [])
        self.assertEqual(verdict['unavailable'], ['late_observation'])
        self.assertEqual(verdict['verdict'], 'UNAVAILABLE')
        self.assertTrue(all(r['status'] == 'PASS' for r in verdict['criteria'] if r['name'] != 'late_observation'))

    def test_synthetic_complete_window_and_switch_root_regression(self):
        self.assertEqual(cold.judge(GOOD, SYNTHETIC_LATE)['verdict'], 'PASS')
        slower = re.sub(r'^UserspaceTimestampMonotonic=\d+', 'UserspaceTimestampMonotonic=11000000', GOOD, flags=re.M)
        self.assertEqual(cold.judge(slower, SYNTHETIC_LATE)['failed'], ['switch_root'])

    def test_early_failures_cannot_be_erased_by_later_pass(self):
        cases = [('GPU_ERR=0', 'GPU_ERR=1', 'gpu_errors'),
                 ('PIANO8_CLOCK_WARNINGS=0', 'PIANO8_CLOCK_WARNINGS=1', 'clock_dsi_warnings'),
                 ('NATIVE_DSI_ERRORS=0', 'NATIVE_DSI_ERRORS=1', 'clock_dsi_warnings'),
                 ('MOD_OUTSIDE=0', 'MOD_OUTSIDE=1', 'modules_own_release'),
                 ('MOD_NOFILE=0', 'MOD_NOFILE=1', 'modules_own_release'),
                 ('SYSTEM_STATE=running', 'SYSTEM_STATE=degraded', 'failed_units'),
                 ('PIANO8_MCA_MODULE=present', 'PIANO8_MCA_MODULE=missing', 'piano8_controls'),
                 ('PIANO8_ACTIVE_WAYLAND_USERS=1', 'PIANO8_ACTIVE_WAYLAND_USERS=2', 'wayland_session'),
                 ('THP_ERR=0', 'THP_ERR=1', 'thp_first_frame'),
                 ('hf_axi_cbcr=0x08200001', 'hf_axi_cbcr=0x88200000', 'hf_axi_held')]
        for old, new, name in cases:
            with self.subTest(field=old):
                self.assertIn(old, GOOD)
                self.assertIn(name, cold.judge(GOOD.replace(old, new), SYNTHETIC_LATE)['failed'])

    def test_thresholds(self):
        for field, good, bad, name in [('UserspaceTimestampMonotonic', 10_000_000, 10_000_001, 'switch_root'),
                                      ('ActiveEnterTimestampMonotonic', 20_000_000, 20_000_001, 'gdm_active')]:
            for value, status in [(good, 'PASS'), (bad, 'FAIL')]:
                text = re.sub(r'^' + field + r'=\d+', field + '=' + str(value), GOOD, flags=re.M)
                self.assertEqual(row(cold.judge(text, SYNTHETIC_LATE), name)['status'], status)
        for value, status in [('0.999999', 'PASS'), ('1.000000', 'FAIL')]:
            text = re.sub(r'\[\s*[\d.]+\] \[drm\] Initialized simpledrm',
                          f'[{value}] [drm] Initialized simpledrm', GOOD)
            self.assertEqual(row(cold.judge(text, SYNTHETIC_LATE), 'simpledrm_init')['status'], status)
        for value, status in [('2000', 'PASS'), ('1999', 'FAIL')]:
            text = re.sub(r'(memcpy_s [\d.]+ iters \d+ MBps )\d+', r'\g<1>' + value, GOOD)
            self.assertEqual(row(cold.judge(text, SYNTHETIC_LATE), 'copy_256mib')['status'], status)

    def test_scanout_counter_and_both_interfaces(self):
        text = re.sub(r'^INTF2 .*\n', '', GOOD, flags=re.M)
        self.assertEqual(row(cold.judge(text, SYNTHETIC_LATE), 'scanout')['status'], 'UNAVAILABLE')
        for delta, status in [(69, 'FAIL'), (70, 'PASS'), (74, 'PASS'), (75, 'FAIL')]:
            text = re.sub(r'frame_count (\d+)->\d+ \(\+72',
                          lambda m: f'frame_count {m[1]}->{int(m[1]) + delta} (+{delta}', GOOD)
            self.assertEqual(row(cold.judge(text, SYNTHETIC_LATE), 'scanout')['status'], status)
        self.assertEqual(row(cold.judge(GOOD.replace('(+72 in', '(+71 in'), SYNTHETIC_LATE), 'scanout')['status'], 'FAIL')

    def test_missing_data_never_passes_or_uses_other_capture(self):
        for field, name in [('GPU_ERR', 'gpu_errors'), ('PIANO8_CLOCK_WARNINGS', 'clock_dsi_warnings'),
                            ('MOD_NOFILE', 'modules_own_release'), ('THP_FIRST', 'thp_first_frame')]:
            text = re.sub(r'^' + field + r'=.*\n', '', GOOD, flags=re.M)
            self.assertEqual(row(cold.judge(text, SYNTHETIC_LATE), name)['status'], 'UNAVAILABLE')
        verdict = cold.judge('echo GPU_ERR=0\nUPTIME=nan\n', '')
        self.assertNotIn('PASS', [r['status'] for r in verdict['criteria']])

    def test_no_journal_receive_time_as_kernel_initialization(self):
        text = re.sub(r'^\[\s*[\d.]+\] \[drm\] Initialized simpledrm.*\n', '', GOOD, flags=re.M)
        self.assertEqual(row(cold.judge(text, SYNTHETIC_LATE), 'simpledrm_init')['status'], 'UNAVAILABLE')

    def test_late_window_and_boot_identity(self):
        self.assertIn('capture_identity', cold.judge(GOOD, LATE)['failed'])
        for uptime, expected in [('199.99', 'UNAVAILABLE'), ('200.00', 'PASS'), ('20.00', 'FAIL')]:
            later = SYNTHETIC_LATE.replace('UPTIME=240.00', 'UPTIME=' + uptime)
            self.assertEqual(row(cold.judge(GOOD, later), 'late_observation')['status'], expected)

    def test_sound_requires_card_list_not_asoc_probe_log(self):
        text = GOOD.split('== sound\n')[0]
        self.assertEqual(row(cold.judge(text), 'sound_card')['status'], 'UNAVAILABLE')
        self.assertEqual(row(cold.judge(text + '== sound\n--- no soundcards ---\n', SYNTHETIC_LATE),
                             'sound_card')['status'], 'FAIL')

    def test_cli_table_json_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            early, late = Path(tmp) / 'early', Path(tmp) / 'late'
            late.write_text(SYNTHETIC_LATE)
            for text, second, code in [(GOOD, True, 0), (GOOD, False, 1), (EARLY, False, 1)]:
                early.write_text(text)
                args = ['judge', str(early)] + ([str(late)] if second else [])
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cold.main(args), code)
                table, data = output.getvalue().split('\n\n', 1)
                self.assertIn('Measured | Budget', table)
                self.assertEqual(json.loads(data)['verdict'] == 'PASS', code == 0)


class RunTests(unittest.TestCase):
    def test_two_captures_through_serial_bound_helper_password_stdin_only(self):
        calls = []
        password = b'test-only-secret\n'
        def ssh(argv, **kwargs):
            calls.append((argv, kwargs))
            self.assertEqual(argv[1:4], [str(TOOLS / 'piano-devmode-ssh.py'), '--serial', 'TEST-SERIAL'])
            self.assertEqual(argv[4], 'tester')
            self.assertNotIn(password.strip().decode(), ' '.join(argv))
            self.assertNotIn('PIANO_SUDO_PASSWORD_FILE', kwargs['env'])
            self.assertEqual(kwargs['input'], password)
            return subprocess.CompletedProcess(argv, 0, (GOOD if len(calls) == 1 else SYNTHETIC_LATE).encode(), b'')
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            args = argparse.Namespace(out=Path(tmp) / 'captures', serial='TEST-SERIAL', user='tester', late_seconds=200)
            self.assertEqual(cold.run_captures(args, password, run=ssh)['verdict'], 'PASS')
            self.assertEqual(len(calls), 2)
            self.assertIn('time.sleep(max(0, 200', calls[1][0][-1])
            self.assertEqual(len(list(args.out.iterdir())), 5)
            for p in args.out.iterdir():
                self.assertNotIn(password.strip(), p.read_bytes())
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(args.out.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(FileExistsError):
                cold.run_captures(args, password, run=ssh)

    def test_transport_failure_preserves_partial_output_without_retry(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
                def ssh(argv, **kwargs):
                    if timeout:
                        raise subprocess.TimeoutExpired(argv, 120, output=GOOD.encode(), stderr=b'test-secret')
                    return subprocess.CompletedProcess(argv, 1, GOOD.encode(), b'test-secret')
                mocked = mock.Mock(side_effect=ssh)
                args = argparse.Namespace(out=Path(tmp) / 'captures', serial='TEST', user='tester', late_seconds=200)
                verdict = cold.run_captures(args, b'test-secret\n', run=mocked)
                self.assertEqual(mocked.call_count, 1)
                self.assertIn('capture_transport', verdict['failed'])
                self.assertEqual((args.out / 'capture-early.stderr.txt').read_text(), '<PASSWORD>')
                self.assertFalse((args.out / 'capture-late.txt').exists())

    def test_password_file_and_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'password'
            path.write_bytes(b'test-secret\n')
            with mock.patch.dict(os.environ, {'PIANO_SUDO_PASSWORD_FILE': str(path)}):
                self.assertEqual(cold.password_from_input(), b'test-secret\n')
            path.write_bytes(b'line1\nline2\n')
            with mock.patch.dict(os.environ, {'PIANO_SUDO_PASSWORD_FILE': str(path)}):
                with self.assertRaises(ValueError):
                    cold.password_from_input()
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'from-stdin\n'))):
            self.assertEqual(cold.password_from_input(), b'from-stdin\n')

    def test_generation_reuses_native_payload_and_parses_without_execution(self):
        script = cold.native.cold_boot_script()
        self.assertTrue(script.startswith(cold.native.script()))
        self.assertIn('PIANO8_INTEGRATION_DONE', script)
        self.assertIn('cat /proc/asound/cards', script)
        self.assertLess(script.index('if [ "$(cat $D/power/runtime_status'), script.index(cold.native.NATIVE_SCANOUT))
        result = subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        compile(cold.native.NATIVE_SCANOUT, '<native-scanout>', 'exec')

    def test_invalid_window_and_identity_do_not_read_password_or_connect(self):
        for extra in [('--late-seconds', '199'), ('--late-seconds', 'nan'), ('--serial', '-bad'), ('--user', 'x@y')]:
            with self.subTest(extra=extra), mock.patch.object(cold, 'password_from_input') as secret, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cold.main(['run', '--serial', 'TEST', '--user', 'tester', '--out', 'unused', *extra])
                secret.assert_not_called()


if __name__ == '__main__':
    unittest.main()
