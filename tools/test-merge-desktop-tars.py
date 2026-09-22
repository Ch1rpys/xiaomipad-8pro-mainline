#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Focused metadata/whiteout regression for the Desktop TAR merger."""
import io
import os
import runpy
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

implementation = runpy.run_path(str(Path(__file__).with_name('merge-desktop-tars.py')))
merge = implementation['merge']
SQFS2TAR = os.environ.get('SQFS2TAR') or shutil.which('sqfs2tar')


def layer(rows):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for name, kind, content, attrs in rows:
            member = tarfile.TarInfo(name)
            member.type, member.mode, member.uid, member.gid = kind, 0o4755, 42, 43
            member.pax_headers = attrs
            if kind == tarfile.REGTYPE:
                member.size = len(content)
            elif kind == tarfile.LNKTYPE:
                member.linkname = content
            archive.addfile(member, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
    data.seek(0)
    return tarfile.open(fileobj=data, mode='r:')


class MergeTest(unittest.TestCase):
    def test_whiteouts_opaque_metadata_and_replaced_hardlink_target(self):
        d, f, h, w = tarfile.DIRTYPE, tarfile.REGTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE
        cap = {'SCHILY.xattr.security.capability': '\x01\x00\x00\x02\udc80\x00'}
        base = layer([('.', d, None, {}), ('a', f, b'old', cap), ('b', h, 'a', {}),
                      ('c', h, 'a', {}), ('.hidden', f, b'keep', {}),
                      ('gone', d, None, {}), ('gone/file', f, b'delete', {}),
                      ('gone-alias', f, b'delete', {}),
                      ('opaque', d, None, {}), ('opaque/old', f, b'delete', {})])
        upper = layer([('.', d, None, {'SCHILY.xattr.trusted.overlay.impure': 'y'}),
                       ('a', f, b'new', {}), ('gone', w, None, {}), ('gone-alias', h, 'gone', {}),
                       ('opaque', d, None, {'SCHILY.xattr.trusted.overlay.opaque': 'y'}),
                       ('opaque/new', f, b'new', {})])
        output = io.BytesIO()
        with base, upper, tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as dst:
            stats = merge(base, upper, dst)
        output.seek(0)
        with tarfile.open(fileobj=output, mode='r:') as result:
            self.assertEqual(result.extractfile('a').read(), b'new')
            self.assertEqual(result.extractfile('b').read(), b'old')
            self.assertEqual(result.extractfile('c').read(), b'old')
            self.assertEqual(result.getmember('c').linkname, 'b')
            b = result.getmember('b')
            self.assertEqual((b.uid, b.gid, b.mode), (42, 43, 0o4755))
            self.assertEqual(b.pax_headers['SCHILY.xattr.security.capability'], cap['SCHILY.xattr.security.capability'])
            self.assertEqual(b.pax_headers['hdrcharset'], 'BINARY')
            self.assertIn('.hidden', result.getnames())
            self.assertNotIn('gone/file', result.getnames())
            self.assertNotIn('gone', result.getnames())
            self.assertNotIn('gone-alias', result.getnames())
            self.assertNotIn('opaque/old', result.getnames())
            self.assertFalse(result.getmember('opaque').pax_headers)
        self.assertEqual(stats['hardlinks'], 1)

    def test_rejects_metacopy(self):
        base = layer([('.', tarfile.DIRTYPE, None, {})])
        upper = layer([('.', tarfile.DIRTYPE, None, {}),
                       ('file', tarfile.REGTYPE, b'', {'SCHILY.xattr.trusted.overlay.metacopy': 'y'})])
        with base, upper, tarfile.open(fileobj=io.BytesIO(), mode='w') as dst:
            with self.assertRaisesRegex(ValueError, 'Unsupported overlay'):
                merge(base, upper, dst)

    @unittest.skipUnless(shutil.which('sqfstar') and SQFS2TAR,
                         'Set SQFS2TAR for the native root-metadata round trip')
    def test_root_metadata_survives_native_squashfs(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, image = Path(directory) / 'root.tar', Path(directory) / 'root.squashfs'
            with tarfile.open(archive, 'w') as dst:
                root = tarfile.TarInfo('.')
                root.type, root.uid, root.gid, root.mode, root.mtime = tarfile.DIRTYPE, 42, 43, 0o750, 1700000000
                dst.addfile(root)
            implementation['build_squashfs'](archive, image)
            result = subprocess.run([SQFS2TAR, '--root-becomes', '.', '--no-skip', str(image)],
                                    capture_output=True, check=True)
            with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:') as src:
                root = src.getmember('.')
                self.assertEqual((root.uid, root.gid, root.mode, root.mtime), (42, 43, 0o750, 1700000000))


if __name__ == '__main__':
    unittest.main()
