# SPDX-License-Identifier: MIT
"""Bounded SSC nameservice discovery, without sending QMI sensor requests."""
import socket
import struct
import time


def lookup(seconds=3, wait_for_service=False):
    with socket.socket(getattr(socket, 'AF_QIPCRTR', 42), socket.SOCK_DGRAM) as sock:
        sock.bind((sock.getsockname()[0], 0))
        sock.sendto(struct.pack('<5I', 10, 400, 0, 0, 0), (sock.getsockname()[0], 0xfffffffe))
        deadline, services, complete = time.monotonic() + seconds, [], False
        while time.monotonic() < deadline:
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                packet, peer = sock.recvfrom(4096)
            except socket.timeout:
                break
            if len(packet) != 20 or peer[1] != 0xfffffffe:
                continue
            command, service, instance, node, port = struct.unpack('<5I', packet)
            if command == 4 and service == 400:
                services.append(dict(service=service, version=instance & 255,
                                     instance=instance >> 8, node=node, port=port))
                if wait_for_service:
                    return services
            if command == 4 and service == 0:
                complete = True
                if not wait_for_service:
                    break
        if not complete:
            raise TimeoutError('QRTR nameservice did not complete the lookup')
        return services
