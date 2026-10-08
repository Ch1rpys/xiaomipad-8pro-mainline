# SPDX-License-Identifier: MIT
"""piano-slot-success against synthetic GPT disks; every refusal path writes nothing."""
import contextlib
import fcntl
import io
import json
import struct
import tempfile
import unittest
from unittest import mock

import fakepiano as fp
from fakepiano import slot

tool = fp.load_tool('piano-slot-success')
UNMARKED, MARKED = 0x37, 0x77  # prio 3, active, retry 6; plus bit 54


class Base(unittest.TestCase):
    layout = 'xiaomi'
    lun_name = 'sde'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = fp.FakePiano(self.tmp.name, boot_lun_name=self.lun_name, layout=self.layout)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = tool.main(list(argv), host=self.p.host)
        return rc, json.loads(out.getvalue())

    def refused(self, code, *argv):
        before = self.p.all_disks()
        rc, report = self.run_tool(*(argv or ('--mark',)))
        self.assertEqual((rc, report['state'], report.get('code')), (1, 'refused', code), report)
        self.assertEqual(self.p.all_disks(), before, 'a refusal must not write')
        return report


class Mark(Base):
    def test_marks_only_bit_54_in_both_copies(self):
        others = {k: v for k, v in self.p.all_disks().items() if k != self.p.lun4.name}
        before = self.p.lun4.raw()
        rc, report = self.run_tool('--mark')
        self.assertEqual((rc, report['state']), (0, 'marked'), report)
        self.assertEqual(report['disk'], self.lun_name)
        self.assertEqual(report['scsi'], '0:0:0:4')
        self.assertTrue(report['boot_a']['successful'])
        for which in ('primary', 'backup'):
            self.assertEqual(self.p.lun4.attrs('boot_a', which), fp.attrs(MARKED))
            self.assertEqual(self.p.lun4.attrs('boot_b', which), fp.attrs(0x02))
        after = self.p.lun4.raw()
        changed = [i for i in range(len(before)) if before[i] != after[i]]
        lbs, last = fp.LBS, fp.DISK_LBAS - 1
        backup_entries = fp.DISK_LBAS - (7 if self.layout == 'xiaomi' else 4)
        index = next(i for i, r in enumerate(self.p.lun4.rows) if r.name == 'boot_a')
        allowed = {2 * lbs + index * 128 + 54, backup_entries * lbs + index * 128 + 54}
        for header in (lbs, last * lbs):
            allowed |= set(range(header + 16, header + 20)) | set(range(header + 88, header + 92))
        self.assertTrue(set(changed) <= allowed, sorted(set(changed) - allowed))
        self.assertIn(2 * lbs + index * 128 + 54, changed)
        self.assertEqual(after[2 * lbs + index * 128 + 54], before[2 * lbs + index * 128 + 54] | 0x40)
        self.assertEqual({k: v for k, v in self.p.all_disks().items() if k != self.p.lun4.name}, others)
        snaps = sorted(p.name for p in (self.p.root / 'var/lib/piano/slot').iterdir())
        self.assertEqual(len(snaps), 8)
        # The result is a GPT that the validator accepts again, idempotently.
        rc, report = self.run_tool('--mark')
        self.assertEqual((rc, report['state']), (0, 'already-successful'))
        self.assertEqual(self.p.lun4.raw(), after)

    def test_backup_is_written_before_primary(self):
        offsets = []
        real = slot.pwrite_all

        def record(fd, data, offset):
            offsets.append(offset // fp.LBS)
            real(fd, data, offset)
        with mock.patch.object(slot, 'pwrite_all', record):
            self.assertEqual(self.run_tool('--mark')[0], 0)
        backup_entries = fp.DISK_LBAS - (7 if self.layout == 'xiaomi' else 4)
        self.assertEqual(offsets, [backup_entries, fp.DISK_LBAS - 1, 2, 1])

    def test_signals_blocked_while_writing(self):
        seen = []
        real = slot.pwrite_all

        def record(fd, data, offset):
            seen.append(slot.signal.SIGTERM in slot.signal.pthread_sigmask(slot.signal.SIG_BLOCK, []))
            real(fd, data, offset)
        with mock.patch.object(slot, 'pwrite_all', record):
            self.run_tool('--mark')
        self.assertEqual(seen, [True] * 4)
        self.assertNotIn(slot.signal.SIGTERM, slot.signal.pthread_sigmask(slot.signal.SIG_BLOCK, []))

    def test_readback_with_any_other_change_fails(self):
        boot_b = next(i for i, r in enumerate(self.p.lun4.rows) if r.name == 'boot_b')

        def also_boot_b(disk, index):  # a faulty writer: correct CRCs, one extra bit
            entries = bytearray(disk.primary.entries)
            for i in (index, boot_b):
                entries[i * 128 + 54] |= 0x40
            entries, headers = bytes(entries), {}
            for which, copy in (('backup', disk.backup), ('primary', disk.primary)):
                block = bytearray(copy.block)
                struct.pack_into('<I', block, 88, slot.crc32(entries))
                struct.pack_into('<I', block, 16, 0)
                struct.pack_into('<I', block, 16, slot.crc32(block[:92]))
                headers[which] = bytes(block)
            return entries, headers
        with mock.patch.object(tool, 'marked_copies', also_boot_b):
            rc, report = self.run_tool('--mark')
        self.assertEqual((rc, report['code']), (1, 'write-verify-failed'), report)
        self.assertIn('inspect /var/lib/piano/slot/', report['message'])

    def test_check_and_dry_run_never_write(self):
        before = self.p.lun4.raw()
        rc, report = self.run_tool('--check')
        self.assertEqual((rc, report['state']), (1, 'not-successful'))
        rc, report = self.run_tool('--dry-run')
        self.assertEqual((rc, report['state']), (0, 'would-mark'))
        self.assertEqual(report['boot_a_after']['attributes'], f'0x{fp.attrs(MARKED):016x}')
        self.assertEqual(self.p.lun4.raw(), before)
        self.p.set_boot_attrs(a=MARKED)
        rc, report = self.run_tool('--check')
        self.assertEqual((rc, report['state']), (0, 'already-successful'))

    def test_previous_ubuntu_set_may_be_marked(self):
        self.p.fill_slot(self.p.sets['ubuntu.prev'])
        rc, report = self.run_tool('--mark')
        self.assertEqual((rc, report['slot_set']), (0, 'ubuntu.prev'))

    def test_bootconfig_slot_a_is_accepted(self):
        (self.p.root / 'proc/bootconfig').write_text('androidboot.slot_suffix = "_a"\n')
        rc, report = self.run_tool('--mark')
        self.assertEqual((rc, report['source']), (0, 'bootargs+gpt'))

    def test_boot_a_on_a_non_ufs_disk_is_ignored(self):
        fp.FakeDisk(self.p, 'sdz', 0, [fp.Row('boot_a', 6, 8, fp.attrs(UNMARKED)), fp.Row('boot_b', 14, 8)],
                    controller='usb')
        self.assertEqual(self.run_tool('--mark')[0], 0)


class StandardLayout(Mark):
    """Backup array directly below the backup header, as generic tools write it."""
    layout = 'standard'
    lun_name = 'sdc'


class Refusals(Base):
    def test_not_piano(self):
        (self.p.root / 'sys/firmware/devicetree/base/compatible').write_bytes(b'qcom,sm8750-mtp\0')
        self.refused('not-piano')

    def test_not_persistent_boot(self):
        self.p.cmdline(fp.ABL_APPEND)
        self.refused('not-persistent-boot')

    def test_slot_b_and_conflicting_suffixes(self):
        self.p.cmdline(fp.UBUNTU_CMDLINE + ' androidboot.slot_suffix=_b')
        self.refused('not-slot-a')
        (self.p.root / 'proc/bootconfig').write_text('androidboot.slot_suffix = "_a"\n')
        self.refused('slot-suffix-conflict')

    def test_slot_a_not_selected(self):
        self.p.set_boot_attrs(a=0x33)  # active bit clear
        self.refused('slot-a-not-selected')
        self.p.set_boot_attrs(a=UNMARKED, b=0x06)  # B active too
        self.refused('slot-a-not-selected')
        self.p.set_boot_attrs(a=0x36, b=0x02)  # priority 2
        self.refused('slot-a-not-selected')

    def test_unbootable(self):
        self.p.set_boot_attrs(a=UNMARKED | 0x80)
        self.refused('slot-a-unbootable')
        self.refused('slot-a-unbootable', '--check')

    def test_retry_zero_unsuccessful(self):
        self.p.set_boot_attrs(a=0x07)
        report = self.refused('retry-count-zero')
        self.assertEqual(report['boot_a']['retry'], 0)

    def gpt(self, code, edit=None, after_seal=None):
        self.p.lun4.write_gpt(edit=edit, after_seal=after_seal)
        self.refused(code)

    def test_signature(self):
        self.gpt('gpt-signature', after_seal=lambda b: b['backup_header'].__setitem__(slice(0, 8), b'EFI JUNK'))

    def test_revision(self):
        self.gpt('gpt-revision', edit=lambda b: struct.pack_into('<I', b['primary_header'], 8, 0x00020000))

    def test_header_size(self):
        self.gpt('gpt-header-size', edit=lambda b: struct.pack_into('<I', b['backup_header'], 12, 91))

    def test_primary_header_crc(self):
        self.gpt('gpt-header-crc', after_seal=lambda b: b['primary_header'].__setitem__(40, 7))

    def test_backup_header_crc(self):
        # A stale backup header is refused, not rebuilt from the primary.
        self.gpt('gpt-header-crc', after_seal=lambda b: struct.pack_into('<I', b['backup_header'], 16, 1))

    def test_primary_entries_crc(self):
        self.gpt('gpt-entries-crc', after_seal=lambda b: b['primary_entries'].__setitem__(5000, 1))

    def test_backup_entries_crc(self):
        self.gpt('gpt-entries-crc', after_seal=lambda b: b['backup_entries'].__setitem__(5000, 1))

    def test_copies_differ_with_valid_crcs(self):
        self.gpt('gpt-copies-differ', edit=lambda b: b['backup_entries'].__setitem__(9 * 128 + 54, 0x40))

    def test_header_fields_differ(self):
        self.gpt('gpt-header-fields-differ', edit=lambda b: b['backup_header'].__setitem__(60, 0xaa))

    def test_my_alternate_cross_links(self):
        self.gpt('gpt-lba-links', edit=lambda b: struct.pack_into('<Q', b['primary_header'], 32, fp.DISK_LBAS - 2))

    def test_entry_array_location(self):
        # The backup header declares the primary's array: valid CRC, wrong place.
        self.gpt('gpt-entries-location', edit=lambda b: struct.pack_into('<Q', b['backup_header'], 72, 2))

    def test_entry_array_declared_in_usable_area(self):
        self.gpt('gpt-entries-location', edit=lambda b: struct.pack_into('<Q', b['backup_header'], 72, 100))

    def test_entry_geometry(self):
        self.gpt('gpt-entry-geometry', edit=lambda b: struct.pack_into('<I', b['primary_header'], 84, 256))

    def test_missing_boot_a(self):
        for row in self.p.lun4.rows:
            if row.name.startswith('boot_'):
                row.name = 'spare' + row.name[4:]
        self.p.lun4.write_gpt()
        self.refused('boot-lun-missing')

    def test_duplicate_boot_a(self):
        next(r for r in self.p.lun4.rows if r.name == 'abl_a').name = 'boot_a'
        self.p.lun4.write_gpt()
        self.refused('name-duplicate')

    def test_boot_entries_on_two_luns(self):
        self.p.lun1.rows[0].name = 'boot_b'
        self.p.lun1.write_gpt()
        self.refused('boot-lun-ambiguous')

    def test_unreadable_other_lun_fails_closed(self):
        self.p.lun1.write_gpt(after_seal=lambda b: b['primary_header'].__setitem__(40, 9))
        self.refused('gpt-header-crc')

    def test_fastboot_booted_debug_image(self):
        self.p.cmdline(fp.UBUNTU_CMDLINE + ' piano.debug=1 piano.debug_timeout=900 ' + fp.ABL_APPEND)
        self.refused('not-booted-from-slot')

    def test_other_command_line(self):
        self.p.cmdline(fp.UBUNTU_CMDLINE.replace('panic=15', 'panic=30') + ' ' + fp.ABL_APPEND)
        self.refused('not-booted-from-slot')

    def test_unregistered_slot_set(self):
        self.p.fill_slot(fp.image_set('ubuntu', 'host-release'))
        report = self.refused('slot-set-unregistered')
        self.assertIn('import-ubuntu', report['message'])

    def test_android_store_set_does_not_vouch(self):
        android_like = fp.image_set('ubuntu', 'x')
        self.p.store_set('android', android_like)
        self.p.fill_slot(android_like)
        self.refused('slot-set-unregistered')

    def test_read_only_disk(self):
        (self.p.lun4.sys / 'ro').write_text('1\n')
        self.refused('disk-read-only')

    def test_lock_shared_with_switch(self):
        with open(self.p.root / 'run/piano-boot-switch.lock', 'a') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.refused('locked')

    def test_geometry_disagreement(self):
        part = self.p.lun4.sys / f'{self.p.lun4.name}2'
        (part / 'size').write_text('8\n')
        self.refused('partition-geometry')


class Cli(unittest.TestCase):
    def test_modes_are_exclusive_and_required(self):
        for argv in ([], ['--check', '--mark']):
            with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
                tool.main(argv, host=slot.Host('/nonexistent'))
            self.assertEqual(ctx.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
