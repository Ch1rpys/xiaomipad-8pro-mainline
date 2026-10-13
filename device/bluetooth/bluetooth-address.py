#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Configure an unconfigured Piano controller from its installed unit address.

The Linux Bluetooth MGMT API preserves the normal hci_qca/BlueZ lifecycle.
This is a bounded initialization step, independent of the boot image format.
"""
import argparse
import ctypes
from pathlib import Path
import socket
import struct
import sys
import time

INDEX_NONE = 0xffff
PUBLIC_ADDRESS = 2
READ_INDEX_LIST = 0x0003
READ_UNCONFIGURED = 0x0036
READ_CONFIG = 0x0037
SET_PUBLIC_ADDRESS = 0x0039
COMPATIBLES = {b'qcom,wcn7860-bt'}


def onboard(index):
    node = Path(f'/sys/class/bluetooth/hci{index}/device/of_node/compatible')
    try:
        return bool(COMPATIBLES.intersection(node.read_bytes().split(b'\0')))
    except FileNotFoundError:
        return False


class Management:
    def __init__(self, timeout):
        self.deadline = time.monotonic() + timeout
        self.index_generation = 0
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW,
                                  socket.BTPROTO_HCI)
        # CPython's HCI bind tuple does not expose HCI_CHANNEL_CONTROL. Bind
        # the standard sockaddr_hci with libc, then use normal socket I/O.
        address = ctypes.create_string_buffer(struct.pack('=HHH',
            socket.AF_BLUETOOTH, INDEX_NONE, 3))
        libc = ctypes.CDLL(None, use_errno=True)
        libc.bind.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_uint)
        libc.bind.restype = ctypes.c_int
        if libc.bind(self.sock.fileno(), address, 6):
            code = ctypes.get_errno()
            self.sock.close()
            raise OSError(code, 'Cannot bind Bluetooth MGMT control socket')

    def receive(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Timed out waiting for onboard Bluetooth initialization')
        self.sock.settimeout(remaining)
        packet = self.sock.recv(65535)
        if len(packet) < 6:
            raise ValueError('Short Bluetooth MGMT packet')
        event, index, size = struct.unpack_from('<HHH', packet)
        if len(packet) != size + 6:
            raise ValueError('Invalid Bluetooth MGMT packet length')
        if event in (4, 5, 0x001d, 0x001e):
            self.index_generation += 1
        return event, index, packet[6:]

    def wait_change(self, generation):
        while self.index_generation == generation:
            self.receive()

    def command(self, opcode, index=INDEX_NONE, payload=b''):
        self.sock.sendall(struct.pack('<HHH', opcode, index, len(payload)) + payload)
        while True:
            event, target, data = self.receive()
            if target != index:
                continue
            if event == 1 and len(data) >= 3:
                reply, status = struct.unpack_from('<HB', data)
                if reply == opcode:
                    if status:
                        raise RuntimeError(f'Bluetooth MGMT command {opcode:#06x} failed ({status:#04x})')
                    return data[3:]
            elif event == 2 and len(data) >= 3:
                reply, status = struct.unpack_from('<HB', data)
                if reply == opcode and status:
                    raise RuntimeError(f'Bluetooth MGMT command {opcode:#06x} rejected ({status:#04x})')

    def indexes(self, opcode):
        data = self.command(opcode)
        if len(data) < 2:
            raise ValueError('Short Bluetooth controller list')
        count, = struct.unpack_from('<H', data)
        if len(data) != 2 + 2 * count:
            raise ValueError('Invalid Bluetooth controller list length')
        return struct.unpack_from('<' + 'H' * count, data, 2)


def installed_address(path):
    text = path.read_text().strip()
    parts = text.split(':')
    if len(parts) != 6 or any(len(p) != 2 or
            any(c not in '0123456789abcdefABCDEF' for c in p) for p in parts):
        raise ValueError('Expected one six-octet Bluetooth address in the unit file')
    raw = bytes(int(p, 16) for p in parts)
    if raw in (b'\0' * 6, b'\xff' * 6):
        raise ValueError('Invalid unit Bluetooth address')
    # File is MSB-first text; MGMT bdaddr_t is LSB-first.
    return raw[::-1]


def configure(timeout, address_file):
    mgmt = Management(timeout)
    try:
        while True:
            generation = mgmt.index_generation
            for index in mgmt.indexes(READ_INDEX_LIST):
                if onboard(index):
                    print('Onboard Bluetooth already configured; factory address unchanged.')
                    return
            for index in mgmt.indexes(READ_UNCONFIGURED):
                if not onboard(index):
                    continue
                data = mgmt.command(READ_CONFIG, index)
                if len(data) != 10:
                    raise ValueError('Invalid Bluetooth configuration information')
                _, supported, missing = struct.unpack('<HII', data)
                if missing != PUBLIC_ADDRESS or not supported & PUBLIC_ADDRESS:
                    raise RuntimeError('Onboard Bluetooth needs configuration beyond its public address')
                result = mgmt.command(SET_PUBLIC_ADDRESS, index, installed_address(address_file))
                if len(result) != 4 or struct.unpack('<I', result)[0]:
                    raise RuntimeError('Onboard Bluetooth remains unconfigured after address submission')
                print('Bluetooth address supplied; waiting for controller readiness.')
                # SET_PUBLIC_ADDRESS can change the index. Re-enumerate instead
                # of assuming the old hci number survives reinitialization.
                while True:
                    generation = mgmt.index_generation
                    if any(onboard(i) for i in mgmt.indexes(READ_INDEX_LIST)):
                        print('Onboard Bluetooth configured; BlueZ can take over.')
                        return
                    mgmt.wait_change(generation)
            # Subscribe before waiting: the two list commands register normal
            # and unconfigured index events with the kernel management API.
            mgmt.wait_change(generation)
    finally:
        mgmt.sock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=20,
                        help='total controller initialization timeout in seconds')
    parser.add_argument('--address-file', type=Path, default=Path('/etc/piano/bluetooth-address'))
    parser.add_argument('--check-source', action='store_true',
                        help='only validate the available identity source; do not configure Bluetooth')
    args = parser.parse_args()
    if not 0 < args.timeout <= 60:
        parser.error('timeout must be between 0 and 60 seconds')
    if b'xiaomi,piano' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0'):
        raise ValueError('This helper is for Xiaomi piano only')
    if args.check_source:
        installed_address(args.address_file)
        print('Bluetooth identity source is readable and valid.')
    else:
        configure(args.timeout, args.address_file)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Bluetooth factory address: {error}', file=sys.stderr)
        sys.exit(1)
