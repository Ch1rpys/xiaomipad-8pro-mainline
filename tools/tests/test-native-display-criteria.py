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
ROOT = (FIXTURE / 'root-0040s.txt').read_text()


class NativeCriteria(unittest.TestCase):
    def judge(self, initrd=INITRD, root=ROOT):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'initrd-first.txt').write_text(initrd)
            (directory / 'root-0040s.txt').write_text(root)
            return capture.judge(directory, '7.2.6-piano8')

    def assert_underrun(self, text, status):
        verdict = self.judge(root=text)
        name = 'zero_underrun:root-0040s.txt'
        row = next(r for r in verdict['criteria'] if r['name'] == name)
        self.assertEqual(row['status'], status, row)
        self.assertTrue(row['measured'])
        self.assertTrue(row['rule'])
        self.assertEqual(name in verdict['failed'], status == 'FAIL')
        self.assertEqual(name in verdict['unavailable'], status == 'UNAVAILABLE')
        return row

    def test_live_underrun_bits_clear_and_hardware_frames_advance(self):
        row = self.assert_underrun(ROOT, 'PASS')
        self.assertEqual(row['value']['top0'][0]['underrun'], {'INTF1': [0, 0], 'INTF2': [0, 0]})
        self.assertEqual([i['frames'] for i in row['value']['intf']], [72, 72])
        # INTF2's software vsync is zero in the actual capture; its hardware
        # counter advances. TOP0 intr_en=0 is not an underrun status bit.
        self.assertEqual({e['vsync'] for e in row['value']['encoders'] if e['intf'] == 2}, {0})

    def test_either_top0_bit_in_either_sample_fails(self):
        for bit in (26, 28):
            for sample in (0, 1):
                with self.subTest(bit=bit, sample=sample):
                    values = ['0x28000300', '0x28000300']
                    values[sample] = f'{int(values[sample], 16) | (1 << bit):#010x}'
                    text = ROOT.replace('0x28000300->0x28000300', '->'.join(values))
                    # Leave the convenience INTFn_underrun=0 fields unchanged:
                    # both raw status samples, not just the printed last bit, matter.
                    row = self.assert_underrun(text, 'FAIL')
                    self.assertIn(values[sample], row['measured'])
                    self.assert_underrun(text + ROOT, 'FAIL')

    def test_missing_native_register_lines_are_unavailable(self):
        for prefixes in (('TOP0 ',), ('INTF1 ',), ('INTF2 ',), ('TOP0 ', 'INTF1 ', 'INTF2 ')):
            with self.subTest(prefixes=prefixes):
                text = '\n'.join(line for line in ROOT.splitlines() if not line.startswith(prefixes))
                self.assert_underrun(text, 'UNAVAILABLE')

    def test_stalled_counter_fails_and_wrapped_counter_can_advance(self):
        self.assert_underrun(ROOT.replace('4758->4830 (+72', '4758->4758 (+0'), 'FAIL')
        self.assert_underrun(ROOT.replace('4758->4830 (+72', '4294967290->66 (+72'), 'PASS')
        self.assert_underrun(ROOT.replace('4758->4830 (+72', '4758->4758 (+72'), 'FAIL')

    def test_encoder_errors_still_fail_but_zero_software_vsync_does_not(self):
        for old, new in (('"underrun": 0', '"underrun": 1'),
                         ('"frame_timeout": 0', '"frame_timeout": 1')):
            with self.subTest(field=old):
                row = self.assert_underrun(ROOT.replace(old, new, 1), 'FAIL')
                self.assertIn('encoder INTF1', row['measured'])

    def test_native_scanout_ignores_splash_colours_or_missing_splash(self):
        without_splash = '\n'.join(line for line in ROOT.splitlines() if not line.startswith('scanout samples'))
        for text in (ROOT, without_splash):
            with self.subTest(splash=text == ROOT):
                row = next(r for r in self.judge(root=text)['criteria'] if r['name'] == 'scanout')
                self.assertEqual(row['status'], 'PASS', row)
                self.assertFalse(row['required'])
                self.assertIn('not applicable (native KMS)', row['measured'])
                self.assertIn('INTF1 144 Hz, INTF2 144 Hz', row['measured'])

    def test_native_scanout_checks_rate_counter_enable_and_interrupts(self):
        for text in (ROOT.replace('(+72 in 0.5s)', '(+72 in 1.0s)', 1),
                     ROOT.replace('4758->4830 (+72', '4758->4758 (+0'),
                     ROOT.replace('timing_en=1', 'timing_en=0', 1),
                     ROOT.replace('0xa00->0xa00', '0xa00->0xa01', 1)):
            with self.subTest(text=text):
                row = next(r for r in self.judge(root=text)['criteria'] if r['name'] == 'scanout')
                self.assertEqual(row['status'], 'FAIL', row)
                self.assertTrue(row['measured'])

    def test_native_scanout_missing_interface_is_unavailable(self):
        text = '\n'.join(line for line in ROOT.splitlines() if not line.startswith('INTF2 '))
        row = next(r for r in self.judge(root=text)['criteria'] if r['name'] == 'scanout')
        self.assertEqual(row['status'], 'UNAVAILABLE')

    def test_ram_store_and_slot_report_preinstall_values_as_info(self):
        rows = {r['name']: r for r in self.judge()['criteria']}
        for name, value in (('store_manifest_release', '7.2.6-piano7'), ('slot_occupant', 'android')):
            row = rows[name]
            self.assertEqual(row['status'], 'INFO')
            self.assertEqual(row['value'], value)
            self.assertEqual(row['measured'], value)
            self.assertFalse(row['required'])
            self.assertIn('pre-install', row['rule'])

    def test_missing_ram_store_and_slot_are_unavailable(self):
        text = '\n'.join(line for line in ROOT.splitlines()
                         if not line.startswith('MANIFEST_RELEASE=') and '"occupant"' not in line)
        rows = {r['name']: r for r in self.judge(root=text)['criteria']}
        for name in ('store_manifest_release', 'slot_occupant'):
            self.assertEqual(rows[name]['status'], 'UNAVAILABLE')

    def test_simpledrm_still_requires_colours_and_cold_install_state(self):
        # Give the old profile its accepted 120 Hz rate so only the splash
        # colour requirement can explain scanout FAIL.
        text = ROOT.replace('(+72 in 0.5s)', '(+60 in 0.5s)')
        verdict = capture.acceptance.evaluate(consoles=[('root.txt', text)],
                                              release='7.2.6-piano8', profile='cold')
        rows = {r['name']: r for r in verdict['criteria']}
        for name in ('scanout', 'store_manifest_release', 'slot_occupant'):
            self.assertEqual(rows[name]['status'], 'FAIL', rows[name])
            self.assertTrue(rows[name]['required'])
        self.assertIn('2 colours, top 000000', rows['scanout']['measured'])

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
