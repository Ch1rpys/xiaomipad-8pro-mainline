#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read a bounded WN8030 evdev window; never inject events or change LEDs."""
import argparse
import errno
import json
import os
from pathlib import Path
import select
import struct
import time

EVENT = struct.Struct('@llHHi')


def text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def nodes():
    result = []
    for path in sorted(Path('/sys/class/input').glob('event*')):
        device = path / 'device'
        resolved = str(device.resolve())
        if 'a98000.i2c' not in resolved or '-004c/' not in resolved:
            continue
        result.append({'event': path.name, 'name': text(device / 'name'),
                       'path': resolved,
                       'capabilities': {key: text(device / 'capabilities' / key)
                                        for key in ('ev', 'key', 'sw', 'rel', 'abs', 'led')},
                       'modalias': text(device / 'modalias')})
    return result


def snapshot():
    leds = {}
    for led in Path('/sys/class/leds').glob('*'):
        resolved = str(led.resolve())
        if led.name.startswith('nanosic') or ('a98000.i2c' in resolved and '-004c/' in resolved):
            leds[led.name] = {key: text(led / key) for key in ('brightness', 'max_brightness')}
    return {'uptime': text('/proc/uptime'), 'release': os.uname().release,
            'input': nodes(),
            'leds': leds,
            'modules': text('/proc/modules')}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seconds', type=int, default=30, choices=range(1, 46))
    args = ap.parse_args()
    opened, pending, events, lifecycle, errors = {}, {}, [], [], []
    before = snapshot()
    deadline = time.monotonic() + args.seconds
    next_scan = 0
    try:
        while time.monotonic() < deadline:
            if time.monotonic() >= next_scan:
                for row in nodes():
                    path = '/dev/input/' + row['event']
                    if path in opened.values():
                        continue
                    try:
                        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                    except OSError as exc:
                        errors.append({'path': path, 'error': str(exc)})
                        continue
                    opened[fd], pending[fd] = path, b''
                    lifecycle.append({'action': 'open', 'node': row})
                next_scan = time.monotonic() + 0.25
            ready, _, _ = select.select(list(opened), [], [], min(0.25, max(0, deadline - time.monotonic())))
            for fd in ready:
                try:
                    data = os.read(fd, EVENT.size * 128)
                except OSError as exc:
                    if exc.errno == errno.EAGAIN:
                        continue
                    if exc.errno != errno.ENODEV:
                        errors.append({'path': opened[fd], 'error': str(exc)})
                    data = b''
                if not data:
                    lifecycle.append({'action': 'closed', 'path': opened[fd]})
                    os.close(fd)
                    del opened[fd], pending[fd]
                    continue
                data = pending[fd] + data
                size = len(data) // EVENT.size * EVENT.size
                for sec, usec, kind, code, value in EVENT.iter_unpack(data[:size]):
                    events.append({'path': opened[fd], 'time': sec + usec / 1e6,
                                   'type': kind, 'code': code, 'value': value})
                pending[fd] = data[size:]
    finally:
        for fd in opened:
            os.close(fd)
    print(json.dumps({'scope': 'Read-only real evdev capture; LED visibility requires observation',
                      'before': before, 'after': snapshot(), 'events': events,
                      'lifecycle': lifecycle, 'errors': errors}, indent=2))
    print('KEYBOARD_CAPTURE_DONE')


if __name__ == '__main__':
    main()
