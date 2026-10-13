# SPDX-License-Identifier: MIT
"""MGMT wire errors and first-boot transitions; no Bluetooth/device access."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('address', Path(__file__).with_name('bluetooth-address.py'))
address = importlib.util.module_from_spec(spec)
spec.loader.exec_module(address)


class AddressTests(unittest.TestCase):
    def test_text_address_is_little_endian_on_wire(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'address'
            path.write_text('00:11:22:33:44:55\n')
            self.assertEqual(address.installed_address(path), bytes.fromhex('554433221100'))

    def test_bad_input_never_becomes_an_address(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'address'
            for text in ('', '00:00:00:00:00:00', 'FF:FF:FF:FF:FF:FF',
                         '00:11:22:33:44:55\n00:11:22:33:44:66',
                         '0:11:22:33:44:55', '00:11:22:33:44:gg'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(ValueError):
                        address.installed_address(path)

    def test_command_status_uses_kernel_opcode_then_status_layout(self):
        # include/net/bluetooth/mgmt.h: __le16 opcode; __u8 status.
        mgmt = address.Management.__new__(address.Management)
        mgmt.sock = Mock()
        mgmt.receive = Mock(side_effect=[(2, 3, struct.pack('<HB', 0x0039, 0x0a))])
        with self.assertRaisesRegex(RuntimeError, '0x0039.*0x0a'):
            mgmt.command(0x0039, 3, bytes.fromhex('554433221100'))
        mgmt.sock.sendall.assert_called_once_with(
            struct.pack('<HHH', 0x0039, 3, 6) + bytes.fromhex('554433221100'))

    def test_foreign_command_completion_is_ignored(self):
        mgmt = address.Management.__new__(address.Management)
        mgmt.sock = Mock()
        mgmt.receive = Mock(side_effect=[
            (1, 2, struct.pack('<HB', 0x0039, 0) + bytes(4)),
            (1, 3, struct.pack('<HB', 0x0039, 0) + bytes(4))])
        self.assertEqual(mgmt.command(0x0039, 3), bytes(4))

    def test_configured_controller_does_not_need_or_read_a_file(self):
        mgmt = Mock(index_generation=0)
        mgmt.indexes.return_value = [4]
        with patch.object(address, 'Management', return_value=mgmt), \
             patch.object(address, 'onboard', return_value=True), \
             patch.object(address, 'installed_address') as read:
            address.configure(1, Path('/missing'))
            read.assert_not_called()
            mgmt.command.assert_not_called()
            mgmt.sock.close.assert_called_once()

    def test_only_onboard_unconfigured_controller_is_changed_then_reenumerated(self):
        mgmt = Mock(index_generation=0)
        mgmt.indexes.side_effect = [[1], [2, 3], [7]]
        mgmt.command.side_effect = [struct.pack('<HII', 29, 2, 2), bytes(4)]
        raw = bytes.fromhex('554433221100')
        with patch.object(address, 'Management', return_value=mgmt), \
             patch.object(address, 'onboard', side_effect=lambda i: i in (3, 7)), \
             patch.object(address, 'installed_address', return_value=raw):
            address.configure(1, Path('/unit'))
        self.assertEqual(mgmt.command.call_args_list[1].args,
                         (address.SET_PUBLIC_ADDRESS, 3, raw))
        self.assertEqual([c.args[0] for c in mgmt.indexes.call_args_list],
                         [address.READ_INDEX_LIST, address.READ_UNCONFIGURED, address.READ_INDEX_LIST])
        mgmt.sock.close.assert_called_once()

    def test_other_missing_configuration_is_not_overridden(self):
        mgmt = Mock(index_generation=0)
        mgmt.indexes.side_effect = [[], [3]]
        mgmt.command.return_value = struct.pack('<HII', 29, 3, 3)
        with patch.object(address, 'Management', return_value=mgmt), \
             patch.object(address, 'onboard', return_value=True), \
             patch.object(address, 'installed_address') as read:
            with self.assertRaisesRegex(RuntimeError, 'beyond its public address'):
                address.configure(1, Path('/unit'))
            read.assert_not_called()
        mgmt.sock.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
