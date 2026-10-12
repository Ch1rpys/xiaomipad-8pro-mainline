#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Result classification and owned-process cleanup, without device access."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

spec = importlib.util.spec_from_file_location('ssc_run', Path(__file__).with_name('run.py'))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class Results(unittest.TestCase):
    def accel(self, value='-9.810000', code=0, extra=''):
        return run.parse_sensor('accelerometer',
            "DEBUG: Discovered 'accel' sensor (123 456)\nDEBUG:   name: actual accel\n" +
            f'Accelerometer sensor measurement: X=0.000000 Y=0.000000 Z={value} m/s²\n' * 2 + extra, code)

    def test_resting_accel(self):
        row = self.accel()
        result = run.aggregate({'accelerometer': row}, True)
        self.assertEqual(result['result'], 'PASS')
        self.assertAlmostEqual(result['accel_median_m_s2'], 9.81)
        self.assertEqual(row['suid'], ('123', '456'))

    def test_zero_not_a_pass(self):
        self.assertEqual(run.aggregate({'accelerometer': self.accel('0')}, True)['result'], 'FAIL')

    def test_nan_is_rejected(self):
        self.assertEqual(self.accel('nan')['result'], 'FAIL')
        self.assertEqual(self.accel('nan')['invalid_samples'], 2)

    def test_daemon_exit_is_not_a_pass(self):
        self.assertEqual(run.aggregate({'accelerometer': self.accel()}, False)['result'], 'FAIL')

    def test_cli_failure_after_samples_is_not_a_pass(self):
        self.assertEqual(self.accel(code=-15)['result'], 'FAIL')

    def test_close_error_is_not_a_pass(self):
        self.assertEqual(self.accel(extra='Unable to close accelerometer sensor: error\n')['result'], 'FAIL')

    def test_debug_translation_is_not_a_transport_failure(self):
        row = self.accel(extra='<<<<<<   translated =  ERROR: Reading TLV would overflow\n')
        self.assertEqual(row['result'], 'PASS')
        self.assertEqual(len(row['trace_diagnostics']), 1)

    def test_actual_glib_warning_is_retained_as_failure(self):
        self.assertEqual(self.accel(extra='** (ssccli:42): WARNING **: 00:00:00: parse failed\n')['result'], 'FAIL')

    def test_missing_optional_type(self):
        gyro = run.parse_sensor('gyroscope', "DEBUG: No 'gyro' sensor available\n", 254)
        self.assertEqual(gyro['result'], 'UNAVAILABLE')
        self.assertEqual(run.aggregate({'accelerometer': self.accel(), 'gyroscope': gyro}, True)['result'], 'PASS')

    def test_advertised_but_no_sample(self):
        light = run.parse_sensor('light', "DEBUG: Discovered 'ambient_light' sensor (2 3)\n", 0)
        self.assertEqual(light['result'], 'FAIL')
        self.assertEqual(run.aggregate({'accelerometer': self.accel(), 'light': light}, True)['result'], 'FAIL')

    def test_proximity_and_light(self):
        self.assertEqual(run.parse_sensor('proximity', 'Proximity sensor measurement: FAR\n', 0)['samples'], [{'near': False}])
        self.assertEqual(run.parse_sensor('light', 'Light sensor measurement: 42.000000 Lux\n', 0)['samples'], [{'lux': 42.0}])

    def test_owned_process_is_reaped(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            run.stop(child)
            self.assertIsNotNone(child.poll())
            run.stop(child)  # Cleanup remains safe after natural/earlier exit.
        finally:
            if child.poll() is None:
                child.kill(); child.wait()


if __name__ == '__main__':
    unittest.main()
