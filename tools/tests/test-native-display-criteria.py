#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-only native RAM criteria regressions using scrubbed live-01 readings."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('native_capture', TOOLS / 'piano-native-display-capture.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
FIXTURE = Path(__file__).resolve().parent / 'fixtures/native-display-ram'
INITRD = (FIXTURE / 'initrd-first.txt').read_text()


class NativeCriteria(unittest.TestCase):
    def judge(self, initrd=INITRD):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'initrd-first.txt').write_text(initrd)
            (directory / 'root-0040s.txt').write_text((FIXTURE / 'root-0040s.txt').read_text())
            return capture.judge(directory, '7.2.6-piano8')

    def assert_clock(self, text, status):
        verdict = self.judge(text)
        rows = {r['name']: r for r in verdict['criteria']}
        for name in ('hf_axi_held_initrd', 'native_hf_axi_initrd'):
            self.assertEqual(rows[name]['status'], status, rows[name])
        self.assertEqual('native_hf_axi_initrd' in verdict['failed'], status == 'FAIL')
        return rows['hf_axi_held_initrd']

    def test_saved_native_holder_passes(self):
        row = self.assert_clock(INITRD, 'PASS')
        self.assertEqual(row['value']['rows'], [
            {'enable': 4, 'prepare': 4, 'hw': 'Y', 'consumer': 'ae96000.dsi'}])
        self.assertEqual(row['value']['cbcr'], ['0x08200001'])
        self.assertEqual(row['value']['cbcr_samples'], 2)
        self.assertEqual(row['value']['first_uptime'], 11.09)
        self.assertIn('ae96000.dsi or MDSS/DPU', row['rule'])

    def test_framebuffer_and_mdss_dpu_holders_pass(self):
        for holder in ('framebuffer', 'ae00000.display-subsystem', 'ae01000.display-controller', 'mdss', 'dpu'):
            with self.subTest(holder=holder):
                self.assert_clock(INITRD.replace('ae96000.dsi', holder), 'PASS')

    def test_clock_n_fails_even_with_enabled_cbcr(self):
        self.assert_clock(INITRD.replace('Y   ae96000.dsi', 'N   ae96000.dsi'), 'FAIL')

    def test_unheld_or_unknown_consumer_fails(self):
        for text in (INITRD.replace('4       4', '0       0'),
                     INITRD.replace('ae96000.dsi', 'deviceless'),
                     INITRD.replace('ae96000.dsi', 'ae96000.unrelated')):
            with self.subTest(text=text):
                self.assert_clock(text, 'FAIL')

    def test_cbcr_disabled_or_off_fails(self):
        for value in ('0x08200000', '0x88200001', '0x8a200000'):
            with self.subTest(value=value):
                self.assert_clock(INITRD.replace('0x08200001', value, 1), 'FAIL')

    def test_handoff_without_gap_passes_but_later_recovery_does_not_erase_gap(self):
        framebuffer = INITRD.replace('ae96000.dsi', 'framebuffer')
        self.assert_clock(framebuffer + INITRD, 'PASS')
        gap = INITRD.replace('Y   ae96000.dsi', 'N   ae96000.dsi')
        self.assert_clock(framebuffer + gap + INITRD, 'FAIL')

    def test_partial_evidence_cannot_hide_failure_or_prove_pass(self):
        clock_only = '\n'.join(line for line in INITRD.splitlines() if 'REG t=' not in line)
        register_only = '\n'.join(line for line in INITRD.splitlines() if 'gcc_disp_hf_axi_clk ' not in line)
        for text in ('', clock_only, register_only):
            with self.subTest(text=text):
                self.assert_clock(text, 'UNAVAILABLE')
        self.assert_clock(clock_only.replace('Y   ae96000.dsi', 'N   ae96000.dsi'), 'FAIL')
        self.assert_clock(register_only.replace('0x08200001', '0x8a200000'), 'FAIL')

    def test_root_clock_uses_same_native_rule(self):
        rows = {r['name']: r for r in self.judge()['criteria']}
        self.assertEqual(rows['hf_axi_held_root']['status'], 'PASS')
        self.assertEqual(rows['native_hf_axi_root']['status'], 'PASS')
        self.assertEqual(rows['hf_axi_held_root']['rule'], rows['hf_axi_held_initrd']['rule'])

    def test_ram_timing_is_info_with_values_and_cold_budget_note(self):
        rows = {r['name']: r for r in self.judge()['criteria']}
        row = rows['mode_fast']
        self.assertEqual(row['status'], 'INFO')
        self.assertFalse(row['required'])
        self.assertEqual(row['value']['switch_root_s'], 18.0574)
        self.assertEqual(row['value']['gdm_active_s'], 24.48103)
        self.assertIn('RAM full-module boot; persistent budgets (switch_root ≤10 s, GDM ≤20 s) '
                      'apply only to the cold-boot acceptance', row['measured'])
        self.assertIn('switch_root 18.057 s; GDM 24.481 s', row['measured'])
        self.assertNotIn('SLOW', json.dumps(row))
        # This task changes mode_fast only, not the separate timing criteria.
        for name in ('switch_root', 'gdm_active'):
            self.assertEqual(rows[name]['status'], 'FAIL')
            self.assertTrue(rows[name]['required'])

    def test_persistent_cold_budgets_and_framebuffer_rule_stay_strict(self):
        args = capture.acceptance.parse_args(['evaluate', '--dir', str(FIXTURE),
                                             '--release', '7.2.6-piano8', '--profile', 'cold'])
        verdict = capture.acceptance.run_evaluate(args)
        rows = {r['name']: r for r in verdict['criteria']}
        self.assertEqual(verdict['budgets']['switch_root_s'], 10)
        self.assertEqual(verdict['budgets']['gdm_active_s'], 20)
        self.assertEqual(verdict['budgets']['slow_switch_root_s'], 18)
        self.assertEqual(verdict['budgets']['slow_gdm_by_s'], 40)
        for name in ('switch_root', 'gdm_active', 'mode_fast', 'hf_axi_held_root'):
            self.assertEqual(rows[name]['status'], 'FAIL')
            self.assertTrue(rows[name]['required'])

    def test_existing_offline_judge_cli(self):
        result = subprocess.run([sys.executable, str(TOOLS / 'piano-native-display-capture.py'),
                                 'judge', '--dir', str(FIXTURE), '--release', '7.2.6-piano8'],
                                check=True, capture_output=True, text=True)
        verdict = json.loads(result.stdout)
        self.assertEqual(verdict['profile'], 'native-display-ram')
        rows = {r['name']: r for r in verdict['criteria']}
        self.assertEqual(rows['hf_axi_held_initrd']['status'], 'PASS')
        self.assertEqual(rows['mode_fast']['status'], 'INFO')


if __name__ == '__main__':
    unittest.main()
