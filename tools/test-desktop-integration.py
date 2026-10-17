#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline package contracts and APT's real PPD provider replacement."""
import importlib.util
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_apt', REPO / 'tools/prepare-ubuntu-apt.py')
prepare_apt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_apt)


class DesktopIntegration(unittest.TestCase):
    def test_built_package_payload_and_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'debs'
            subprocess.run(['python3', str(REPO / 'tools/build-device-debs.py'), '--desktop-only',
                            '--version', '0.5.0~test', '--output', str(out)], check=True,
                           stdout=subprocess.DEVNULL)
            deb = next(out.glob('*.deb'))
            control = subprocess.check_output(['dpkg-deb', '-f', str(deb)], text=True)
            root = out / 'extract'
            subprocess.run(['dpkg-deb', '-R', str(deb), str(root)], check=True)
            conffiles = (root / 'DEBIAN/conffiles').read_text().splitlines()
            self.assertIn('/etc/tuned/piano-ppd.conf', conffiles)
            self.assertFalse((root / 'etc/tuned/ppd.conf').exists())
            self.assertEqual((root / 'etc/tuned/piano-ppd.conf').read_bytes(),
                             (REPO / 'device/power/tuned/ppd.conf').read_bytes())
            profiles = list((root / 'usr/lib/tuned/profiles').glob('*/tuned.conf'))
            self.assertEqual(len(profiles), 3)
            for p in profiles:
                self.assertEqual(p.read_bytes(), (REPO / 'device/power/tuned/profiles' /
                                                 p.parent.name / 'tuned.conf').read_bytes())
            self.assertIn('tuned-ppd (>= 2.25.1)', control)
            dependencies = next(line for line in control.splitlines() if line.startswith('Depends: '))
            for package in ('showtime', 'gstreamer1.0-plugins-base', 'gstreamer1.0-plugins-good',
                            'gstreamer1.0-plugins-bad', 'gstreamer1.0-libav'):
                self.assertEqual(dependencies.split(', ').count(package), 1)
            self.assertFalse((root / 'usr/local').exists())
            self.assertFalse((root / 'etc/mpv').exists())
            self.assertFalse(list(root.rglob('powerprofilesctl')))
            self.assertIn("power-button-action='lock'", (root / 'usr/share/glib-2.0/schemas/'
                         '50_piano-ubuntu-desktop.gschema.override').read_text())
            for script in ('postinst', 'prerm', 'postrm'):
                subprocess.run(['sh', '-n', str(root / 'DEBIAN' / script)], check=True)

    def test_pins_keep_local_versions_against_future_ubuntu_updates(self):
        # No apt update or network: synthetic index plus the real shipped preferences.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name in ('lists/partial', 'empty', 'cache', 'prefs'):
                (d / name).mkdir(parents=True)
            (d / 'sources.list').write_text('deb [trusted=yes] https://example.invalid/ubuntu resolute main\n')
            versions = {'gnome-settings-daemon': '50.0-1ubuntu1+piano1',
                        'gnome-settings-daemon-common': '50.0-1ubuntu1+piano1',
                        'gnome-control-center': '1:50.0-0ubuntu6+piano1',
                        'gnome-control-center-data': '1:50.0-0ubuntu6+piano1'}
            (d / 'status').write_text('\n'.join(
                f'Package: {name}\nStatus: install ok installed\nArchitecture: arm64\n'
                f'Version: {version}\nDescription: synthetic installed package\n'
                for name, version in versions.items()))
            (d / 'lists/example.invalid_ubuntu_dists_resolute_main_binary-arm64_Packages').write_text(
                '\n'.join(f'Package: {name}\nArchitecture: arm64\nVersion: 9:99.0-1ubuntu1\n'
                          f'Description: synthetic security update\nFilename: pool/{name}.deb\n'
                          'Size: 1\nSHA256: ' + '0' * 64 + '\n' for name in versions))
            shutil.copyfile(REPO / 'packaging/piano-ubuntu-desktop/etc/apt/preferences.d/'
                            'piano-power-button-lock', d / 'prefs/piano')
            options = ['-o', 'APT::Architecture=arm64', '-o', f'Dir::State={d}', '-o',
                       f'Dir::State::status={d}/status', '-o', f'Dir::Cache={d}/cache', '-o',
                       f'Dir::Etc::sourcelist={d}/sources.list', '-o', f'Dir::Etc::sourceparts={d}/empty',
                       '-o', 'Dir::Etc::preferences=/dev/null', '-o', f'Dir::Etc::preferencesparts={d}/prefs']
            for name, version in versions.items():
                policy = subprocess.check_output(['apt-cache', *options, 'policy', name], text=True,
                                                 env=dict(os.environ, LC_ALL='C'))
                self.assertIn(f'Candidate: {version}', policy)
                self.assertIn('9:99.0-1ubuntu1 -1', policy)

    def test_image_provider_removal_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / 'plan'
            script = REPO / 'tools/rootfs-image-steps.sh'
            def check(text, sensor_supplied):
                plan.write_text(text)
                return subprocess.run(['/bin/sh', '-c',
                    '. "$1"; check_userspace_removals "$2" "$3"',
                    'check', str(script), str(plan), str(int(sensor_supplied))]).returncode
            providers = 'Remv power-profiles-daemon [0.30-2]\nRemv iio-sensor-proxy [3.9]\n'
            self.assertEqual(check(providers, True), 0)
            self.assertNotEqual(check(providers, False), 0)
            self.assertEqual(check(providers.replace('iio-sensor-proxy ', 'iio-sensor-proxy:arm64 '), True), 0)
            self.assertNotEqual(check(providers + 'Remv gnome-shell [50]\n', True), 0)

    def test_real_apt_replacement_plan_and_removal_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / 'status').write_text(
                'Package: power-profiles-daemon\nStatus: install ok installed\n'
                'Priority: optional\nSection: admin\nInstalled-Size: 1\n'
                'Maintainer: Test <test@example.invalid>\nArchitecture: all\nVersion: 0.30-2\n'
                'Description: synthetic old provider\n\n'
                'Package: desktop-consumer\nStatus: install ok installed\n'
                'Priority: optional\nSection: admin\nInstalled-Size: 1\n'
                'Maintainer: Test <test@example.invalid>\nArchitecture: all\nVersion: 1\n'
                'Depends: power-profiles-daemon\nDescription: synthetic consumer\n')
            stage = d / 'stage/DEBIAN'
            stage.mkdir(parents=True)
            (stage / 'control').write_text(
                'Package: tuned-ppd\nVersion: 2.25.1-1ubuntu1\nArchitecture: all\n'
                'Maintainer: Test <test@example.invalid>\n'
                'Conflicts: power-profiles-daemon\nProvides: power-profiles-daemon\n'
                'Description: synthetic new provider\n')
            deb = d / 'tuned-ppd.deb'
            subprocess.run(['dpkg-deb', '--build', str(stage.parent), str(deb)], check=True,
                           stdout=subprocess.DEVNULL)
            for name in ('lists/partial', 'cache/archives/partial', 'empty'):
                (d / name).mkdir(parents=True)
            command = ['apt-get', '-o', 'Dir::Etc::sourcelist=/dev/null', '-o',
                       f'Dir::Etc::sourceparts={d / "empty"}', '-o',
                       f'Dir::State::status={d / "status"}', '-o', f'Dir::State::lists={d / "lists"}',
                       '-o', f'Dir::Cache={d / "cache"}', '-o', 'Debug::NoLocking=1',
                       '--simulate', '--no-download', '--no-install-recommends', 'install', str(deb)]
            plan = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL,
                                           env=dict(os.environ, LC_ALL='C'))
            self.assertEqual(prepare_apt.check_removals(plan, True), ['power-profiles-daemon'])
            with self.assertRaises(ValueError):
                prepare_apt.check_removals(plan, False)
            with self.assertRaises(ValueError):
                prepare_apt.check_removals(plan + '\nRemv desktop-consumer [1]\n', True)
            self.assertIn('Inst tuned-ppd', plan)


if __name__ == '__main__':
    unittest.main()
