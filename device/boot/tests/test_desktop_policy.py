# SPDX-License-Identifier: MIT
"""The desktop entry, its polkit action and the switch CLI agree with each other."""
import configparser
import contextlib
import io
from pathlib import Path
import shlex
import shutil
import subprocess
import unittest
import unittest.mock
import xml.etree.ElementTree as ET

import fakepiano as fp

PKG = fp.BOOT.parents[1] / 'packaging/piano-device-support'
DESKTOP = PKG / 'usr/share/applications/piano-switch-to-android.desktop'
POLICY = PKG / 'usr/share/polkit-1/actions/io.github.piano.switch.policy'
ANNOTATE = 'org.freedesktop.policykit.exec.'


class DesktopPolicy(unittest.TestCase):
    def entry(self):
        parser = configparser.RawConfigParser(strict=True, interpolation=None)
        parser.optionxform = str
        parser.read_string(DESKTOP.read_text())
        return parser['Desktop Entry']

    def action(self):
        actions = ET.parse(POLICY).getroot().findall('action')
        self.assertEqual(len(actions), 1)
        return actions[0]

    @unittest.skipUnless(shutil.which('desktop-file-validate'), 'desktop-file-validate not installed')
    def test_desktop_file_validates(self):
        r = subprocess.run(['desktop-file-validate', str(DESKTOP)], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout + r.stderr), (0, ''))

    def test_exec_is_exactly_the_policy_program_and_argument(self):
        argv = shlex.split(self.entry()['Exec'])
        notes = {a.get('key')[len(ANNOTATE):]: a.text for a in self.action().findall('annotate')}
        self.assertEqual(argv[:3], ['pkexec', notes['path'], notes['argv1']])
        self.assertEqual(argv, ['pkexec', '/usr/sbin/piano-boot-switch', 'to-android', '--desktop', '--force'])
        self.assertEqual(set(notes), {'path', 'argv1'}, 'no allow_gui: the root process needs no display')
        self.assertEqual(self.entry()['Terminal'], 'false')

    def test_the_cli_accepts_the_desktop_arguments(self):
        tool = fp.load_tool('piano-boot-switch')
        args = shlex.split(self.entry()['Exec'])[2:]
        parsed = None

        def capture(host, a):
            nonlocal parsed
            parsed = a
            return {'result': 'would-write'}
        with unittest.mock.patch.object(tool, 'cmd_switch', capture), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tool.main(args, host=fp.slot.Host('/nonexistent')), 0)
        self.assertTrue(parsed.desktop)
        self.assertTrue(parsed.force)
        self.assertEqual(parsed.command, 'to-android')

    def test_authentication_is_admin_keep_everywhere(self):
        defaults = self.action().find('defaults')
        self.assertEqual({c.tag: c.text for c in defaults},
                         {t: 'auth_admin_keep' for t in ('allow_any', 'allow_inactive', 'allow_active')})

    def test_english_and_chinese_texts(self):
        entry = self.entry()
        for key in ('Name', 'Name[zh_CN]', 'Comment', 'Comment[zh_CN]'):
            self.assertTrue(entry.get(key))
        lang = '{http://www.w3.org/XML/1998/namespace}lang'
        for tag in ('description', 'message'):
            self.assertEqual(sorted(e.get(lang) or '' for e in self.action().findall(tag)), ['', 'zh_CN'])
        self.assertIn('save your work', entry['Comment'])
        self.assertIn('Save your work', self.action().find('message').text)


if __name__ == '__main__':
    unittest.main()
