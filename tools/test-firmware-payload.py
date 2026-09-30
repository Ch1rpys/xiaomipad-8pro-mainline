#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the public staging CLI with synthetic inputs, including a Python -S run."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).with_name('stage-firmware.py')


class Payload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'inputs'
        self.source.mkdir()
        self.files = {'adsp.mdt': b'header', 'adsp.b01': b'segment',
                      'adsp_dtb.mdt': b'dtb header', 'adsp_dtb.b01': b'dtb segment',
                      'adsps.jsn': b'private service map'}
        for name, data in self.files.items():
            (self.source / name).write_bytes(data)
        self.lock = {'schema': 1, 'stock_build': 'synthetic-only',
                     'firmware_directory': 'usr/lib/firmware/qcom/test',
                     'images': ['adsp.mdt', 'adsp_dtb.mdt'], 'redistribution': 'fixture',
                     'files': [{'name': n, 'bytes': len(d), 'sha256': hashlib.sha256(d).hexdigest()}
                               for n, d in self.files.items()]}

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, name='result', images=()):
        path = self.root / 'lock.json'
        path.write_text(json.dumps(self.lock))
        # -S excludes site-packages: the payload path must not import python-debian/apt.
        words = [sys.executable, '-S', str(TOOL), '--lock', str(path), '--firmware-dir',
                 str(self.source), '--output', str(self.root / name)]
        for image in images:
            words += ['--image', image]
        return subprocess.run(words, capture_output=True, text=True, timeout=15)

    def test_plain_payload_and_adsp_selection_without_site_packages(self):
        for name, images, expected in [('all', (), set(self.files)),
                                       ('adsp', ('adsp.mdt',), {'adsp.mdt', 'adsp.b01'})]:
            with self.subTest(images=images):
                result = self.invoke(name, images)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = self.root / name / 'root/usr/lib/firmware/qcom/test'
                self.assertEqual({p.name for p in payload.iterdir()}, expected)
                for p in payload.iterdir():
                    self.assertEqual(p.read_bytes(), self.files[p.name])
                    self.assertEqual(p.stat().st_mode & 0o777, 0o644)
                manifest = json.loads((self.root / name / 'manifest.json').read_text())
                self.assertEqual({r['name'] for r in manifest['files']}, expected)

    def test_bad_bytes_do_not_publish_a_payload(self):
        (self.source / 'adsp.mdt').write_bytes(b'BADBAD')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Firmware hash mismatch', result.stderr)
        self.assertFalse((self.root / 'result').exists())
        self.assertFalse(list(self.root.glob('.piano-firmware-*')))

    def test_symlink_input_rejected(self):
        (self.source / 'adsp.mdt').unlink()
        target = self.root / 'external'
        target.write_bytes(self.files['adsp.mdt'])
        (self.source / 'adsp.mdt').symlink_to(target)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse((self.root / 'result').exists())

    def test_invalid_names_and_namespace_rejected(self):
        for name in ('../adsp.mdt', '/adsp.mdt', '.', 'adsp.b01'):
            with self.subTest(name=name):
                self.lock['files'][0]['name'] = name
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertFalse((self.root / 'result').exists())
        self.lock['files'][0]['name'] = 'adsp.mdt'
        for directory in ('/usr/lib/firmware', '../escape', 'usr/../escape'):
            self.lock['firmware_directory'] = directory
            self.assertNotEqual(self.invoke().returncode, 0)

    def test_unknown_or_repeated_image_rejected(self):
        for images in (('missing.mdt',), ('adsp.mdt', 'adsp.mdt')):
            self.assertNotEqual(self.invoke(images=images).returncode, 0)
            self.assertFalse((self.root / 'result').exists())

    def test_existing_output_preserved(self):
        output = self.root / 'result'
        output.mkdir()
        (output / 'keep').write_bytes(b'previous output')
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual((output / 'keep').read_bytes(), b'previous output')
        self.assertEqual({p.name for p in output.iterdir()}, {'keep'})


if __name__ == '__main__':
    unittest.main()
