#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""GPU content connection fixture tests; no snapd, GPU or device access."""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'tools/fixtures/snap-graphics'
loader = importlib.machinery.SourceFileLoader('connect', str(
    REPO / 'packaging/piano-snap-graphics/usr/bin/piano-snap-graphics-connect'))
spec = importlib.util.spec_from_loader(loader.name, loader)
tool = importlib.util.module_from_spec(spec)
loader.exec_module(tool)


class Graphics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        tool.PAYLOAD = self.root / 'payload'
        tool.PAYLOAD.mkdir()
        payload = tool.PAYLOAD / 'piano-mesa-2404.snap'
        payload.write_bytes(b'fixture payload, not a snap')
        (tool.PAYLOAD / 'provider.json').write_text(json.dumps({
            'version': 'fixture-version', 'sha256': hashlib.sha256(payload.read_bytes()).hexdigest()}))
        tool.MARKER = self.root / 'marker'
        self.state = {'seeded': True, 'connections': (FIXTURE / 'connections.txt').read_text()}
        self.save()
        env = patch.dict(os.environ, PATH=str(FIXTURE) + ':' + os.environ['PATH'],
                         SNAP_GRAPHICS_FIXTURE=str(self.root))
        env.start()
        self.addCleanup(env.stop)

    def save(self):
        (self.root / 'state.json').write_text(json.dumps(self.state))

    def run_cli(self, *args):
        with patch.object(sys, 'argv', ['connect', *args]), contextlib.redirect_stdout(io.StringIO()):
            tool.main()

    def calls(self, verb):
        return [row['args'] for row in map(json.loads, (self.root / 'calls.jsonl').read_text().splitlines())
                if row['args'][0] == verb]

    def test_install_connect_and_repeat(self):
        self.run_cli('--install')
        self.assertTrue(tool.MARKER.exists())
        state = json.loads((self.root / 'state.json').read_text())
        for row in [line.split() for line in state['connections'].splitlines()][1:]:
            if row[1].endswith(':gpu-2404'):
                self.assertEqual(row[2], tool.PROVIDER)
        self.assertEqual(len(self.calls('install')), 1)
        self.assertEqual([row[1] for row in self.calls('connect')],
                         ['future-app_test:gpu-2404', 'snap-store:gpu-2404', 'thunderbird:gpu-2404'])
        self.run_cli('--install')
        self.run_cli()
        self.assertEqual(len(self.calls('install')), 1)
        self.assertEqual(len(self.calls('connect')), 3)
        self.assertEqual(len(self.calls('disconnect')), 2)

    def test_partial_connect_failure_then_explicit_resume(self):
        self.state['fail_connect'] = 'snap-store:gpu-2404'
        self.save()
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_cli('--install')
        self.assertFalse(tool.MARKER.exists())
        self.assertEqual(len(self.calls('connect')), 2)  # stop, no retries
        self.state = json.loads((self.root / 'state.json').read_text())
        del self.state['fail_connect']
        self.save()
        self.run_cli('--install')
        self.assertTrue(tool.MARKER.exists())
        self.assertEqual(len(self.calls('install')), 1)
        self.assertEqual(len(self.calls('connect')), 4)

    def test_old_slot_disconnect_failure_leaves_no_marker(self):
        self.state['fail_disconnect'] = 'snap-store:gpu-2404'
        self.save()
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_cli('--install')
        self.assertFalse(tool.MARKER.exists())
        self.assertEqual(len(self.calls('disconnect')), 1)
        self.state = json.loads((self.root / 'state.json').read_text())
        del self.state['fail_disconnect']
        self.save()
        self.run_cli('--install')
        self.assertTrue(tool.MARKER.exists())
        self.assertEqual(len(self.calls('install')), 1)
        self.assertEqual(len(self.calls('connect')), 3)

    def test_install_failure_leaves_no_marker(self):
        self.state['fail_install'] = True
        self.save()
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_cli('--install')
        self.assertFalse(tool.MARKER.exists())
        self.assertEqual(len(self.calls('install')), 1)
        self.assertEqual(self.calls('connect'), [])

    def test_hash_failure_has_no_snap_calls(self):
        (tool.PAYLOAD / 'piano-mesa-2404.snap').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.run_cli('--install')
        self.assertFalse((self.root / 'calls.jsonl').exists())
        self.assertFalse(tool.MARKER.exists())

    def test_parsing_existing_duplicate_slot_and_empty(self):
        text = self.state['connections'] + 'content thunderbird:gpu-2404 piano-mesa-2404:gpu-2404 manual\n'
        self.assertEqual(tool.connections(text)['thunderbird:gpu-2404'],
                         {'mesa-2404:gpu-2404', tool.PROVIDER})
        self.assertEqual(tool.connections('Interface Plug Slot Notes\n'), {})
        for text in ('', 'error: cannot contact snapd', 'Interface Plug Slot Notes\ncontent bad:gpu-2404\n',
                     'Interface Plug Slot Notes\nnetwork bad:gpu-2404 - -\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                tool.connections(text)

    def test_seed_failure_does_not_install(self):
        self.state['seeded'] = False
        self.save()
        with self.assertRaisesRegex(RuntimeError, 'before seeded'):
            self.run_cli('--install')
        self.assertFalse(tool.MARKER.exists())
        self.assertEqual(self.calls('install'), [])


if __name__ == '__main__':
    unittest.main()
