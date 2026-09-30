#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Snapshot a verified module subset and emit gen_init_cpio input (no module loading)."""
import argparse
from pathlib import Path
import shutil

from kernel_modules import runtime_metadata, sha, verified_subset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modules-tree', type=Path, required=True)
    parser.add_argument('--stage', type=Path, required=True)
    args = parser.parse_args()
    source = args.modules_tree.resolve()
    manifest = verified_subset(source)
    stage = args.stage.resolve()
    stage.mkdir(parents=True, exist_ok=False)
    for name, expected in manifest['files'].items():
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        if sha(target) != expected:
            raise ValueError(f'Module changed during copy: {name}')
    for name, data in runtime_metadata(manifest).items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    helper = Path(__file__).resolve().parents[1] / 'initramfs/piano-modules'
    (stage / 'bin').mkdir()
    shutil.copyfile(helper, stage / 'bin/piano-modules')
    for path in sorted(stage.rglob('*')):
        name = '/' + str(path.relative_to(stage))
        # These common directories are emitted by build-initramfs.sh.
        if path.is_dir() and name not in ('/bin', '/etc', '/lib'):
            print(f'dir {name} 0755 0 0')
        elif path.is_file():
            mode = '0755' if name == '/bin/piano-modules' else '0644'
            print(f'file {name} {path} {mode} 0 0')


if __name__ == '__main__':
    main()
