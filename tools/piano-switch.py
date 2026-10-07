#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Switch an unlocked piano's active A-slot boot triplet from Fastboot.

Both directories must contain boot.img/init_boot.img/vendor_boot.img and
SHA256SUMS. Rollback inputs are checked before the first write. Partition names
are queried from the current bootloader; no historical Linux sdX names are used.
"""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess

NAMES = ('init_boot', 'vendor_boot', 'boot')  # Publish the kernel last.


def load(directory):
    expected = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split()
        if name in [n + '.img' for n in NAMES]:
            if name in expected or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('Ambiguous or invalid image digest')
            expected[name] = digest
    for name in NAMES:
        path = directory / (name + '.img')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected.get(path.name):
            raise ValueError('Image digest mismatch: ' + str(path))
    return directory


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--rollback', type=Path, required=True)
    a = p.parse_args()
    if not re.fullmatch('[A-Za-z0-9]+', a.serial):
        p.error('Invalid serial')
    desired, restore = load(a.images), load(a.rollback)

    def run(*args):
        r = subprocess.run(['fastboot', '-s', a.serial, *args], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        print(r.stdout, end='', flush=True)
        if r.returncode:
            raise RuntimeError('Fastboot failed: ' + ' '.join(args))
        return r.stdout

    for key, expected in [('product', 'piano'), ('unlocked', 'yes'), ('current-slot', 'a'), ('is-userspace', 'no')]:
        if not re.search(re.escape(key) + r':\s*' + expected + r'\b', run('getvar', key)):
            p.error('Current Fastboot identity does not match piano active A')
    for name in NAMES:
        match = re.search(r'partition-size:' + name + r'_a:\s*((?:0x)?[0-9a-fA-F]+)',
                          run('getvar', 'partition-size:' + name + '_a'))
        if not match or any((d / (name + '.img')).stat().st_size != int(match[1], 16) for d in (desired, restore)):
            p.error('Complete image size does not match current partition: ' + name)
    try:
        for name in NAMES:
            run('flash', name + '_a', str(desired / (name + '.img')))
    except Exception:
        print('Write failed; restoring the checked rollback triplet before returning the error.', flush=True)
        for name in NAMES:
            run('flash', name + '_a', str(restore / (name + '.img')))
        raise
    print('Active A boot triplet written; remain in Fastboot for a RAM readback before reboot.')


if __name__ == '__main__':
    main()
