#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that kernel_tag.py names the Makefile's upstream tag and ignores project tags such as v0.1.0-preview."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).with_name('kernel_tag.py')
sys.path.insert(0, str(TOOL.parent))
from kernel_tag import makefile_tag, upstream_tag  # noqa: E402

ENV = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
       'GIT_AUTHOR_NAME': 'test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
       'GIT_COMMITTER_NAME': 'test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid'}


def makefile(sub, extra='', version=7, patch=2):
    return (f'# SPDX-License-Identifier: GPL-2.0\nVERSION = {version}\nPATCHLEVEL = {patch}\n'
            f'SUBLEVEL = {sub}\nEXTRAVERSION ={" " + extra if extra else ""}\nNAME = Test\n')


class Tag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.git('init', '-q', '-b', 'main')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *words):
        return subprocess.run(['git', '-C', str(self.repo), *words], env=ENV, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, text, tag=None):
        (self.repo / 'Makefile').write_text(text)
        self.git('add', 'Makefile')
        self.git('commit', '-q', '--allow-empty', '-m', 'change')
        if tag:
            self.git('tag', '-a', '-m', tag, tag)

    def test_project_tag_after_upstream_tag(self):
        self.commit(makefile(6), 'v7.2.6')
        self.commit(makefile(6) + '# piano\n', 'v0.1.0-preview')
        self.commit(makefile(6) + '# piano7\n')
        # The old nearest-tag search picks the project tag.
        self.assertEqual(self.git('describe', '--tags', '--abbrev=0', '--match', 'v[0-9]*', 'HEAD'),
                         'v0.1.0-preview')
        self.assertEqual(upstream_tag(self.repo), 'v7.2.6')
        cli = subprocess.run([sys.executable, '-I', str(TOOL), str(self.repo), 'HEAD'], env=ENV,
                             capture_output=True, text=True)
        self.assertEqual((cli.returncode, cli.stdout), (0, 'v7.2.6\n'))

    def test_makefile_names(self):
        self.assertEqual(makefile_tag(makefile(0)), 'v7.2')
        self.assertEqual(makefile_tag(makefile(0, '-rc3', patch=3)), 'v7.3-rc3')
        self.assertEqual(makefile_tag(makefile(12)), 'v7.2.12')
        for bad in (makefile(6, '-piano'), makefile('06'), 'VERSION = 7\nPATCHLEVEL = 2\n'):
            with self.assertRaises(ValueError):
                makefile_tag(bad)

    def test_missing_or_unreachable_tag(self):
        self.commit(makefile(6), 'v7.2.6')
        self.commit(makefile(7))  # stable bump without its tag
        with self.assertRaisesRegex(ValueError, 'v7.2.7 named by the Makefile is missing'):
            upstream_tag(self.repo)
        cli = subprocess.run([sys.executable, '-I', str(TOOL), str(self.repo)], env=ENV,
                             capture_output=True, text=True)
        self.assertEqual((cli.returncode, cli.stdout), (1, ''))
        self.assertIn('missing', cli.stderr)
        self.git('checkout', '-q', '--orphan', 'other')
        self.commit(makefile(8), None)
        self.git('checkout', '-q', 'main')
        self.git('tag', 'v7.2.8', 'other')
        self.commit(makefile(8))
        with self.assertRaisesRegex(ValueError, 'does not contain the upstream tag v7.2.8'):
            upstream_tag(self.repo)


if __name__ == '__main__':
    unittest.main()
