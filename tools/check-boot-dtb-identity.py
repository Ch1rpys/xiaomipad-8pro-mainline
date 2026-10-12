#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check a RAM image's DTB identity against an explicitly recorded booted DTB.

Uses AOSP unpack_bootimg and dtc's fdtget; never accesses a device. The expected
identity and evidence belong in the local test package, not in public code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


PROPERTIES = ('compatible', 'model', 'qcom,msm-id', 'qcom,board-id')


def root_identity(dtb, fdtget):
    result = {}
    for name in PROPERTIES:
        cells = name.startswith('qcom,')
        raw = subprocess.check_output(
            [str(fdtget), '-t', 'x' if cells else 'bx', str(dtb), '/', name], text=True)
        values = [int(v, 16) for v in raw.split()]
        if cells:
            result[name] = values
        else:
            data = bytes(values)
            if not data.endswith(b'\0'):
                raise ValueError(f'Unterminated DTB identity string: {name}')
            result[name] = data[:-1].decode().split('\0')
    return result


def verify(boot, dtb, reference_dtb, expected, unpack_bootimg, fdtget):
    if set(expected) != set(PROPERTIES):
        raise ValueError('Expected all four DTB root identity properties')
    for name, path in (('booted reference', reference_dtb), ('packaged DTB', dtb)):
        actual = root_identity(path, fdtget)
        if actual != expected:
            raise ValueError(f'{name} root identity mismatch: {actual!r} != {expected!r}')
    # Check the actual boot payload, not only a sidecar that may be stale.
    with tempfile.TemporaryDirectory(prefix='.dtb-identity-', dir=dtb.parent) as tmp:
        subprocess.run([sys.executable, str(unpack_bootimg), '--boot_img', str(boot),
                        '--out', tmp], check=True, capture_output=True)
        embedded = Path(tmp) / 'dtb'
        if embedded.read_bytes() != dtb.read_bytes():
            raise ValueError('Embedded DTB differs from the packaged DTB')
        if root_identity(embedded, fdtget) != expected:
            raise ValueError('Embedded DTB root identity mismatch')
    return {'state': 'OFFLINE_DTB_IDENTITY_PASS_NOT_DEVICE_BOOT', 'identity': expected,
            'dtb_sha256': hashlib.sha256(dtb.read_bytes()).hexdigest(),
            'scope': 'Identity and container agreement only; ABL selection needs a device boot'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('boot', 'dtb', 'reference-dtb', 'package-json', 'unpack-bootimg', 'fdtget'):
        ap.add_argument('--' + name, type=Path, required=True)
    a = ap.parse_args()
    expected = json.loads(a.package_json.read_text())['dtb_identity']['expected']
    print(json.dumps(verify(a.boot, a.dtb, a.reference_dtb, expected,
                            a.unpack_bootimg, a.fdtget), indent=2))


if __name__ == '__main__':
    main()
