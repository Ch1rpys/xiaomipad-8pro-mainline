#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage verified local DSP firmware for a native package recipe or RAM initramfs.

The output contains a plain payload root and a manifest; it is not an installed
package and carries no firmware redistribution permission. Requires only Python.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

import firmware_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New private output directory')
    parser.add_argument('--lock', type=Path, default=Path(__file__).resolve().parents[1] / 'firmware/piano-os3.0.303.0.json')
    parser.add_argument('--image', action='append', help='MDT header to select; repeat as needed, default all files')
    args = parser.parse_args()
    lock = firmware_payload.load_lock(args.lock)
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error('Output must not already exist')
    os.umask(0o022)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.piano-firmware-', dir=output.parent) as temporary:
        result = Path(temporary) / 'result'
        stage = result / 'root'
        stage.mkdir(parents=True)
        result.chmod(0o700)
        rows = firmware_payload.stage_payload(lock, args.firmware_dir, stage, args.image)
        manifest = {'state': 'LOCAL_PAYLOAD_STAGED_NOT_INSTALLED',
                    'stock_build': lock['stock_build'], 'firmware_directory': lock['firmware_directory'],
                    'images': args.image, 'files': rows,
                    'input_lock_sha256': firmware_payload.sha(args.lock),
                    'builder_sha256': firmware_payload.sha(__file__),
                    'payload_builder_sha256': firmware_payload.sha(firmware_payload.__file__),
                    'redistribution': lock['redistribution']}
        (result / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        result.rename(output)
    print(json.dumps({'state': manifest['state'], 'files': len(rows), 'output': str(output)}))


if __name__ == '__main__':
    main()
