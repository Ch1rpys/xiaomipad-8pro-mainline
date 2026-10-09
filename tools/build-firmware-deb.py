#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the piano firmware deb from the locked firmware tree.

The payload is every file selected by firmware/piano-*.json, copied from the
repository's firmware/ tree or from --firmware-tree (an owner's own extraction
with the same layout), plus the capture topology built from device/audio.
Every file is checked against its locked size and SHA-256. Uses dpkg-deb
ownership handling as in the liuqin packaging workflow (see NOTICE). Nothing is
downloaded, executed, flashed or installed.
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
import firmware_payload
from firmware_payload import sha

PACKAGE = 'piano-local-firmware'
VERSION = '0.2+os3.0.303.0'
SOURCE_DATE_EPOCH = 0


def license_paragraph(files, copyright, name, text):
    body = ''.join(f' {line}\n' if line.strip() else ' .\n' for line in text.strip('\n').splitlines())
    return f'Files: {files}\nCopyright: {copyright}\nLicense: {name}\n{body}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-tree', type=Path, default=firmware_payload.REPO_FIRMWARE,
                        help='Tree with the /usr/lib/firmware layout (default: the repository firmware/ tree)')
    parser.add_argument('--topology', type=Path, required=True,
                        help='Capture topology built from device/audio (Piano-Capture-Diag-tplg.bin)')
    parser.add_argument('--output', type=Path, required=True, help='New directory for the deb and its manifest')
    parser.add_argument('--maintainer', required=True, help='Local package builder identity, Name <email>')
    args = parser.parse_args()
    if '\n' in args.maintainer or '\r' in args.maintainer:
        parser.error('Maintainer must be one control-file field')
    repo = Path(__file__).resolve().parent.parent
    rows = firmware_payload.load_tree()
    locks = sorted(firmware_payload.REPO_FIRMWARE.glob('piano-*.json'))
    builds = {json.loads(p.read_text()).get('stock_build') for p in locks} - {None}
    if len(builds) != 1:
        parser.error('The firmware locks must name one stock build')
    topology = json.loads((repo / 'device/audio/diagnostic.json').read_text())['topology']
    status = args.topology.lstat()
    if (not stat.S_ISREG(status.st_mode) or status.st_size != topology['bytes'] or
            sha(args.topology) != topology['sha256']):
        parser.error('Topology does not match device/audio/diagnostic.json')
    os.umask(0o022)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    archive = out / f'{PACKAGE}_{VERSION}_all.deb'
    partial = archive.with_suffix('.deb.partial')
    with tempfile.TemporaryDirectory(prefix='stage-', dir=out) as temporary:
        stage = Path(temporary)
        stage.chmod(0o755)
        firmware = stage / firmware_payload.FIRMWARE_ROOT
        firmware_payload.stage_tree(rows, args.firmware_tree, firmware)
        target = firmware / topology['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.topology, target)
        target.chmod(0o644)
        docs = stage / 'usr/share/doc' / PACKAGE
        docs.mkdir(parents=True)
        inputs = {'stock_build': builds.pop(), 'files': rows,
                  'topology': {k: topology[k] for k in ('path', 'bytes', 'sha256')}}
        (docs / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
        (docs / 'copyright').write_text(
            'Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\n' +
            license_paragraph('*', 'Respective rights holders of the stock firmware',
                              'LicenseRef-Proprietary-Firmware',
                              (repo / 'LICENSES/LicenseRef-Proprietary-Firmware.txt').read_text()) + '\n' +
            license_paragraph(f'usr/lib/firmware/{topology["path"]}',
                              '2021-2024 Linaro Ltd.; the piano mainline project contributors', 'BSD-3-Clause',
                              (repo / 'LICENSES/audioreach-BSD-3-Clause.txt').read_text()))
        # Debian's KiB estimate for this regular-file/directory-only payload.
        installed_kib = sum((p.stat().st_size + 1023) // 1024 if p.is_file() else 1
                            for p in [stage, *stage.rglob('*')])
        control = stage / 'DEBIAN'
        control.mkdir()
        fields = Deb822({'Package': PACKAGE, 'Version': VERSION, 'Architecture': 'all',
                         'Installed-Size': str(installed_kib),
                         'Maintainer': args.maintainer, 'Section': 'non-free/kernel', 'Priority': 'optional',
                         'Description': 'Xiaomi Pad 8 Pro stock firmware\n'
                                        ' Unmodified ADSP, GPU, Bluetooth, Wi-Fi, touch and keyboard-bridge\n'
                                        ' firmware from stock build OS3.0.303.0.WPYCNXM, and the audio capture\n'
                                        ' topology built from device/audio. No firmware license is granted.'})
        (control / 'control').write_text(fields.dump())
        files = sorted(p for p in stage.rglob('*') if p.is_file() and control not in p.parents)
        (control / 'md5sums').write_text(''.join(
            f'{hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest()}  {p.relative_to(stage)}\n'
            for p in files))
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(SOURCE_DATE_EPOCH))
        subprocess.run(['dpkg-deb', '--root-owner-group', '--threads-max=1', '-Zxz', '--build', str(stage), str(partial)],
                       env=env, check=True)
    partial.replace(archive)
    manifest = {'state': 'LOCAL_PACKAGE_BUILT_NOT_INSTALLED', 'stock_build': inputs['stock_build'],
                'package': PACKAGE, 'version': VERSION, 'firmware_files': len(rows),
                'firmware_tree': ('repository firmware/' if args.firmware_tree.resolve() == firmware_payload.REPO_FIRMWARE
                                  else 'owner-supplied --firmware-tree'),
                'input_locks_sha256': {p.name: sha(p) for p in locks},
                'topology_sha256': topology['sha256'], 'builder_sha256': sha(Path(__file__)),
                'payload_builder_sha256': sha(Path(firmware_payload.__file__)),
                'deb': archive.name, 'deb_bytes': archive.stat().st_size, 'deb_sha256': sha(archive),
                'installed_size_kib': installed_kib,
                'dpkg_deb_version': subprocess.check_output(['dpkg-deb', '--version'], text=True).splitlines()[0],
                'maintainer': args.maintainer,
                'limitations': 'No package install, firmware load or device test'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
