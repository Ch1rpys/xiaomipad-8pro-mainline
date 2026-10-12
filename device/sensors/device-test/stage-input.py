#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage this tablet's saved stock files and extracted persist registry, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stock-root', type=Path, required=True, help='saved vendor/ and odm/ trees from this tablet')
    p.add_argument('--registry', type=Path, required=True, help='already extracted registry/registry from the verified persist backup')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    vendor = args.stock_root/'vendor/etc/sensors'
    odm = args.stock_root/'odm/etc/sensors'
    for directory in (vendor, odm, args.registry):
        if not directory.is_dir() or any(f.is_symlink() for f in directory.rglob('*')):
            p.error('require complete regular directory without symlinks: ' + str(directory))
    if not (odm/'config/json.lst').is_file() or not (vendor/'sns_reg_config').is_file():
        p.error('missing stock ODM json.lst or vendor sns_reg_config')
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    root = args.output/'hexagonfs/sensors'
    root.mkdir(parents=True)
    shutil.copytree(odm, root/'odm')
    shutil.copytree(vendor, root/'vendor')
    # Retain the upstream conventional vendor mapping without merging ODM data.
    shutil.copytree(vendor/'config', root/'config')
    shutil.copy2(vendor/'sns_reg_config', root/'sns_reg.conf')
    shutil.copytree(args.registry, root/'registry')
    names = (odm/'config/json.lst').read_text().splitlines()
    referenced = []
    for name in names:
        if Path(name).name != name:
            p.error('unsafe entry in stock json.lst: ' + repr(name))
        referenced.append({'name': name, 'odm_exists': (odm/'config'/name).is_file(),
                           'other_saved_stock_paths': [str(f.relative_to(args.stock_root))
                               for f in args.stock_root.rglob(name) if f.is_file()]})
    status = {'scope': 'Private local input, no device access, not for publication',
              'registry_files': sum(f.is_file() for f in args.registry.rglob('*')),
              'odm_files': sum(f.is_file() for f in odm.rglob('*')),
              'vendor_files': sum(f.is_file() for f in vendor.rglob('*')),
              'json_list_entries': referenced,
              'registry_pristine_sha256': {str(f.relative_to(args.registry)): sha(f)
                                          for f in sorted(args.registry.rglob('*')) if f.is_file()}}
    (args.output/'input-status.json').write_text(json.dumps(status, indent=2)+'\n')


if __name__ == '__main__':
    main()
