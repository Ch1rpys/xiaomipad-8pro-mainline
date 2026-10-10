# SPDX-License-Identifier: MIT
"""tools/extract-boot-partitions.py: a map made from sfdisk --json is one piano-boot-switch accepts."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import fakepiano as fp

TOOL = fp.BOOT.parents[1] / 'tools/extract-boot-partitions.py'


def load():
    loader = importlib.machinery.SourceFileLoader('extract_boot_partitions', str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def sfdisk_json(disk):
    """What util-linux sfdisk --json prints for a FakeDisk: upper-case GUIDs, sector units."""
    return {'partitiontable': {
        'label': 'gpt', 'id': disk.disk_guid.upper(), 'device': f'/dev/{disk.name}', 'unit': 'sectors',
        'firstlba': 6, 'lastlba': fp.DISK_LBAS - 8, 'sectorsize': fp.LBS,
        'partitions': [{'node': f'/dev/{disk.name}{i}', 'start': r.first, 'size': r.last - r.first + 1,
                        'type': r.type_guid.upper(), 'uuid': r.unique_guid.upper(), 'name': r.name,
                        **({'attrs': f'GUID:{",".join(str(b) for b in range(48, 64) if r.attrs >> b & 1)}'}
                           if r.attrs else {})}
                       for i, r in enumerate(disk.rows, 1)]}}


class BootPartitions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = fp.FakePiano(self.tmp.name)
        self.tool = load()
        self.profile = {n: {'capacity': size} for n, size in fp.SIZES.items()}

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_switch_accepts_the_generated_map(self):
        work = self.p.root / 'host'
        work.mkdir()
        (work / 'boot-lun.json').write_text(json.dumps(sfdisk_json(self.p.lun4), indent=3))
        (work / 'boot-profile.json').write_text(json.dumps(self.profile))
        installed = self.p.root / 'etc/piano/boot-partitions.json'
        expected = {r['label']: r for r in json.loads(installed.read_text())}
        installed.unlink()
        # The JSON on standard input, as when it is piped from nc.
        r = subprocess.run([sys.executable, '-I', str(TOOL), '--input', '-',
                            '--profile', str(work / 'boot-profile.json'), '--output', str(installed)],
                           input=(work / 'boot-lun.json').read_text(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.stat(installed).st_mode & 0o777, 0o600)
        self.assertEqual({r['label']: r for r in json.loads(installed.read_text())}, expected)
        switch = fp.load_tool('piano-boot-switch')
        for command in ('status', 'verify'):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(switch.main([command], host=self.p.host), 0, out.getvalue())
            self.assertEqual(json.loads(out.getvalue())['occupant'], 'ubuntu')
        again = subprocess.run([sys.executable, '-I', str(TOOL), '--input', str(work / 'boot-lun.json'),
                                '--profile', str(work / 'boot-profile.json'), '--output', str(installed)],
                               capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0, 'an existing map is never overwritten')

    def test_refuses_other_luns_and_wrong_sizes(self):
        with self.assertRaisesRegex(ValueError, 'not the boot LUN'):
            self.tool.boot_partitions(sfdisk_json(self.p.lun0), self.profile)
        profile = dict(self.profile, init_boot={'capacity': fp.SIZES['init_boot'] * 2})
        with self.assertRaisesRegex(ValueError, 'init_boot_a is'):
            self.tool.boot_partitions(sfdisk_json(self.p.lun4), profile)
        table = sfdisk_json(self.p.lun4)
        table['partitiontable']['partitions'].append(dict(table['partitiontable']['partitions'][1]))
        with self.assertRaisesRegex(ValueError, 'exactly one boot_a'):
            self.tool.boot_partitions(table, self.profile)
        del table['partitiontable']['sectorsize']
        with self.assertRaisesRegex(ValueError, 'sectorsize'):
            self.tool.boot_partitions(table, self.profile)


if __name__ == '__main__':
    unittest.main()
