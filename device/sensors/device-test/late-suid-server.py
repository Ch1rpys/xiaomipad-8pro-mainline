#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""QEMU-only availability gate around the existing upstream SSC mock.

Wire encoding, QMI and QRTR remain upstream. Hide accel for its first two SUID
queries, then expose the existing synthetic sensor. Never run on a tablet.
"""
import json
import os
from pathlib import Path
import runpy
import sys

assert b'linux,dummy-virt' in Path('/sys/firmware/devicetree/base/compatible').read_bytes()
server, command = sys.argv[1:]
sys.path.insert(0, str(Path(server).resolve().parent))
from ssc_server.ssc import SSC

original = SSC.generate_protobuf_discovery_response
counts = {}
events = Path('/run/ssc-late-suid-events.jsonl')
events.write_text('')
os.environ['SSC_MOCK_SUPERVISOR_PID'] = str(os.getpid())


def discovery(data_type):
    counts[data_type] = counts.get(data_type, 0) + 1
    hide = data_type == 'accel' and counts[data_type] <= 2
    with events.open('a') as stream:
        stream.write(json.dumps(dict(data_type=data_type, count=counts[data_type], hide=hide))+'\n')
    if not hide:
        return original(data_type)
    read_data = SSC._read_data
    SSC._read_data = staticmethod(lambda: [row for row in read_data() if row['sensor']['data_type'] != 'accel'])
    try:
        return original(data_type)
    finally:
        SSC._read_data = staticmethod(read_data)


SSC.generate_protobuf_discovery_response = staticmethod(discovery)
sys.argv = [server, command]
runpy.run_path(server, run_name='__main__')
