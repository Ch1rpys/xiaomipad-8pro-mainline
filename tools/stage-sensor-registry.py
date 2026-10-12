#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage an OWN-device extracted persist sensors/registry as a private seed.

Input is the outer registry directory, containing registry/ and optional stock
metadata. Output is an installable private tree, never a public package/repo.
This tool does not mount, read or contact a tablet or modify running services.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat


def stage(source, output):
    if source.is_symlink() or not (source / 'registry').is_dir():
        raise ValueError('expected full sensors/registry parent containing registry/')
    files = {}
    for path in source.rglob('*'):
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('refusing link or special file: ' + str(path))
        if path.is_file():
            files[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError('empty private input; omit staging to use stock defaults')
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    dest = output / 'usr/share/piano/sensors/registry-private'
    shutil.copytree(source, dest)
    for path in dest.rglob('*'):
        path.chmod(0o500 if path.is_dir() else 0o400)
    dest.chmod(0o500)
    (output / 'private-manifest.json').write_text(json.dumps({
        'scope': 'PRIVATE: device calibration, never redistribute',
        'destination': '/usr/share/piano/sensors/registry-private', 'sha256': files,
    }, indent=2) + '\n')
    (output / 'private-manifest.json').chmod(0o600)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    stage(args.registry, args.output)
