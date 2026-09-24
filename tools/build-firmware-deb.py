#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a local piano DSP firmware deb from explicitly supplied, hashed inputs.

Uses dpkg-deb ownership handling as in the liuqin packaging workflow (see NOTICE).
No firmware is downloaded, executed, flashed, installed or licensed for redistribution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from debian.deb822 import Deb822


def sha(path):
    with path.open('rb') as src:
        return hashlib.file_digest(src, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-dir', type=Path, required=True, help='Extracted stock modem image directory')
    parser.add_argument('--output', type=Path, required=True, help='New private directory for the local deb')
    parser.add_argument('--maintainer', required=True, help='Local package builder identity, Name <email>')
    args = parser.parse_args()
    if '\n' in args.maintainer or '\r' in args.maintainer:
        parser.error('Maintainer must be one control-file field')
    repo = Path(__file__).resolve().parent.parent
    source_lock = repo / 'firmware/piano-os3.0.303.0.json'
    inputs = json.loads(source_lock.read_text())
    names = [row['name'] for row in inputs['files']]
    if len(names) != len(set(names)) or any(Path(name).name != name or name in ('.', '..') for name in names):
        raise ValueError('Firmware lock must contain unique flat filenames')
    firmware = args.firmware_dir.resolve()
    for row in inputs['files']:
        source = firmware / row['name']
        if not stat.S_ISREG(source.lstat().st_mode) or source.stat().st_size != row['bytes']:
            raise ValueError(f'Expected matching regular firmware file: {row["name"]}')
    os.umask(0o022)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    name = inputs['package']
    archive = out / f'{name}_{inputs["version"]}_all.deb'
    partial = archive.with_suffix('.deb.partial')
    with tempfile.TemporaryDirectory(prefix='stage-', dir=out) as temporary:
        stage = Path(temporary)
        stage.chmod(0o755)
        payload = stage / inputs['firmware_directory']
        payload.mkdir(parents=True)
        for row in inputs['files']:
            target = payload / row['name']
            shutil.copyfile(firmware / row['name'], target)
            target.chmod(0o644)
            if sha(target) != row['sha256']:
                raise ValueError(f'Firmware hash mismatch: {row["name"]}')
        docs = stage / 'usr/share/doc' / name
        docs.mkdir(parents=True)
        shutil.copyfile(source_lock, docs / 'inputs.json')
        (docs / 'copyright').write_text(
            'Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n'
            'Files: *\n'
            'Copyright: Not determined from the supplied firmware\n'
            'License: proprietary-unknown\n'
            ' No firmware redistribution permission has been established.\n'
            ' This package is generated locally from the user-supplied matching stock inputs.\n'
            ' The MIT license on the builder does not grant rights to these firmware bytes.\n')
        # Debian's KiB estimate for this regular-file/directory-only payload.
        installed_kib = sum((p.stat().st_size + 1023) // 1024 if p.is_file() else 1
                            for p in [stage, *stage.rglob('*')])
        control = stage / 'DEBIAN'
        control.mkdir()
        fields = Deb822({'Package': name, 'Version': inputs['version'], 'Architecture': 'all',
                         'Installed-Size': str(installed_kib),
                         'Maintainer': args.maintainer, 'Section': 'non-free/kernel', 'Priority': 'optional',
                         'Description': 'Local Xiaomi Pad 8 Pro DSP firmware inputs\n'
                                        ' User-supplied ADSP/CDSP images and service maps in a device namespace.\n'
                                        ' No redistribution rights or hardware support are implied.'})
        (control / 'control').write_text(fields.dump())
        files = sorted(p for p in stage.rglob('*') if p.is_file() and control not in p.parents)
        (control / 'md5sums').write_text(''.join(
            f'{hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest()}  {p.relative_to(stage)}\n'
            for p in files))
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(inputs['source_date_epoch']))
        subprocess.run(['dpkg-deb', '--root-owner-group', '--threads-max=1', '-Zxz', '--build', str(stage), str(partial)],
                       env=env, check=True)
    partial.replace(archive)
    manifest = {'state': 'LOCAL_PACKAGE_BUILT_NOT_INSTALLED', 'stock_build': inputs['stock_build'],
                'package': name, 'version': inputs['version'], 'firmware_files': len(names),
                'firmware_directory': '/' + inputs['firmware_directory'],
                'input_lock_sha256': sha(source_lock), 'builder_sha256': sha(Path(__file__)),
                'deb': archive.name, 'deb_bytes': archive.stat().st_size, 'deb_sha256': sha(archive),
                'installed_size_kib': installed_kib,
                'dpkg_deb_version': subprocess.check_output(['dpkg-deb', '--version'], text=True).splitlines()[0],
                'maintainer': args.maintainer, 'redistribution': inputs['redistribution'],
                'limitations': 'No package install, PAS authentication, DSP boot, QRTR service or device test'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
